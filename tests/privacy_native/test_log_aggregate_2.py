import unittest
import json

from native_support import LogAggregator, _MAX_LINE, _COUNTER_MAX, _SCHEMA_VERSION


SYNTH_IPv4 = "192.0.2.1"
SYNTH_IPv6 = "2001:db8::1"
SYNTH_FORM = "private_form.yml"
SYNTH_SESSION = "sess_abc123secret"
SYNTH_TOKENS = [SYNTH_IPv4, SYNTH_IPv6, SYNTH_FORM, SYNTH_SESSION]

EXPECTED_KEYS = {
    "schema", "component",
    "status_1xx", "status_2xx", "status_3xx",
    "status_4xx", "status_5xx",
    "latency_fast", "latency_medium",
    "latency_slow", "latency_timeout",
    "unclassified", "rejected", "dropped",
}


def _snapshot_str(agg):
    return json.dumps(agg.snapshot())


class TestLatencyBoundaries(unittest.TestCase):

    def _feed_msecs(self, msecs):
        agg = LogAggregator("nginx")
        line = ("PRIVACY_REQUEST status=200 msecs=%d\n" % msecs).encode()
        agg.feed("stdout", line)
        return agg.snapshot()

    def test_msecs_0_fast(self):
        self.assertEqual(self._feed_msecs(0)["latency_fast"], 1)

    def test_msecs_99_fast(self):
        self.assertEqual(self._feed_msecs(99)["latency_fast"], 1)

    def test_msecs_100_medium(self):
        self.assertEqual(self._feed_msecs(100)["latency_medium"], 1)

    def test_msecs_999_medium(self):
        self.assertEqual(self._feed_msecs(999)["latency_medium"], 1)

    def test_msecs_1000_slow(self):
        self.assertEqual(self._feed_msecs(1000)["latency_slow"], 1)

    def test_msecs_29999_slow(self):
        self.assertEqual(self._feed_msecs(29999)["latency_slow"], 1)

    def test_msecs_30000_timeout(self):
        self.assertEqual(self._feed_msecs(30000)["latency_timeout"], 1)

    def test_msecs_600000_timeout(self):
        self.assertEqual(self._feed_msecs(600000)["latency_timeout"], 1)

    def test_msecs_600001_rejected(self):
        self.assertEqual(self._feed_msecs(600001)["rejected"], 1)

    def test_msecs_negative_rejected(self):
        self.assertEqual(self._feed_msecs(-1)["rejected"], 1)


class TestCounterSaturation(unittest.TestCase):

    def test_counter_saturates_at_max(self):
        agg = LogAggregator("nginx")
        agg._counters["status_2xx"] = _COUNTER_MAX
        agg.feed("stdout", b"PRIVACY_REQUEST status=200 msecs=50\n")
        self.assertEqual(agg.snapshot()["status_2xx"], _COUNTER_MAX)

    def test_rejected_counter_saturates(self):
        agg = LogAggregator("nginx")
        agg._counters["rejected"] = _COUNTER_MAX
        agg.feed("stdout", b"PRIVACY_REQUEST bad\n")
        self.assertEqual(agg.snapshot()["rejected"], _COUNTER_MAX)


class TestInvalidTypes(unittest.TestCase):

    def test_chunk_string_rejected(self):
        agg = LogAggregator("nginx")
        with self.assertRaises(TypeError):
            agg.feed("stdout", "not bytes")

    def test_chunk_int_rejected(self):
        agg = LogAggregator("nginx")
        with self.assertRaises(TypeError):
            agg.feed("stdout", 42)

    def test_chunk_none_rejected(self):
        agg = LogAggregator("nginx")
        with self.assertRaises(TypeError):
            agg.feed("stdout", None)

    def test_chunk_bytearray_rejected(self):
        agg = LogAggregator("nginx")
        with self.assertRaises(TypeError):
            agg.feed("stdout", bytearray(b"data"))

    def test_bytes_subclass_rejected(self):
        class EvilBytes(bytes):
            pass
        agg = LogAggregator("nginx")
        with self.assertRaises(TypeError):
            agg.feed("stdout", EvilBytes(b"data"))

    def test_stream_int_rejected(self):
        agg = LogAggregator("nginx")
        with self.assertRaises(TypeError):
            agg.feed(123, b"data")

    def test_stream_str_subclass_rejected(self):
        class EvilStr(str):
            pass
        agg = LogAggregator("nginx")
        with self.assertRaises(TypeError):
            agg.feed(EvilStr("stdout"), b"data\n")

    def test_stream_invalid_value(self):
        agg = LogAggregator("nginx")
        with self.assertRaises(ValueError):
            agg.feed("stdin", b"data")

    def test_component_invalid(self):
        with self.assertRaises(ValueError):
            LogAggregator("apache")

    def test_component_int(self):
        with self.assertRaises(ValueError):
            LogAggregator(42)

    def test_component_str_subclass(self):
        class EvilStr(str):
            pass
        with self.assertRaises(ValueError):
            LogAggregator(EvilStr("nginx"))


class TestNoSyntheticTokensInOutput(unittest.TestCase):

    def test_no_tokens_after_ipv4_input(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout",
            ("192.0.2.1 PRIVACY_REQUEST status=200 msecs=50\n"
             ).encode())
        out = _snapshot_str(agg)
        for token in SYNTH_TOKENS:
            self.assertNotIn(token, out)

    def test_no_tokens_after_ipv6_input(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout",
            ("2001:db8::1 PRIVACY_REQUEST status=200 msecs=50\n"
             ).encode())
        out = _snapshot_str(agg)
        for token in SYNTH_TOKENS:
            self.assertNotIn(token, out)

    def test_no_tokens_after_form_input(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout",
            ("PRIVACY_REQUEST status=200 msecs=50 private_form.yml\n"
             ).encode())
        out = _snapshot_str(agg)
        for token in SYNTH_TOKENS:
            self.assertNotIn(token, out)

    def test_no_tokens_after_garbage_with_embedded_ips(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout",
            b"192.0.2.1 2001:db8::1 sess_abc123secret "
            b"private_form.yml\n")
        out = _snapshot_str(agg)
        for token in SYNTH_TOKENS:
            self.assertNotIn(token, out)

    def test_no_tokens_after_oversized_drop(self):
        agg = LogAggregator("nginx")
        garbage = SYNTH_IPv4.encode() * 500
        agg.feed("stdout", garbage + b"\n")
        out = _snapshot_str(agg)
        for token in SYNTH_TOKENS:
            self.assertNotIn(token, out)


class TestSnapshotSchema(unittest.TestCase):

    def test_snapshot_has_exact_keys(self):
        agg = LogAggregator("nginx")
        s = agg.snapshot()
        self.assertEqual(set(s.keys()), EXPECTED_KEYS)

    def test_schema_field_is_one(self):
        agg = LogAggregator("nginx")
        self.assertEqual(agg.snapshot()["schema"], _SCHEMA_VERSION)
        self.assertEqual(agg.snapshot()["schema"], 1)

    def test_all_values_are_int_except_schema_and_component(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout", b"PRIVACY_REQUEST status=200 msecs=50\n")
        s = agg.snapshot()
        self.assertIsInstance(s["schema"], int)
        self.assertIsInstance(s["component"], str)
        for k, v in s.items():
            if k == "component":
                self.assertIsInstance(v, str)
            else:
                self.assertIsInstance(v, int)

    def test_snapshot_is_copy(self):
        agg = LogAggregator("nginx")
        s1 = agg.snapshot()
        agg.feed("stdout", b"PRIVACY_REQUEST status=200 msecs=50\n")
        s2 = agg.snapshot()
        self.assertEqual(s1["status_2xx"], 0)
        self.assertEqual(s2["status_2xx"], 1)

    def test_snapshot_is_json_serializable(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout", b"PRIVACY_REQUEST status=200 msecs=50\n")
        serialized = json.dumps(agg.snapshot())
        parsed = json.loads(serialized)
        self.assertEqual(parsed["status_2xx"], 1)
        self.assertEqual(parsed["schema"], 1)
