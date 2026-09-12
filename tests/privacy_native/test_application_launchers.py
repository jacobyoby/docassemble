"""Real shell handoffs and compiled diagnostics, with synthetic bootstrap/native tools."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import test_native_launchers as native

PRIVATE, ROOT = native.PRIVATE, native.ROOT

PROFILES = (('run-celery.sh', 'celery'), ('run-celery-single.sh', 'celerysingle'),
            ('run-websockets.sh', 'websockets'))


class ApplicationLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        native.NativeLauncherTests.setUpClass()

    def fixture(self, directory, failure=None):
        root = native.NativeLauncherTests().fixture(directory, activation_failure=failure == 'activation')
        interpreter = root / 'runtime/bin/python'
        interpreter.write_text('#!' + sys.executable + '\n' + r'''import os, sys
print('SYNTHETIC_PRIVATE_BOOTSTRAP', file=sys.stderr)
if sys.argv[1] == '-m':
    print('export LOCALE="' if os.environ.get('SYNTHETIC_CONFIG_EVAL_FAIL') else 'export LOCALE="C.UTF-8 UTF-8"')
    print('DAMAXCELERYWORKERS=4')
    print('DACELERYWORKERS=' + os.environ.get('SYNTHETIC_WORKERS', '3'))
    if os.environ.get('SYNTHETIC_LAUNCH_FAIL'):
        os.unlink(os.environ['DA_ROOT'] + '/webapp/privacy-process')
    raise SystemExit(1 if os.environ.get('SYNTHETIC_CONFIG_FAIL') else 0)
print('SYNTHETIC_PRIVATE_NATIVE')
raise SystemExit(17)
''')
        for name, text in {'nproc': '#!/bin/sh\nprintf "8\\n"\n',
                           'celery': '#!/bin/sh\nprintf "SYNTHETIC_PRIVATE_NATIVE\\n"\nexit 17\n'}.items():
            executable = root / 'runtime/bin' / name
            executable.write_text(text)
            executable.chmod(0o755)
        return root

    def invoke(self, script, root, **extra):
        env = dict(os.environ, DA_ROOT=str(root), DA_PYTHON=str(root / 'runtime'), **extra)
        env['PATH'] = str(root / 'runtime/bin') + os.pathsep + os.environ['PATH']
        child = subprocess.Popen(['bash', str(ROOT / 'Docker' / script)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        stdout, stderr = child.communicate(timeout=5)
        return child, stdout, stderr

    def test_every_application_uses_protected_foreground_capture(self):
        for script, component in PROFILES:
            with self.subTest(script=script), tempfile.TemporaryDirectory() as directory:
                root = self.fixture(directory)
                child, stdout, stderr = self.invoke(script, root)
                self.assertNotIn(PRIVATE.encode(), stdout + stderr)
                self.assertNotIn(b'SYNTHETIC_PRIVATE_NATIVE', stdout + stderr)
                self.assertEqual(child.returncode, 0)
                self.assertEqual(stderr, b'')
                record = json.loads(stdout)
                self.assertEqual(record['pid'], child.pid)
                self.assertTrue(record['extra_sink_closed'])
                self.assertEqual(record['argv'][:3], ['--component', component, '--'])
                if component == 'websockets':
                    self.assertEqual(record['argv'][3:], [str(root / 'runtime/bin/python'), '-u', '-m', 'docassemble.webapp.socketserver'])
                else:
                    args = record['argv'][3:]
                    self.assertEqual(args[0], str(root / 'runtime/bin/celery'))
                    self.assertEqual(args[1:5], ['-A', 'docassemble.webapp.worker', 'worker', '--loglevel=INFO'])
                    self.assertIn('--concurrency=' + ('2' if component == 'celery' else '1'), args)
                    self.assertEqual(args[args.index('-Q') + 1], 'celery' if component == 'celery' else 'single')

    def test_bootstrap_and_exec_failures_are_fixed_and_bounded(self):
        for script, component in PROFILES:
            for failure in ('activation', 'config', 'config_eval', 'launch'):
                with self.subTest(script=script, failure=failure), tempfile.TemporaryDirectory() as directory:
                    root = self.fixture(directory, failure)
                    extra = {} if failure == 'activation' else {'SYNTHETIC_' + failure.upper() + '_FAIL': '1'}
                    child, stdout, stderr = self.invoke(script, root, **extra)
                    self.assertEqual(child.returncode, 70)
                    self.assertEqual(stderr, b'')
                    self.assertEqual(json.loads(stdout), {'schema': 1, 'component': component,
                                                         'event': 'startup_failed', 'phase': failure})

    def test_missing_diagnostic_stops_before_activation(self):
        for script, component in PROFILES:
            with self.subTest(script=script), tempfile.TemporaryDirectory() as directory:
                root = self.fixture(directory)
                (root / 'webapp/privacy-diagnostic').unlink()
                child, stdout, stderr = self.invoke(script, root)
                self.assertEqual(child.returncode, 69)
                self.assertEqual(stdout + stderr, b'')

    def test_worker_count_cannot_be_shell_arithmetic(self):
        for value in ('1+2', '-1', '0', '99999999999999999999', 'name[0]'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                root = self.fixture(directory)
                child, stdout, stderr = self.invoke('run-celery.sh', root, SYNTHETIC_WORKERS=value)
                self.assertEqual(child.returncode, 70)
                self.assertEqual(stderr, b'')
                self.assertEqual(json.loads(stdout)['phase'], 'config_eval')
