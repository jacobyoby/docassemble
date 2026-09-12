"""Execute real startup modules up to the first post-logger dependency boundary."""
import contextlib
import importlib
import io
import json
import runpy
import sys
import types
import unittest
from unittest.mock import patch

from module_support import MODULE, WEBAPP, fixture, package


class AfterLogging(Exception):
    """Stop the synthetic application before database or service initialization."""


class SyntheticApp:
    @property
    def secret_key(self):
        return None

    @secret_key.setter
    def secret_key(self, value):
        raise AfterLogging()


def stub(name, **attrs):
    result = types.ModuleType(name)
    result.__dict__.update(attrs)
    return result


@contextlib.contextmanager
def startup_dependencies(state):
    base_config = stub("docassemble.base.config", loaded=False)
    def base_load(**kwargs):
        state.config.in_celery = kwargs.get("in_celery", False)
        base_config.loaded = True
    base_config.load = base_load
    modules = {
        "werkzeug": package("werkzeug"),
        "werkzeug.middleware": package("werkzeug.middleware"),
        "werkzeug.middleware.proxy_fix": stub("werkzeug.middleware.proxy_fix", ProxyFix=object),
        "docassemble.base.plugin_manager": stub("docassemble.base.plugin_manager", pm=object()),
        "docassemble.webapp.extensions": stub("docassemble.webapp.extensions", **{
            name: object() for name in ("csrf", "cors", "babel", "lm", "the_user_manager", "kv_session", "db")}),
        "docassemble.webapp.setup": stub("docassemble.webapp.setup", init_app=lambda app: None),
        "docassemble.webapp.app_object": stub("docassemble.webapp.app_object", flaskapp=SyntheticApp()),
        "docassemble.base.config": base_config,
        "celery": stub("celery", Celery=object, chord=object),
    }
    root = sys.modules["docassemble"]
    base = sys.modules["docassemble.base"]
    webapp = sys.modules["docassemble.webapp"]
    with patch.dict(sys.modules, modules), \
            patch.object(root, "base", base, create=True), \
            patch.object(root, "webapp", webapp, create=True), \
            patch.object(base, "config", base_config, create=True):
        for name in ("app_initialize", "flask_app", "worker", "server"):
            sys.modules.pop("docassemble.webapp." + name, None)
        yield base_config


class TestActualStartupPaths(unittest.TestCase):
    def test_web_and_log_to_std_reach_import_time_protection(self):
        for context in ("web", "std"):
            with self.subTest(context=context), fixture(context) as state, startup_dependencies(state):
                with self.assertRaises(AfterLogging):
                    importlib.import_module("docassemble.webapp.server")
                module = sys.modules[MODULE]
                self.assertTrue(module._configured)
                state.base.logmessage("SYNTHETIC_PRIVATE_MARKER")
                output = ((state.directory / "docassemble.log").read_text()
                          if context == "web" else state.stderr.getvalue())
                self.assertEqual(json.loads(output)["event"], "UNKNOWN")
                self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", output)

    def test_actual_worker_sets_celery_then_installs_safe_callback(self):
        # Begin in default web context: the real worker must select Celery.
        with fixture() as state, startup_dependencies(state) as base_config:
            with self.assertRaises(AfterLogging):
                importlib.import_module("docassemble.webapp.worker")
            self.assertTrue(base_config.loaded)
            self.assertTrue(state.config.in_celery)
            self.assertTrue(sys.modules[MODULE]._configured)
            state.base.logmessage("SYNTHETIC_PRIVATE_MARKER")
            self.assertEqual(json.loads(state.stderr.getvalue())["event"], "UNKNOWN")
            self.assertFalse((state.directory / "docassemble.log").exists())

    def test_actual_cron_launcher_selects_cron_for_server_startup(self):
        calls = []
        def launch(argv, **kwargs):
            calls.append((argv, kwargs))
            return types.SimpleNamespace(returncode=0)
        with patch("subprocess.run", side_effect=launch), \
                patch.object(sys, "argv", ["cron.py", "-type", "cron_daily"]):
            with self.assertRaises(SystemExit) as stopped:
                runpy.run_path(str(WEBAPP / "cron.py"), run_name="__main__")
        self.assertEqual(stopped.exception.code, 0)
        argv, options = calls[0]
        self.assertEqual(argv[:3], ["flask", "--app", "docassemble.webapp.server"])
        self.assertEqual(options["env"]["IN_CRON"], "true")
        # The Flask CLI and config loader are synthetic, not live dependencies.
        with fixture() as state, startup_dependencies(state):
            state.config.in_cron = options["env"]["IN_CRON"] == "true"
            with self.assertRaises(AfterLogging):
                importlib.import_module("docassemble.webapp.server")
            self.assertTrue(sys.modules[MODULE]._configured)
            state.base.logmessage("SYNTHETIC_PRIVATE_MARKER")
            self.assertEqual(json.loads(state.stderr.getvalue())["event"], "UNKNOWN")
            self.assertFalse((state.directory / "docassemble.log").exists())

    def test_worker_no_sink_fails_before_post_logging_startup(self):
        stream = io.StringIO()
        stream.close()
        with fixture(stderr=stream) as state, startup_dependencies(state):
            with self.assertRaisesRegex(RuntimeError, "^Privacy logging unavailable$"):
                importlib.import_module("docassemble.webapp.worker")
            self.assertTrue(state.config.in_celery)
            state.base.logmessage("SYNTHETIC_PRIVATE_MARKER")


if __name__ == "__main__":
    unittest.main()
