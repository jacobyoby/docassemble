import json
import unittest
from native_support import LogAggregator


class NginxRequestCounts(unittest.TestCase):
    def test_real_nginx_decimal_seconds_have_exact_latency_buckets(self):
        cases = (("0.000", "latency_fast"), ("0.099", "latency_fast"),
                 ("0.100", "latency_medium"), ("0.999", "latency_medium"),
                 ("1.000", "latency_slow"), ("29.999", "latency_slow"),
                 ("30.000", "latency_timeout"), ("600.000", "latency_timeout"))
        for seconds, bucket in cases:
            with self.subTest(seconds=seconds):
                agg = LogAggregator("nginx")
                line = ("PRIVACY_REQUEST status=204 seconds=" + seconds + "\n").encode()
                for byte in line:
                    agg.feed("stdout", bytes([byte]))
                self.assertEqual(agg.snapshot()["status_2xx"], 1)
                self.assertEqual(agg.snapshot()[bucket], 1)
                self.assertEqual(agg.snapshot()["rejected"], 0)

    def test_malformed_decimal_or_out_of_range_is_rejected_without_markers(self):
        values = ("00.001", "+0.100", "-0.100", "0.1", "0.0000", "1e3",
                  "600.001", "999999999999.000", "0.000 SYNTHETIC_PRIVATE", "nan", "١.000")
        for value in values:
            with self.subTest(value=value):
                agg = LogAggregator("nginx")
                agg.feed("stdout", ("PRIVACY_REQUEST status=200 seconds=" + value + "\n").encode())
                self.assertEqual(agg.snapshot()["rejected"], 1)
                self.assertEqual(agg.snapshot()["status_2xx"], 0)
                self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(agg.snapshot()))

    def test_nginx_seconds_not_misread_as_uwsgi_milliseconds(self):
        agg = LogAggregator("uwsgi")
        agg.feed("stderr", b"PRIVACY_REQUEST status=200 seconds=0.010\n")
        self.assertEqual(agg.snapshot()["rejected"], 1)


if __name__ == "__main__":
    unittest.main()
