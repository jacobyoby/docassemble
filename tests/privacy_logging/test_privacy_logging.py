import unittest
import logging
import json
import io
import sys

from module_support import privacy

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


class TestPrivacyFormatterNoLeaks(unittest.TestCase):
    """No untrusted field content may appear in formatted output."""

    def setUp(self):
        self.fmt = PrivacyFormatter()

    def out(self, record):
        return self.fmt.format(record)

    def test_ipv4_in_msg_not_in_output(self):
        r = _make_record(msg="client 192.0.2.1 submitted form")
        self.assertNotIn("192.0.2.1", self.out(r))

    def test_ipv6_in_msg_not_in_output(self):
        r = _make_record(msg="client 2001:db8::1 submitted form")
        self.assertNotIn("2001:db8::1", self.out(r))

    def test_ipv4_in_logger_name_not_in_output(self):
        r = _make_record(name="private_client_192.0.2.1")
        self.assertNotIn("192.0.2.1", self.out(r))
        self.assertNotIn("private_client", self.out(r))

    def test_ipv4_in_safe_diag_not_in_output(self):
        r = _make_record()
        r.safe_diag = "192.0.2.1 /interview?i=synthetic.yml session=synthetic-secret"
        self.assertNotIn("192.0.2.1", self.out(r))
        self.assertNotIn("synthetic.yml", self.out(r))
        self.assertNotIn("synthetic-secret", self.out(r))

    def test_encoded_query_in_msg_not_in_output(self):
        r = _make_record(msg="GET /interview?q=%3Ftoken%3Dsecret%26user%3Dadmin")
        self.assertNotIn("token", self.out(r))
        self.assertNotIn("secret", self.out(r))
        self.assertNotIn("%3F", self.out(r))

    def test_multiline_msg_not_in_output(self):
        r = _make_record(msg="line1\n192.0.2.1\nline3")
        out = self.out(r)
        self.assertNotIn("line1", out)
        self.assertNotIn("192.0.2.1", out)
        self.assertNotIn("\n", out)

    def test_logger_name_injection_not_in_output(self):
        r = _make_record(name="ERROR\x1b[31mINJECTED")
        out = self.out(r)
        self.assertNotIn("INJECTED", out)
        self.assertNotIn("\x1b", out)

    def test_levelname_injection_ignored(self):
        r = _make_record()
        r.levelname = "SUPERCRITICAL"
        out = self.out(r)
        self.assertNotIn("SUPERCRITICAL", out)
        parsed = json.loads(out)
        self.assertEqual(parsed["level"], "INFO")

    def test_lineno_not_in_output(self):
        r = _make_record()
        r.lineno = 31337
        self.assertNotIn("31337", self.out(r))

    def test_exception_text_not_in_output(self):
        try:
            raise ValueError("secret error detail 203.0.113.5")
        except ValueError:
            ei = sys.exc_info()
        r = _make_record(msg="fail", exc_info=ei)
        out = self.out(r)
        self.assertNotIn("secret error detail", out)
        self.assertNotIn("203.0.113.5", out)
        self.assertNotIn("Traceback", out)

    def test_clientip_attr_not_in_output(self):
        r = _make_record()
        r.clientip = "198.51.100.7"
        self.assertNotIn("198.51.100.7", self.out(r))

    def test_yamlfile_attr_not_in_output(self):
        r = _make_record()
        r.yamlfile = "/interviews/private_form.yml"
        self.assertNotIn("private_form", self.out(r))

    def test_session_attr_not_in_output(self):
        r = _make_record()
        r.session = "sess_abc123secret"
        self.assertNotIn("sess_abc123secret", self.out(r))

    def test_user_attr_not_in_output(self):
        r = _make_record()
        r.user = "filer_jane_doe"
        self.assertNotIn("filer_jane_doe", self.out(r))

    def test_pathname_not_in_output(self):
        r = _make_record(pathname="/srv/app/secret_module.py")
        self.assertNotIn("secret_module", self.out(r))


class TestHostileStringConversion(unittest.TestCase):
    """Formatter must never call __str__, __repr__, or __eq__ on msg."""

    def setUp(self):
        self.fmt = PrivacyFormatter()

    def test_hostile_str_not_called(self):
        class HostileStr:
            called = False
            def __str__(self):
                HostileStr.called = True
                return "192.0.2.1 leaked via __str__"
        r = _make_record(msg=HostileStr())
        self.fmt.format(r)
        self.assertFalse(HostileStr.called)

    def test_hostile_repr_not_called(self):
        class HostileRepr:
            called = False
            def __repr__(self):
                HostileRepr.called = True
                return "192.0.2.1 leaked via __repr__"
        r = _make_record(msg=HostileRepr())
        self.fmt.format(r)
        self.assertFalse(HostileRepr.called)

    def test_hostile_eq_not_called(self):
        class HostileEq:
            called = False
            def __eq__(self, other):
                HostileEq.called = True
                return True
        r = _make_record(msg=HostileEq())
        self.fmt.format(r)
        self.assertFalse(HostileEq.called)

    def test_hostile_str_in_args_not_called(self):
        class HostileArg:
            called = False
            def __str__(self):
                HostileArg.called = True
                return "leaked"
        r = _make_record(msg="msg %s", args=(HostileArg(),))
        self.fmt.format(r)
        self.assertFalse(HostileArg.called)


class TestInvalidTimestampTypes(unittest.TestCase):

    def setUp(self):
        self.fmt = PrivacyFormatter()

    def _ts_out(self, created):
        r = _make_record()
        r.created = created
        return json.loads(self.fmt.format(r))["ts"]

    def test_string_timestamp_rejected(self):
        self.assertEqual(self._ts_out("2026-01-01"), "1970-01-01T00:00:00Z")

    def test_none_timestamp_rejected(self):
        self.assertEqual(self._ts_out(None), "1970-01-01T00:00:00Z")

    def test_nan_timestamp_rejected(self):
        self.assertEqual(self._ts_out(float("nan")), "1970-01-01T00:00:00Z")

    def test_inf_timestamp_rejected(self):
        self.assertEqual(self._ts_out(float("inf")), "1970-01-01T00:00:00Z")

    def test_negative_inf_timestamp_rejected(self):
        self.assertEqual(self._ts_out(float("-inf")), "1970-01-01T00:00:00Z")

    def test_future_out_of_range_rejected(self):
        self.assertEqual(self._ts_out(99999999999.0), "1970-01-01T00:00:00Z")

    def test_negative_timestamp_rejected(self):
        self.assertEqual(self._ts_out(-1.0), "1970-01-01T00:00:00Z")

    def test_valid_float_accepted(self):
        self.assertIn("2024", self._ts_out(1725500000.0))

    def test_valid_int_accepted(self):
        self.assertIn("2024", self._ts_out(1725500000))

    def test_bool_timestamp_rejected(self):
        self.assertEqual(self._ts_out(True), "1970-01-01T00:00:00Z")

    def test_list_timestamp_rejected(self):
        self.assertEqual(self._ts_out([1, 2]), "1970-01-01T00:00:00Z")


class TestInvalidLevelTypes(unittest.TestCase):

    def setUp(self):
        self.fmt = PrivacyFormatter()

    def _level_out(self, levelno):
        r = _make_record()
        r.levelno = levelno
        return json.loads(self.fmt.format(r))["level"]

    def test_string_level_rejected(self):
        self.assertEqual(self._level_out("INFO"), "UNKNOWN")

    def test_bool_level_rejected(self):
        self.assertEqual(self._level_out(True), "UNKNOWN")

    def test_float_level_rejected(self):
        self.assertEqual(self._level_out(20.0), "UNKNOWN")

    def test_none_level_rejected(self):
        self.assertEqual(self._level_out(None), "UNKNOWN")

    def test_unknown_int_level(self):
        self.assertEqual(self._level_out(999), "UNKNOWN")

    def test_valid_int_levels_accepted(self):
        for lvl_int, expected in [
            (logging.DEBUG, "DEBUG"),
            (logging.INFO, "INFO"),
            (logging.WARNING, "WARNING"),
            (logging.ERROR, "ERROR"),
            (logging.CRITICAL, "CRITICAL"),
        ]:
            self.assertEqual(self._level_out(lvl_int), expected)


class TestUnknownEventCodes(unittest.TestCase):

    def setUp(self):
        self.fmt = PrivacyFormatter()

    def _event_out(self, event_code):
        r = _make_record()
        if event_code is not None:
            r.event_code = event_code
        return json.loads(self.fmt.format(r))["event"]

    def test_missing_event_code(self):
        self.assertEqual(self._event_out(None), EVENT_UNKNOWN)

    def test_unknown_string_event(self):
        self.assertEqual(self._event_out("DROP_TABLE"), EVENT_UNKNOWN)

    def test_empty_string_event(self):
        self.assertEqual(self._event_out(""), EVENT_UNKNOWN)

    def test_int_event_rejected(self):
        self.assertEqual(self._event_out(42), EVENT_UNKNOWN)

    def test_bool_event_rejected(self):
        self.assertEqual(self._event_out(True), EVENT_UNKNOWN)

    def test_str_subclass_event_rejected(self):
        class EvilStr(str):
            pass
        self.assertEqual(self._event_out(EvilStr("FORM_START")), EVENT_UNKNOWN)


class TestSafeEventCodeAcceptance(unittest.TestCase):

    def setUp(self):
        self.fmt = PrivacyFormatter()

    def test_all_safe_event_codes_accepted(self):
        for code in SAFE_EVENT_CODES:
            r = _make_record()
            r.event_code = code
            parsed = json.loads(self.fmt.format(r))
            self.assertEqual(parsed["event"], code)


class TestOutputStructure(unittest.TestCase):

    def setUp(self):
        self.fmt = PrivacyFormatter()

    def test_output_is_valid_json(self):
        r = _make_record()
        parsed = json.loads(self.fmt.format(r))
        self.assertIsInstance(parsed, dict)

    def test_output_has_exactly_five_keys(self):
        r = _make_record()
        parsed = json.loads(self.fmt.format(r))
        self.assertEqual(
            set(parsed.keys()), {"ts", "level", "svc", "comp", "event"}
        )

    def test_fixed_service_and_component(self):
        r1 = _make_record(name="completely.different.logger")
        r2 = _make_record(name="192.0.2.1.evil.logger", msg="10.0.0.1")
        for r in (r1, r2):
            parsed = json.loads(self.fmt.format(r))
            self.assertEqual(parsed["svc"], SVC)
            self.assertEqual(parsed["comp"], COMP)

    def test_fallback_is_valid_json(self):
        parsed = json.loads(_FALLBACK)
        self.assertEqual(
            set(parsed.keys()), {"ts", "level", "svc", "comp", "event"}
        )

    def test_non_logrecord_returns_fallback(self):
        self.assertEqual(self.fmt.format("not a record"), _FALLBACK)
        self.assertEqual(self.fmt.format(None), _FALLBACK)
        self.assertEqual(self.fmt.format(42), _FALLBACK)

    def test_safe_format_record_helper(self):
        r = _make_record()
        r.event_code = "FORM_SUBMIT"
        parsed = json.loads(safe_format_record(r))
        self.assertEqual(parsed["event"], "FORM_SUBMIT")

    def test_safe_format_record_non_record(self):
        self.assertEqual(safe_format_record(None), _FALLBACK)
        self.assertEqual(safe_format_record("string"), _FALLBACK)


if __name__ == "__main__":
    unittest.main()
