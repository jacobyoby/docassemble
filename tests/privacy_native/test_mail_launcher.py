import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import test_native_launchers as native


class MailLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        native.NativeLauncherTests.setUpClass()

    def fixture(self, directory, failure=None):
        root = native.NativeLauncherTests().fixture(directory, activation_failure=failure == 'activation')
        (root / 'runtime/bin/activate').write_text(
            'printf "SYNTHETIC_PRIVATE_BOOTSTRAP\\n" >&2\n'
            + ('return 1\n' if failure == 'activation' else 'true\n'))
        (root / 'runtime/bin/python').write_text('#!' + sys.executable + '\n'
            'import sys\nprint("SYNTHETIC_PRIVATE_MESSAGE")\nraise SystemExit(17)\n')
        if failure == 'missing':
            (root / 'webapp/privacy-diagnostic').unlink()
        if failure == 'launch':
            (root / 'webapp/privacy-process').unlink()
        return root

    def invoke(self, root):
        env = dict(os.environ, DA_ROOT=str(root), DA_PYTHON=str(root / 'runtime'))
        env['PATH'] = str(root / 'runtime/bin') + os.pathsep + os.environ['PATH']
        process = subprocess.Popen(['bash', str(native.ROOT / 'Docker/process-email.sh')],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        out, err = process.communicate(b'SYNTHETIC_PRIVATE_MESSAGE', timeout=5)
        return process, out, err

    def test_successful_handoff_keeps_identity_and_stream_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            process, out, err = self.invoke(root)
            self.assertEqual(process.returncode, 0)
            self.assertEqual(err, b'')
            record = json.loads(out)
            self.assertEqual(record['pid'], process.pid)
            self.assertTrue(record['extra_sink_closed'])
            self.assertEqual(record['argv'], ['--component', 'mail', '--', str(root / 'runtime/bin/python'),
                                              '-m', 'docassemble.webapp.process_email', '/dev/stdin'])

    def test_failed_bootstrap_and_exec_defer_delivery(self):
        for failure in ('activation', 'missing', 'launch'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = self.fixture(directory, failure)
                process, out, err = self.invoke(root)
                self.assertEqual(process.returncode, 75)
                self.assertEqual(err, b'')
                if failure == 'missing':
                    self.assertEqual(out, b'')
                else:
                    self.assertEqual(json.loads(out), {'schema': 1, 'component': 'mail',
                        'event': 'startup_failed', 'phase': failure})
