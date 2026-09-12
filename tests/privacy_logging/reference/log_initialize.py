"""Install the allowlisted application logger in every application context."""

import logging
import os
import sys
import time

sys_logger = None
_configured = False
_log_files = []


class UnsilenceableLogger(logging.Logger):
    def isEnabledFor(self, level):
        return level >= self.level


def syslog_message(message):
    """Discard legacy free text without inspecting or stringifying it."""
    try:
        if sys_logger is not None:
            record = logging.LogRecord("docassemble", logging.DEBUG, "", 0,
                                       "*", (), None)
            record.event_code = "UNKNOWN"
            sys_logger.handle(record)
    except Exception:
        # Neither the message nor the logging failure is safe to print.
        pass


def syslog_message_with_timestamp(message):
    # The safe formatter supplies UTC time; do not concatenate the message.
    syslog_message(message)


def _close_owned_files():
    for stream in _log_files:
        try:
            stream.close()
        except Exception:
            pass
    _log_files.clear()


def _silence_logger():
    if sys_logger is not None:
        sys_logger.handlers.clear()
        sys_logger.filters.clear()
        sys_logger.propagate = False
        # Prevent logging.lastResort from becoming a raw stderr fallback.
        sys_logger.addHandler(logging.NullHandler())


def _attach_stream(stream):
    from .privacy_logging import PrivacyStreamHandler
    try:
        if stream is None:
            return False
        # Detect already closed or failing sinks without logging user data.
        stream.write("")
        stream.flush()
        sys_logger.addHandler(PrivacyStreamHandler(stream=stream))
        return True
    except Exception:
        return False


def add_log_handler(log_directory=None, *, to_std=False):
    """Return whether at least one usable safe sink was installed."""
    if to_std:
        return _attach_stream(sys.stderr)
    if log_directory is None:
        from docassemble.webapp.config import LOG_DIRECTORY
        log_directory = LOG_DIRECTORY
    added = False
    for attempt in range(5):
        try:
            stream = open(os.path.join(log_directory, "docassemble.log"),
                          "a", encoding="utf-8")
            _log_files.append(stream)
            added = _attach_stream(stream)
            if not added:
                _close_owned_files()
            break
        except OSError:
            if attempt < 4:
                time.sleep(1)
        except Exception:
            break
    if os.environ.get("SUPERVISORLOGLEVEL", "info") == "debug":
        added = _attach_stream(sys.stderr) or added
    return added


def initialize():
    """Fail startup with a fixed error if no safe application sink exists.

    Celery, cron and log-to-std retain their stderr destination. All contexts
    replace the base callback, including the failure path once it is available.
    """
    global sys_logger, _configured
    _configured = False
    previous_class = None
    failed = False
    try:
        previous_class = logging.getLoggerClass()
        logging.setLoggerClass(UnsilenceableLogger)
        sys_logger = logging.getLogger("docassemble")
        _silence_logger()
        _close_owned_files()
        sys_logger.disabled = False
        sys_logger.setLevel(logging.DEBUG)
        from docassemble.base.logger import set_logmessage
        # Install before config/sink setup so failure cannot restore raw output.
        set_logmessage(syslog_message)
        from docassemble.webapp.config import (
            LOGSERVER, LOG_DIRECTORY, daconfig, in_celery, in_cron,
        )
        to_std = in_celery or in_cron or daconfig.get("log to std", False)
        if not add_log_handler(LOG_DIRECTORY, to_std=to_std):
            raise RuntimeError("Privacy logging unavailable")
        if LOGSERVER is None:
            set_logmessage(syslog_message_with_timestamp)
        _configured = True
    except Exception:
        failed = True
        try:
            _silence_logger()
        except Exception:
            pass
        _close_owned_files()
    finally:
        if previous_class is not None:
            try:
                logging.setLoggerClass(previous_class)
            except Exception:
                failed = True
    if failed:
        _configured = False
        # Drop our raw error context and suppress any active caller exception.
        raise RuntimeError("Privacy logging unavailable") from None


initialize()
