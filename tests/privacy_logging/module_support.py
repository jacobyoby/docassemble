"""Exercise the frozen Python draft, not the production Go capture boundary."""
import contextlib
import hashlib
import importlib.util
import io
import logging
import os
from pathlib import Path
import sys
import tempfile
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
WEBAPP = ROOT / "docassemble_webapp/docassemble/webapp"
REFERENCE = ROOT / "tests/privacy_logging/reference"
MODULE = "docassemble.webapp.log_initialize"

# Keep this historical design executable without allowing it to masquerade as
# the current production logger. New capture tests use the actual source module.
for filename, expected in (
    ("log_initialize.py", "93f5e7b14ff7162edef330246bf99d30b34d96fadfac1314eaa593103dd89cb1"),
    ("privacy_logging.py", "0cf784e0d0e3997ba334b511c419fc47ed0f37d560777c1ad1b1c0dc39843634"),
):
    if hashlib.sha256((REFERENCE / filename).read_bytes()).hexdigest() != expected:
        raise RuntimeError("frozen application logger reference changed")


def package(name, path=None):
    module = types.ModuleType(name)
    module.__path__ = [] if path is None else [str(path)]
    return module


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# No installed docassemble package or service configuration is imported.
for name, path in (("docassemble", None), ("docassemble.base", None),
                   ("docassemble.webapp", WEBAPP)):
    sys.modules[name] = package(name, path)
sys.modules["docassemble.webapp"].__path__.insert(0, str(REFERENCE))
privacy = load("docassemble.webapp.privacy_logging", REFERENCE / "privacy_logging.py")


@contextlib.contextmanager
def fixture(context="web", logserver=None, debug=False, stderr=None):
    with tempfile.TemporaryDirectory() as directory:
        config = types.ModuleType("docassemble.webapp.config")
        config.LOGSERVER = logserver
        config.LOG_DIRECTORY = directory
        config.daconfig = {"log to std": context == "std"}
        config.in_celery = context == "celery"
        config.in_cron = context == "cron"
        base = types.ModuleType("docassemble.base.logger")
        base.callback = lambda message: sys.stderr.write(message)
        base.set_logmessage = lambda cb: setattr(base, "callback", cb)
        base.logmessage = lambda message: base.callback(message)
        capture = io.StringIO() if stderr is None else stderr
        previous = logging.Logger.manager.loggerDict.pop("docassemble", None)
        original_class = logging.getLoggerClass()
        state = types.SimpleNamespace(config=config, base=base, stderr=capture,
                                      directory=Path(directory), module=None)
        modules = {"docassemble.webapp.config": config,
                   "docassemble.base.logger": base}
        with patch.dict(sys.modules, modules), patch.object(sys, "stderr", capture), \
                patch.dict(os.environ, {"SUPERVISORLOGLEVEL": "debug" if debug else "info"}):
            try:
                yield state
            finally:
                module = sys.modules.pop(MODULE, None)
                if module is not None:
                    module._silence_logger()
                    module._close_owned_files()
                logging.Logger.manager.loggerDict.pop("docassemble", None)
                if previous is not None:
                    logging.Logger.manager.loggerDict["docassemble"] = previous
                logging.setLoggerClass(original_class)


def start(state):
    state.module = load(MODULE, REFERENCE / "log_initialize.py")
    return state.module
