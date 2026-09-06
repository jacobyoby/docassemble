import json
import tempfile
import unittest

from mail_support import run_processor


class MailProcessorTests(unittest.TestCase):
    def test_message_and_attachments_reach_expected_synthetic_interfaces(self):
        with tempfile.TemporaryDirectory() as directory:
            state = run_processor(directory)
        self.assertTrue(state.completed, repr(state.error or state.exit))
        self.assertEqual(state.config, [{'arguments': ['process_email.py', directory + '/message']}])
        self.assertFalse(any(path == '/tmp/mail.log' for path, _ in state.opens))
        self.assertFalse(any(mode != 'r' for _, mode in state.opens))
        self.assertEqual(len(state.emails), 1)
        self.assertEqual(state.emails[0]['subject'], 'SYNTHETIC_PRIVATE_SUBJECT')
        self.assertEqual(json.loads(state.emails[0]['to_addr']), [{'name': '', 'address': 'testcode@example.invalid'}])
        self.assertEqual(len(state.attachments), 3)
        self.assertEqual(state.saved[1:], [b'SYNTHETIC_PRIVATE_BODY', b'\x00\xffPDF'])
        self.assertEqual(len(state.tasks), 1)
        args, kwargs = state.tasks[0]
        self.assertEqual(args, ('tasks.background_action',))
        self.assertEqual(kwargs['args'][-1], {'action': 'incoming_email', 'arguments': {'id': 42}})

    def test_read_and_unknown_recipient_fail_without_diagnostic_file(self):
        for failure, message in (('read', 'Failed to read e-mail message'), ('unknown', 'short code not found')):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                state = run_processor(directory, failure)
                self.assertEqual(state.exit, message)
                self.assertFalse(state.completed)
                self.assertFalse(state.tasks)
                self.assertFalse(any(path == '/tmp/mail.log' for path, _ in state.opens))

    def test_database_and_broker_failures_propagate(self):
        for failure in ('database', 'broker'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                state = run_processor(directory, failure)
                self.assertIsInstance(state.error, OSError)
                self.assertFalse(state.completed)
                self.assertFalse(any(path == '/tmp/mail.log' for path, _ in state.opens))
