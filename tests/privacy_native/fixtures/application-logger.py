"""Synthetic dependencies around real application startup and base logging."""
import importlib
import logging
import os
from pathlib import Path
import sys
import types


def module(name, **attributes):
    value = types.ModuleType(name)
    value.__dict__.update(attributes)
    sys.modules[name] = value
    return value


def package(name, path=None):
    return module(name, __path__=[] if path is None else [str(path)])


def main():
    root = Path(sys.argv[1])
    directory = Path(sys.argv[2])
    context, logserver, debug = sys.argv[3:6]
    package('docassemble')
    package('docassemble.base', root / 'docassemble_base/docassemble/base')
    webapp = package('docassemble.webapp', root / 'docassemble_webapp/docassemble/webapp')
    from docassemble.base import logger
    original_callback = logger.the_logmessage
    config = module('docassemble.webapp.config', LOG_DIRECTORY=str(directory),
                    LOGSERVER=None if logserver == 'none' else 'synthetic',
                    daconfig={'log to std': context == 'std'},
                    in_celery=context == 'celery', in_cron=context == 'cron')
    os.environ['SUPERVISORLOGLEVEL'] = debug
    package('werkzeug')
    package('werkzeug.middleware')
    module('werkzeug.middleware.proxy_fix', ProxyFix=object)
    module('docassemble.base.plugin_manager', pm=object())
    module('docassemble.webapp.extensions', **{name: object() for name in
           ('csrf', 'cors', 'babel', 'lm', 'the_user_manager', 'kv_session', 'db')})
    module('docassemble.webapp.setup', init_app=lambda app: logger.logmessage('SYNTHETIC_PRIVATE_SETUP'))

    class AfterLogging(Exception):
        pass

    class SyntheticApp:
        @property
        def secret_key(self):
            return None

        @secret_key.setter
        def secret_key(self, value):
            logger.logmessage('SYNTHETIC_PRIVATE_INITIALIZED')
            raise AfterLogging()

    logger.logmessage('SYNTHETIC_PRIVATE_BEFORE')
    startup = importlib.import_module('docassemble.webapp.app_initialize')
    try:
        startup.init_app(SyntheticApp())
    except AfterLogging:
        pass
    else:
        raise AssertionError('actual startup did not reach the post-logging boundary')
    assert not list(directory.iterdir()), 'application initialization opened an independent log file'
    assert logger.the_logmessage is original_callback, 'base stderr callback was replaced'
    entrypoint = sys.modules['docassemble.webapp.log_initialize']
    importlib.reload(entrypoint)
    assert logger.the_logmessage is original_callback
    assert not list(directory.iterdir()), 'reimport opened an independent log file'
    # Exercise third-party reconfiguration after initialization as well as the
    # real base callback. Go owns retained output regardless of these formatters.
    logging.basicConfig(level=logging.DEBUG, force=True)
    logging.getLogger('SYNTHETIC_PRIVATE_LOGGER').warning('SYNTHETIC_PRIVATE_AFTER')
    logger.logmessage('SYNTHETIC_PRIVATE_BASE_AFTER')
    print('SYNTHETIC_PRIVATE_STDOUT', flush=True)
    assert config.daconfig == {'log to std': context == 'std'}
    assert webapp.__path__ == [str(root / 'docassemble_webapp/docassemble/webapp')]


if __name__ == '__main__':
    main()
