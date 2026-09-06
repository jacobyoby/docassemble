"""The integration check must reject retained raw data, even when valid JSON."""
import json
import unittest

from check_install_image import records


class InstallRecordChecks(unittest.TestCase):
    def setUp(self):
        self.record = dict(schema=1, component='uwsgi', status_1xx=0, status_2xx=1,
                           status_3xx=0, status_4xx=0, status_5xx=0, latency_fast=1,
                           latency_medium=0, latency_slow=0, latency_timeout=0,
                           unclassified=0, rejected=0, dropped=0)

    def test_accepts_safe_request_record(self):
        self.assertEqual(records(json.dumps(self.record), 'uwsgi'), [self.record])

    def test_rejects_raw_or_ambiguous_json(self):
        for data in ('{"message":"synthetic private content"}',
                     json.dumps(self.record | {'message': 'synthetic private content'}),
                     '{"status_2xx":"synthetic private content",' + json.dumps(self.record)[1:],
                     '[]', ''):
            with self.subTest(data=data), self.assertRaises(AssertionError):
                records(data, 'uwsgi')

    def test_rejects_wrong_identity_and_invalid_numbers(self):
        for replacement in ({'schema': 2}, {'component': 'nginx'}, {'status_2xx': True},
                            {'status_2xx': -1}, {'status_2xx': 2147483648}, {'status_2xx': 1.5}):
            with self.subTest(replacement=replacement), self.assertRaises(AssertionError):
                records(json.dumps(self.record | replacement), 'uwsgi')

    def test_rejects_request_buckets_for_application_streams(self):
        for component in ('celery', 'celerysingle', 'websockets'):
            with self.subTest(component=component), self.assertRaises(AssertionError):
                records(json.dumps(self.record | {'component': component}), component)
