"""Primary-review regressions, using synthetic bytes only."""
import random
import sys
import tracemalloc
import unittest

from native_support import LogAggregator


class ReviewedContractTests(unittest.TestCase):
    def test_unterminated_overflow_counted_once_and_eof_recovers(self):
        aggregator = LogAggregator("nginx")
        for stream in ("stdout", "stderr"):
            aggregator.feed(stream, b"x" * 4097)
            aggregator.feed(stream, b"more" * 4097)
            aggregator.finish(stream)
            aggregator.finish(stream)
            aggregator.feed(stream, b"PRIVACY_REQUEST status=200 msecs=0\n")
        snapshot = aggregator.snapshot()
        self.assertEqual(snapshot["dropped"], 2)
        self.assertEqual(snapshot["status_2xx"], 2)

    def test_arbitrary_fragmentation_preserves_counts(self):
        payload = (
            b"ordinary synthetic message\r\n"
            + b"x" * 4097 + b"\n"
            b"PRIVACY_REQUEST status=200 msecs=99\n"
            b"PRIVACY_REQUEST status=503 msecs=30000\n"
            b"PRIVACY_REQUEST status=200 msecs=01\n"
            b"\xff\n"
            b"PRIVACY_REQUEST status=404 msecs=1000"
        )
        for seed in range(20):
            rng = random.Random(seed)
            aggregator = LogAggregator("uwsgi")
            position = 0
            while position < len(payload):
                count = rng.randint(1, 3000)
                aggregator.feed("stdout", payload[position:position + count])
                position += count
            aggregator.finish("stdout")
            snapshot = aggregator.snapshot()
            for key, value in {
                "unclassified": 1, "dropped": 1, "rejected": 2,
                "status_2xx": 1, "status_4xx": 1, "status_5xx": 1,
                "latency_fast": 1, "latency_slow": 1, "latency_timeout": 1,
            }.items():
                self.assertEqual(snapshot[key], value, (seed, key))

    def test_large_input_does_not_allocate_a_proportional_copy(self):
        payload = b"SYNTHETIC_PRIVATE_MESSAGE" * 350000
        aggregator = LogAggregator("nginx")
        tracemalloc.start()
        try:
            aggregator.feed("stdout", payload)
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 256 * 1024)
        self.assertEqual(aggregator.snapshot()["dropped"], 1)

    def test_large_numeric_field_rejected_before_integer_conversion(self):
        previous = sys.get_int_max_str_digits()
        try:
            sys.set_int_max_str_digits(640)
            aggregator = LogAggregator("uwsgi")
            aggregator.feed("stdout", b"PRIVACY_REQUEST status=200 msecs=" + b"9" * 1000 + b"\n")
        finally:
            sys.set_int_max_str_digits(previous)
        self.assertEqual(aggregator.snapshot()["rejected"], 1)
        self.assertEqual(aggregator.snapshot()["status_2xx"], 0)
