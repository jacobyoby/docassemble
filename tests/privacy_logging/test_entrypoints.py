import builtins
import io
import itertools
import json
import logging
import sys
import traceback
import unittest
from unittest.mock import patch

from module_support import fixture, privacy, start

MARKER = "SYNTHETIC_PRIVATE_MARKER"
KEYS = {"ts", "level", "svc", "comp", "event"}


class Hostile:
    def __str__(self):
        raise AssertionError("message must not be stringified")

    def __repr__(self):
        raise AssertionError("message must not be represented")


class BrokenStream(io.StringIO):
    fail_write = False
    fail_flush = False

    def write(self, value):
        if self.fail_write:
            raise OSError(MARKER)
        return super().write(value)

    def flush(self):
        if self.fail_flush:
            raise OSError(MARKER)
        return super().flush()


class TestRealModuleEntrypoint(unittest.TestCase):
    def assert_safe(self, data, count=1, event="UNKNOWN"):
        self.assertNotIn(MARKER, data)
        rows = [json.loads(line) for line in data.splitlines()]
        self.assertEqual(len(rows), count)
        for row in rows:
            self.assertEqual(set(row), KEYS)
            self.assertEqual(row["svc"], "docassemble")
            self.assertEqual(row["comp"], "app")
            self.assertEqual(row["event"], event)

    def test_every_context_sink_logserver_and_debug_combination(self):
        for context, server, debug in itertools.product(
                ("web", "celery", "cron", "std"), (None, "synthetic"), (False, True)):
            with self.subTest(context=context, server=server, debug=debug):
                with fixture(context, server, debug) as state:
                    module = start(state)
                    self.assertTrue(module._configured)
                    self.assertFalse(module.sys_logger.propagate)
                    callback = (module.syslog_message_with_timestamp if server is None
                                else module.syslog_message)
                    self.assertIs(state.base.callback, callback)
                    state.base.logmessage(MARKER)
                    state.base.logmessage(Hostile())
                    path = state.directory / "docassemble.log"
                    if context == "web":
                        self.assert_safe(path.read_text(), count=2)
                        self.assert_safe(state.stderr.getvalue(), count=2 if debug else 0)
                    else:
                        self.assertFalse(path.exists())
                        self.assert_safe(state.stderr.getvalue(), count=2)

    def test_replaces_existing_raw_handlers_filters_and_disables_propagation(self):
        with fixture() as state:
            raw = io.StringIO()
            old = logging.getLogger("docassemble")
            old.addHandler(logging.StreamHandler(raw))
            old.addFilter(lambda record: (_ for _ in ()).throw(RuntimeError(MARKER)))
            root = logging.getLogger()
            handler = logging.StreamHandler(raw)
            root.addHandler(handler)
            try:
                module = start(state)
                module.sys_logger.error(MARKER, exc_info=(ValueError, ValueError(MARKER), None),
                                        extra={"event_code": "FORM_ERROR", "user": MARKER})
                self.assert_safe((state.directory / "docassemble.log").read_text(),
                                 event="FORM_ERROR")
                self.assertEqual(raw.getvalue(), "")
            finally:
                root.removeHandler(handler)

    def test_reinitialization_closes_owned_file_without_duplicate_output(self):
        with fixture() as state:
            module = start(state)
            previous = module._log_files[0]
            module.initialize()
            self.assertTrue(previous.closed)
            self.assertEqual(len(module._log_files), 1)
            state.base.logmessage(MARKER)
            self.assert_safe((state.directory / "docassemble.log").read_text())

    def test_no_file_sink_fails_closed_after_five_attempts(self):
        with fixture() as state, patch.object(builtins, "open", side_effect=OSError(MARKER)) as opened, \
                patch("time.sleep") as sleep:
            try:
                start(state)
            except RuntimeError as error:
                self.assertEqual(str(error), "Privacy logging unavailable")
                self.assertNotIn(MARKER, traceback.format_exc())
            else:
                self.fail("missing sink did not stop initialization")
            self.assertEqual(opened.call_count, 5)
            self.assertEqual(sleep.call_count, 4)
            state.base.logmessage(MARKER)
            logging.getLogger("docassemble").error(MARKER)
            self.assertEqual(state.stderr.getvalue(), "")

    def test_debug_stderr_remains_safe_when_file_cannot_open(self):
        with fixture(debug=True) as state, patch.object(builtins, "open", side_effect=OSError(MARKER)), \
                patch("time.sleep"):
            self.assertTrue(start(state)._configured)
            state.base.logmessage(MARKER)
            self.assert_safe(state.stderr.getvalue())

    def test_each_stderr_context_rejects_missing_closed_and_failed_sink(self):
        for context, failure in itertools.product(("celery", "cron", "std"),
                                                   ("missing", "closed", "write", "flush")):
            with self.subTest(context=context, failure=failure):
                stream = BrokenStream()
                if failure == "closed":
                    stream.close()
                stream.fail_write = failure == "write"
                stream.fail_flush = failure == "flush"
                with fixture(context, stderr=stream) as state:
                    with patch("sys.stderr", None if failure == "missing" else stream):
                        with self.assertRaisesRegex(RuntimeError, "^Privacy logging unavailable$"):
                            start(state)
                        state.base.logmessage(MARKER)
                        logging.getLogger("docassemble").error(MARKER)
                    if failure != "closed":
                        self.assertEqual(stream.getvalue(), "")

    def test_later_sink_failures_and_shutdown_do_not_print_record_or_error(self):
        for context, mode in itertools.product(("web", "celery", "cron", "std"),
                                               ("write", "flush")):
            with self.subTest(context=context, mode=mode):
                stream = BrokenStream()
                with fixture(context, stderr=stream) as state:
                    module = start(state)
                    if context == "web":
                        safe = next(h for h in module.sys_logger.handlers
                                    if isinstance(h, privacy.PrivacyStreamHandler))
                        safe.stream = stream
                    stream.fail_write = mode == "write"
                    stream.fail_flush = mode == "flush"
                    state.base.logmessage(MARKER)
                    module.sys_logger.error(MARKER)
                    for handler in module.sys_logger.handlers:
                        handler.flush()
                    self.assert_safe(stream.getvalue(), count=0 if mode == "write" else 2)

    def test_configuration_exception_has_fixed_error_and_safe_registered_callback(self):
        class BrokenConfig:
            def get(self, *args):
                raise ValueError(MARKER)
        with fixture() as state:
            state.config.daconfig = BrokenConfig()
            try:
                start(state)
            except RuntimeError as error:
                self.assertEqual(str(error), "Privacy logging unavailable")
                self.assertNotIn(MARKER, traceback.format_exc())
            else:
                self.fail("configuration failure was ignored")
            state.base.logmessage(MARKER)
            self.assertEqual(state.stderr.getvalue(), "")

    def test_callback_logging_exception_does_not_fall_back_to_raw_stderr(self):
        with fixture() as state:
            module = start(state)
            with patch.object(module.sys_logger, "handle", side_effect=RuntimeError(MARKER)):
                state.base.logmessage(MARKER)
                module.syslog_message_with_timestamp(Hostile())
            self.assertEqual(state.stderr.getvalue(), "")

    def test_dependency_import_errors_are_fixed_and_have_no_raw_context(self):
        original_import = builtins.__import__
        for dependency in ("docassemble.base.logger", "docassemble.webapp.config", "privacy_logging"):
            with self.subTest(dependency=dependency), fixture() as state:
                def importing(name, *args, **kwargs):
                    if name == dependency:
                        raise ImportError(MARKER)
                    return original_import(name, *args, **kwargs)
                with patch.object(builtins, "__import__", side_effect=importing):
                    with self.assertRaisesRegex(RuntimeError, "^Privacy logging unavailable$") as caught:
                        start(state)
                self.assertIsNone(caught.exception.__context__)
                self.assertIsNone(caught.exception.__cause__)
                self.assertEqual(state.stderr.getvalue(), "")
                self.assertFalse(sys.modules["docassemble.webapp.log_initialize"]._log_files)
                if dependency != "docassemble.base.logger":
                    state.base.logmessage(MARKER)
                    self.assertEqual(state.stderr.getvalue(), "")

    def test_logger_setup_and_cleanup_errors_do_not_escape_raw(self):
        for method in ("getLoggerClass", "getLogger"):
            with self.subTest(method=method), fixture() as state:
                with patch.object(logging, method, side_effect=RuntimeError(MARKER)):
                    with self.assertRaisesRegex(RuntimeError, "^Privacy logging unavailable$") as caught:
                        start(state)
                self.assertIsNone(caught.exception.__context__)
                self.assertEqual(state.stderr.getvalue(), "")
        with fixture() as state:
            logger = logging.getLogger("docassemble")
            with patch.object(logger, "addHandler", side_effect=RuntimeError(MARKER)):
                with self.assertRaisesRegex(RuntimeError, "^Privacy logging unavailable$") as caught:
                    start(state)
            self.assertIsNone(caught.exception.__context__)
            self.assertEqual(state.stderr.getvalue(), "")

    def test_bad_file_probe_closes_stream_and_debug_file_survives_bad_stderr(self):
        stream = BrokenStream()
        stream.fail_flush = True
        with fixture() as state, patch.object(builtins, "open", return_value=stream):
            with self.assertRaisesRegex(RuntimeError, "^Privacy logging unavailable$"):
                start(state)
            self.assertTrue(stream.closed)
            self.assertEqual(state.stderr.getvalue(), "")
        stream = BrokenStream()
        stream.fail_write = True
        with fixture(debug=True, stderr=stream) as state:
            self.assertTrue(start(state)._configured)
            state.base.logmessage(MARKER)
            self.assert_safe((state.directory / "docassemble.log").read_text())
            self.assertEqual(stream.getvalue(), "")

    def test_fixed_initialization_failure_suppresses_active_caller_exception(self):
        with fixture() as state, patch.object(builtins, "open", side_effect=OSError(MARKER)), \
                patch("time.sleep"):
            try:
                raise ValueError("CALLER_PRIVATE_MARKER")
            except ValueError:
                try:
                    start(state)
                except RuntimeError as error:
                    self.assertEqual(str(error), "Privacy logging unavailable")
                    rendered = traceback.format_exc()
                    self.assertNotIn("CALLER_PRIVATE_MARKER", rendered)
                    self.assertNotIn(MARKER, rendered)
                    self.assertTrue(error.__suppress_context__)
                else:
                    self.fail("missing sink did not fail initialization")


if __name__ == "__main__":
    unittest.main()
