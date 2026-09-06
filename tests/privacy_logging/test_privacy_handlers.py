import unittest
import logging
import json
import io
import sys

from module_support import privacy, ROOT

from docassemble.webapp.privacy_logging import (
    PrivacyFormatter,
    PrivacyStreamHandler,
    SAFE_EVENT_CODES,
    EVENT_UNKNOWN,
    SVC,
    COMP,
    _FALLBACK,
    safe_format_record,
)


def _make_record(**overrides):
    defaults = dict(
        name="test.logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="ignored message",
        args=(),
        exc_info=None,
    )
    defaults.update(overrides)
    return logging.LogRecord(**defaults)


class TestPrivacyStreamHandlerSafeError(unittest.TestCase):

    def test_write_failure_no_stderr_output(self):
        class FailStream(io.StringIO):
            def write(self, s):
                raise OSError("disk full")

        buf = io.StringIO()
        handler = PrivacyStreamHandler(stream=FailStream())
        handler.setFormatter(PrivacyFormatter())

        old_stderr = sys.stderr
        sys.stderr = buf
        try:
            r = _make_record(msg="192.0.2.1 secret data")
            r.event_code = "FORM_START"
            handler.emit(r)
        finally:
            sys.stderr = old_stderr

        self.assertEqual(buf.getvalue(), "")
        self.assertNotIn("192.0.2.1", buf.getvalue())
        self.assertNotIn("secret data", buf.getvalue())

    def test_flush_failure_no_stderr_output(self):
        class FlushFailStream(io.StringIO):
            def flush(self):
                raise OSError("flush broken")

        buf = io.StringIO()
        handler = PrivacyStreamHandler(stream=FlushFailStream())
        handler.setFormatter(PrivacyFormatter())

        old_stderr = sys.stderr
        sys.stderr = buf
        try:
            r = _make_record(msg="198.51.100.1 private info")
            handler.emit(r)
        finally:
            sys.stderr = old_stderr

        self.assertEqual(buf.getvalue(), "")

    def test_failure_counter_increments(self):
        class FailStream(io.StringIO):
            def write(self, s):
                raise OSError("fail")

        handler = PrivacyStreamHandler(stream=FailStream())
        handler.setFormatter(PrivacyFormatter())
        self.assertEqual(handler.failure_count, 0)

        r = _make_record()
        handler.emit(r)
        self.assertEqual(handler.failure_count, 1)
        handler.emit(r)
        self.assertEqual(handler.failure_count, 2)

    def test_failure_counter_bounded(self):
        class FailStream(io.StringIO):
            def write(self, s):
                raise OSError("fail")

        handler = PrivacyStreamHandler(stream=FailStream())
        handler.setFormatter(PrivacyFormatter())
        r = _make_record()
        for _ in range(200):
            handler.emit(r)
        self.assertLessEqual(
            handler.failure_count, PrivacyStreamHandler._FAILURE_MAX
        )

    def test_successful_write_to_stream(self):
        stream = io.StringIO()
        handler = PrivacyStreamHandler(stream=stream)
        handler.setFormatter(PrivacyFormatter())

        r = _make_record()
        r.event_code = "FORM_START"
        handler.emit(r)

        output = stream.getvalue()
        self.assertTrue(len(output) > 0)
        parsed = json.loads(output.strip())
        self.assertEqual(parsed["event"], "FORM_START")
        self.assertEqual(parsed["svc"], SVC)
        self.assertEqual(parsed["comp"], COMP)


class TestHandlerFormatterLockdown(unittest.TestCase):
    """Handler must always use PrivacyFormatter; no raw fallback path."""

    def test_default_construction_no_formatter_set(self):
        stream = io.StringIO()
        handler = PrivacyStreamHandler(stream=stream)
        r = _make_record(msg="SYNTHETIC_PRIVATE_MARKER")
        handler.emit(r)
        output = stream.getvalue()
        self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", output)
        parsed = json.loads(output.strip())
        self.assertEqual(parsed["svc"], SVC)

    def test_setFormatter_none_still_safe(self):
        stream = io.StringIO()
        handler = PrivacyStreamHandler(stream=stream)
        handler.setFormatter(None)
        r = _make_record(msg="SYNTHETIC_PRIVATE_MARKER")
        handler.emit(r)
        output = stream.getvalue()
        self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", output)
        parsed = json.loads(output.strip())
        self.assertEqual(parsed["event"], EVENT_UNKNOWN)

    def test_setFormatter_generic_formatter_rejected(self):
        stream = io.StringIO()
        handler = PrivacyStreamHandler(stream=stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        r = _make_record(msg="SYNTHETIC_PRIVATE_MARKER")
        handler.emit(r)
        output = stream.getvalue()
        self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", output)
        parsed = json.loads(output.strip())
        self.assertEqual(parsed["svc"], SVC)

    def test_setFormatter_raw_formatter_rejected(self):
        stream = io.StringIO()
        handler = PrivacyStreamHandler(stream=stream)
        handler.setFormatter(logging.Formatter(
            "%(name)s %(levelname)s %(message)s %(safe_diag)s"
        ))
        r = _make_record(
            name="private_client_192.0.2.1",
            msg="raw message content",
        )
        r.safe_diag = "192.0.2.1 /interview?session=secret"
        handler.emit(r)
        output = stream.getvalue()
        self.assertNotIn("private_client", output)
        self.assertNotIn("192.0.2.1", output)
        self.assertNotIn("raw message content", output)
        self.assertNotIn("session=secret", output)
        parsed = json.loads(output.strip())
        self.assertEqual(set(parsed.keys()), {"ts", "level", "svc", "comp", "event"})

    def test_handle_via_handler_handle_default_construction(self):
        stream = io.StringIO()
        handler = PrivacyStreamHandler(stream=stream)
        r = _make_record(msg="SYNTHETIC_PRIVATE_MARKER")
        handler.handle(r)
        output = stream.getvalue()
        self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", output)

    def test_write_failure_after_formatter_override_no_stderr(self):
        class FailStream(io.StringIO):
            def write(self, s):
                raise OSError("disk full")

        buf = io.StringIO()
        handler = PrivacyStreamHandler(stream=FailStream())
        handler.setFormatter(logging.Formatter("%(message)s"))

        old_stderr = sys.stderr
        sys.stderr = buf
        try:
            r = _make_record(msg="SYNTHETIC_PRIVATE_MARKER")
            handler.emit(r)
        finally:
            sys.stderr = old_stderr

        self.assertEqual(buf.getvalue(), "")
        self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", buf.getvalue())


class TestHandlerFlushSafety(unittest.TestCase):
    """flush() must not propagate exceptions or leak to stderr."""

    def test_direct_flush_failure_does_not_raise(self):
        class FlushFailStream(io.StringIO):
            def flush(self):
                raise RuntimeError("SYNTHETIC_PRIVATE_MARKER")

        handler = PrivacyStreamHandler(stream=FlushFailStream())
        handler.flush()

    def test_direct_flush_failure_no_stderr(self):
        class FlushFailStream(io.StringIO):
            def flush(self):
                raise RuntimeError("SYNTHETIC_PRIVATE_MARKER")

        handler = PrivacyStreamHandler(stream=FlushFailStream())
        buf = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = buf
        try:
            handler.flush()
        finally:
            sys.stderr = old_stderr
        self.assertEqual(buf.getvalue(), "")
        self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", buf.getvalue())

    def test_flush_failure_counts_once(self):
        class FlushFailStream(io.StringIO):
            def flush(self):
                raise OSError("broken")

        handler = PrivacyStreamHandler(stream=FlushFailStream())
        self.assertEqual(handler.failure_count, 0)
        handler.flush()
        self.assertEqual(handler.failure_count, 1)
        handler.flush()
        self.assertEqual(handler.failure_count, 2)

    def test_close_with_flush_failure_does_not_raise(self):
        class FlushFailStream(io.StringIO):
            def flush(self):
                raise RuntimeError("SYNTHETIC_PRIVATE_MARKER")

        handler = PrivacyStreamHandler(stream=FlushFailStream())
        handler.close()

    def test_shutdown_simulation_no_stderr_leak(self):
        class FlushFailStream(io.StringIO):
            def flush(self):
                raise RuntimeError("SYNTHETIC_PRIVATE_MARKER")

        handler = PrivacyStreamHandler(stream=FlushFailStream())
        buf = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = buf
        try:
            handler.flush()
            handler.close()
        finally:
            sys.stderr = old_stderr
        self.assertEqual(buf.getvalue(), "")
        self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", buf.getvalue())

    def test_subprocess_shutdown_no_leak(self):
        script = (
            "import logging, sys, io\n"
            "from module_support import privacy\n"
            "from docassemble.webapp.privacy_logging import PrivacyStreamHandler\n"
            "class F(io.StringIO):\n"
            "    def flush(self):\n"
            "        raise RuntimeError('SYNTHETIC_PRIVATE_MARKER')\n"
            "h = PrivacyStreamHandler(stream=F())\n"
            "logging.getLogger('x').addHandler(h)\n"
        )
        old_stderr = sys.stderr
        capture = io.StringIO()
        sys.stderr = capture
        try:
            import subprocess
            result = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=ROOT / "tests/privacy_logging",
            )
        finally:
            sys.stderr = old_stderr
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", result.stderr)
        self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", result.stdout)
        self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", capture.getvalue())



if __name__ == "__main__":
    unittest.main()
