"""Real script bootstrap must fail closed before any maintenance runs."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = [('Docker/cron/docassemble-cron-' + period + '.sh', 'maintenance')
           for period in ('hourly', 'daily', 'weekly', 'monthly')]
SCRIPTS += [('Docker/sync.sh', 'maintenance'), ('Docker/restart-post-logrotate.sh', 'maintenance'),
            ('Docker/initialize.sh', 'initialize')]


class MaintenanceLaunchers(unittest.TestCase):
    def test_missing_capture_emits_only_a_fixed_failure_before_activation(self):
        diagnostic = ROOT / 'tests/.privacy-build/privacy-diagnostic'
        self.assertTrue(diagnostic.is_file(), 'run tests/verify_privacy.sh')
        for script, component in SCRIPTS:
            with self.subTest(script=script), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                (base / 'webapp').mkdir()
                (base / 'runtime/bin').mkdir(parents=True)
                shutil.copy2(diagnostic, base / 'webapp/privacy-diagnostic')
                (base / 'runtime/bin/activate').write_text(
                    'printf JOS81_PRIVATE_MAINTENANCE >&2\ntouch "$DA_ROOT/activation-ran"\n')
                env = dict(os.environ, DA_ROOT=directory, DA_PYTHON=str(base / 'runtime'))
                result = subprocess.run(['bash', str(ROOT / script)], env=env,
                                        capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 70)
                self.assertEqual(result.stderr, b'')
                self.assertEqual(json.loads(result.stdout),
                                 dict(schema=1, component=component, event='startup_failed', phase='launch'))
                self.assertFalse((base / 'activation-ran').exists())


if __name__ == '__main__':
    unittest.main()
