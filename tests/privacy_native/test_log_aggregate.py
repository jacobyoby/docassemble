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


class TestBasicValidLines(unittest.TestCase):

    def test_single_200_fast(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout", b"PRIVACY_REQUEST status=200 msecs=50\n")
        s = agg.snapshot()
        self.assertEqual(s["status_2xx"], 1)
        self.assertEqual(s["latency_fast"], 1)

    def test_multiple_lines(self):
        agg = LogAggregator("uwsgi")
        agg.feed("stdout",
            b"PRIVACY_REQUEST status=200 msecs=50\n"
            b"PRIVACY_REQUEST status=404 msecs=500\n"
            b"PRIVACY_REQUEST status=500 msecs=5000\n")
        s = agg.snapshot()
        self.assertEqual(s["status_2xx"], 1)
        self.assertEqual(s["status_4xx"], 1)
        self.assertEqual(s["status_5xx"], 1)
        self.assertEqual(s["latency_fast"], 1)
        self.assertEqual(s["latency_medium"], 1)
        self.assertEqual(s["latency_slow"], 1)

    def test_component_in_snapshot(self):
        agg = LogAggregator("nginx")
        self.assertEqual(agg.snapshot()["component"], "nginx")
        agg2 = LogAggregator("uwsgi")
        self.assertEqual(agg2.snapshot()["component"], "uwsgi")


class TestFragmentedLines(unittest.TestCase):

    def test_line_split_across_two_chunks(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout", b"PRIVACY_REQUEST status=200 ")
        self.assertEqual(agg.snapshot()["status_2xx"], 0)
        agg.feed("stdout", b"msecs=50\n")
        s = agg.snapshot()
        self.assertEqual(s["status_2xx"], 1)
        self.assertEqual(s["latency_fast"], 1)

    def test_line_split_byte_by_byte(self):
        agg = LogAggregator("nginx")
        line = b"PRIVACY_REQUEST status=301 msecs=99\n"
        for byte in line:
            agg.feed("stdout", bytes([byte]))
        s = agg.snapshot()
        self.assertEqual(s["status_3xx"], 1)
        self.assertEqual(s["latency_fast"], 1)

    def test_multiple_lines_in_one_chunk(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout",
            b"PRIVACY_REQUEST status=200 msecs=10\n"
            b"PRIVACY_REQUEST status=200 msecs=20\n")
        self.assertEqual(agg.snapshot()["status_2xx"], 2)


class TestInterleavedStreams(unittest.TestCase):

    def test_stdout_stderr_independent_buffers(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout", b"PRIVACY_REQUEST status=200 ")
        agg.feed("stderr", b"PRIVACY_REQUEST status=500 ")
        s = agg.snapshot()
        self.assertEqual(s["status_2xx"], 0)
        self.assertEqual(s["status_5xx"], 0)

        agg.feed("stdout", b"msecs=10\n")
        s = agg.snapshot()
        self.assertEqual(s["status_2xx"], 1)
        self.assertEqual(s["status_5xx"], 0)

        agg.feed("stderr", b"msecs=999\n")
        s = agg.snapshot()
        self.assertEqual(s["status_2xx"], 1)
        self.assertEqual(s["status_5xx"], 1)

    def test_stderr_only(self):
        agg = LogAggregator("uwsgi")
        agg.feed("stderr", b"PRIVACY_REQUEST status=200 msecs=50\n")
        self.assertEqual(agg.snapshot()["status_2xx"], 1)


class TestBinaryAndInvalidInput(unittest.TestCase):

    def test_invalid_utf8_rejected(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout", b"\xff\xfe\xfd\n")
        s = agg.snapshot()
        self.assertEqual(s["rejected"], 1)

    def test_nul_byte_rejected(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout", b"PRIVACY_REQUEST\x00 status=200 msecs=50\n")
        self.assertEqual(agg.snapshot()["rejected"], 1)

    def test_crlf_normalized_trailing_cr_stripped(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout",
            b"PRIVACY_REQUEST status=200 msecs=50\r\n")
        s = agg.snapshot()
        self.assertEqual(s["status_2xx"], 1)
        self.assertEqual(s["rejected"], 0)

    def test_embedded_cr_rejected(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout",
            b"PRIVACY_REQUEST status=200\r msecs=50\n")
        self.assertEqual(agg.snapshot()["rejected"], 1)

    def test_all_zero_bytes_rejected(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout", b"\x00\x00\x00\n")
        self.assertEqual(agg.snapshot()["rejected"], 1)

    def test_mixed_valid_and_invalid(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout",
            b"PRIVACY_REQUEST status=200 msecs=50\n"
            b"\xff\xfe\n"
            b"PRIVACY_REQUEST status=404 msecs=100\n")
        s = agg.snapshot()
        self.assertEqual(s["status_2xx"], 1)
        self.assertEqual(s["status_4xx"], 1)
        self.assertEqual(s["rejected"], 1)


class TestOversizedLines(unittest.TestCase):

    def test_oversized_single_chunk_dropped(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout", b"X" * (_MAX_LINE + 1) + b"\n")
        s = agg.snapshot()
        self.assertEqual(s["dropped"], 1)
        self.assertEqual(s["rejected"], 0)

    def test_oversized_delimited_no_dropping_state(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout",
            b"X" * (_MAX_LINE + 1) + b"\n"
            b"PRIVACY_REQUEST status=200 msecs=50\n")
        s = agg.snapshot()
        self.assertEqual(s["dropped"], 1)
        self.assertEqual(s["status_2xx"], 1)
        self.assertFalse(agg._dropping["stdout"])

    def test_oversized_split_across_chunks(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout", b"X" * (_MAX_LINE + 10))
        self.assertEqual(agg.snapshot()["dropped"], 1)
        agg.feed("stdout", b"more_garbage\n")
        s = agg.snapshot()
        self.assertEqual(s["dropped"], 1)

    def test_recovery_after_drop(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout", b"X" * (_MAX_LINE + 1) + b"\n")
        agg.feed("stdout", b"PRIVACY_REQUEST status=200 msecs=50\n")
        s = agg.snapshot()
        self.assertEqual(s["dropped"], 1)
        self.assertEqual(s["status_2xx"], 1)

    def test_multiple_oversized_in_one_chunk(self):
        agg = LogAggregator("nginx")
        chunk = (
            b"X" * (_MAX_LINE + 1) + b"\n"
            + b"Y" * (_MAX_LINE + 1) + b"\n"
            + b"PRIVACY_REQUEST status=200 msecs=10\n"
        )
        agg.feed("stdout", chunk)
        s = agg.snapshot()
        self.assertEqual(s["dropped"], 2)
        self.assertEqual(s["status_2xx"], 1)

    def test_exactly_max_line_accepted(self):
        agg = LogAggregator("nginx")
        line = b"X" * _MAX_LINE + b"\n"
        self.assertEqual(len(line) - 1, _MAX_LINE)
        agg.feed("stdout", line)
        s = agg.snapshot()
        self.assertEqual(s["unclassified"], 1)
        self.assertEqual(s["status_2xx"], 0)
        self.assertEqual(s["dropped"], 0)


class TestHugeChunkMemoryBound(unittest.TestCase):

    def test_1mib_chunk_no_newline_bounded(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout", b"x" * 1048576)
        self.assertLessEqual(len(agg._buf["stdout"]), _MAX_LINE)
        self.assertEqual(agg.snapshot()["dropped"], 1)

    def test_1mib_chunk_then_valid_line(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout", b"x" * 1048576 + b"\n")
        agg.feed("stdout", b"PRIVACY_REQUEST status=200 msecs=50\n")
        s = agg.snapshot()
        self.assertEqual(s["dropped"], 1)
        self.assertEqual(s["status_2xx"], 1)
        self.assertLessEqual(len(agg._buf["stdout"]), _MAX_LINE)

    def test_many_small_chunks_no_newline_bounded(self):
        agg = LogAggregator("nginx")
        for _ in range(10000):
            agg.feed("stdout", b"x")
        self.assertLessEqual(len(agg._buf["stdout"]), _MAX_LINE)


class TestUnterminatedFinish(unittest.TestCase):

    def test_finish_processes_tail(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout", b"PRIVACY_REQUEST status=200 msecs=50")
        self.assertEqual(agg.snapshot()["status_2xx"], 0)
        agg.finish("stdout")
        self.assertEqual(agg.snapshot()["status_2xx"], 1)

    def test_finish_empty_buffer_resets_drop(self):
        agg = LogAggregator("nginx")
        agg._dropping["stdout"] = True
        agg.finish("stdout")
        self.assertFalse(agg._dropping["stdout"])
        self.assertEqual(agg.snapshot()["dropped"], 0)

    def test_finish_empty_buffer_no_drop_noop(self):
        agg = LogAggregator("nginx")
        agg.finish("stdout")
        s = agg.snapshot()
        for k, v in s.items():
            if k in ("schema", "component"):
                continue
            self.assertEqual(v, 0)

    def test_finish_oversized_tail_dropped(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout", b"X" * (_MAX_LINE + 1))
        agg.finish("stdout")
        self.assertEqual(agg.snapshot()["dropped"], 1)


class TestStrictInt(unittest.TestCase):

    def test_plus_sign_rejected(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout",
            b"PRIVACY_REQUEST status=+200 msecs=50\n")
        self.assertEqual(agg.snapshot()["rejected"], 1)
        self.assertEqual(agg.snapshot()["status_2xx"], 0)

    def test_underscore_rejected(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout",
            b"PRIVACY_REQUEST status=200 msecs=1_0\n")
        self.assertEqual(agg.snapshot()["rejected"], 1)

    def test_hex_prefix_rejected(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout",
            b"PRIVACY_REQUEST status=0x200 msecs=50\n")
        self.assertEqual(agg.snapshot()["rejected"], 1)

    def test_leading_zero_rejected(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout",
            b"PRIVACY_REQUEST status=200 msecs=050\n")
        self.assertEqual(agg.snapshot()["rejected"], 1)
        self.assertEqual(agg.snapshot()["status_2xx"], 0)

    def test_empty_status_rejected(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout",
            b"PRIVACY_REQUEST status= msecs=50\n")
        self.assertEqual(agg.snapshot()["rejected"], 1)

    def test_empty_msecs_rejected(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout",
            b"PRIVACY_REQUEST status=200 msecs=\n")
        self.assertEqual(agg.snapshot()["rejected"], 1)

    def test_prefix_runon_rejected(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout",
            b"PRIVACY_REQUESTX status=200 msecs=1\n")
        s = agg.snapshot()
        self.assertEqual(s["rejected"], 0)
        self.assertEqual(s["unclassified"], 1)

    def test_fullwidth_unicode_digits_rejected(self):
        agg = LogAggregator("nginx")
        line = "PRIVACY_REQUEST status=\uff12\uff10\uff10 msecs=50\n"
        agg.feed("stdout", line.encode("utf-8"))
        s = agg.snapshot()
        self.assertEqual(s["rejected"], 1)
        self.assertEqual(s["status_2xx"], 0)

    def test_status_leading_zeros_rejected(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout",
            b"PRIVACY_REQUEST status=0200 msecs=50\n")
        s = agg.snapshot()
        self.assertEqual(s["rejected"], 1)
        self.assertEqual(s["status_2xx"], 0)

    def test_msecs_leading_zeros_rejected(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout",
            b"PRIVACY_REQUEST status=200 msecs=01\n")
        s = agg.snapshot()
        self.assertEqual(s["rejected"], 1)
        self.assertEqual(s["latency_fast"], 0)


class TestUnclassifiedVsRejected(unittest.TestCase):

    def test_ordinary_log_line_unclassified(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout", b"2026-01-01 INFO starting up\n")
        s = agg.snapshot()
        self.assertEqual(s["unclassified"], 1)
        self.assertEqual(s["rejected"], 0)

    def test_wrong_prefix_unclassified(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout",
            b"ACCESS_REQUEST status=200 msecs=50\n")
        s = agg.snapshot()
        self.assertEqual(s["unclassified"], 1)
        self.assertEqual(s["rejected"], 0)

    def test_malformed_privacy_request_rejected(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout",
            b"PRIVACY_REQUEST status=abc msecs=50\n")
        s = agg.snapshot()
        self.assertEqual(s["rejected"], 1)
        self.assertEqual(s["unclassified"], 0)

    def test_extra_fields_rejected(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout",
            b"PRIVACY_REQUEST status=200 msecs=50 extra=1\n")
        self.assertEqual(agg.snapshot()["rejected"], 1)

    def test_missing_msecs_rejected(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout", b"PRIVACY_REQUEST status=200\n")
        self.assertEqual(agg.snapshot()["rejected"], 1)

    def test_empty_line_unclassified(self):
        agg = LogAggregator("nginx")
        agg.feed("stdout", b"\n")
        s = agg.snapshot()
        self.assertEqual(s["unclassified"], 1)
        self.assertEqual(s["rejected"], 0)


class TestStatusBoundaries(unittest.TestCase):

    def _feed_status(self, status):
        agg = LogAggregator("nginx")
        line = ("PRIVACY_REQUEST status=%d msecs=50\n" % status).encode()
        agg.feed("stdout", line)
        return agg.snapshot()

    def test_status_99_rejected(self):
        self.assertEqual(self._feed_status(99)["rejected"], 1)

    def test_status_100_counted(self):
        self.assertEqual(self._feed_status(100)["status_1xx"], 1)

    def test_status_199_counted(self):
        self.assertEqual(self._feed_status(199)["status_1xx"], 1)

    def test_status_200_counted(self):
        self.assertEqual(self._feed_status(200)["status_2xx"], 1)

    def test_status_599_counted(self):
        self.assertEqual(self._feed_status(599)["status_5xx"], 1)

    def test_status_600_rejected(self):
        self.assertEqual(self._feed_status(600)["rejected"], 1)

    def test_status_0_rejected(self):
        self.assertEqual(self._feed_status(0)["rejected"], 1)
