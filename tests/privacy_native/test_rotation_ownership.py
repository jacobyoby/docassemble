"""Local counter streams must have one writer/rotator and preserve forwarding."""
import configparser
import fnmatch
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
FORWARDED = {'celery': 'worker.log', 'celerysingle': 'single_worker.log',
             'uwsgi': 'uwsgi.log', 'websockets': 'websockets.log'}


def supervisor():
    config = configparser.ConfigParser(interpolation=None)
    config.read(ROOT / 'Docker/docassemble-supervisor.conf')
    return config


class RotationOwnershipTests(unittest.TestCase):
    def test_counter_files_have_no_external_writer_or_rotator(self):
        config = supervisor()
        paths = [config['program:' + name]['stdout_logfile']
                 for name in (*FORWARDED, 'uwsgilog', 'nginx')]
        paths.append(config['eventlistener:privacy-monitor']['stderr_logfile'])
        self.assertEqual(len(paths), len(set(paths)))
        collector = (ROOT / 'Docker/syslog-ng.conf').read_text()
        collector_paths = re.findall(r'file\("([^"]+)"', collector)
        patterns = []
        for name in ('docassemble', 'nginx', 'apache'):
            patterns.extend(re.findall(r'^(/\S+)', (ROOT / 'Docker' / (name + '.logrotate')).read_text(), re.M))
        for path in paths:
            with self.subTest(path=path):
                self.assertNotIn(path, collector_paths)
                self.assertFalse(any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns))

    def test_forwarding_tracks_capture_files_and_preserves_collector_labels(self):
        source = (ROOT / 'Docker/docassemble-syslog-ng.conf').read_text()
        collector = (ROOT / 'Docker/syslog-ng.conf').read_text()
        rotation = (ROOT / 'Docker/docassemble.logrotate').read_text()
        config = supervisor()
        for component, legacy in FORWARDED.items():
            with self.subTest(component=component):
                path = config['program:' + component]['stdout_logfile']
                self.assertEqual(Path(path).name, 'privacy-' + component + '.log')
                self.assertRegex(source, r'file\("' + re.escape(path) + r'"[^\n]+program-override\("' + component + r'"\)')
                self.assertIn('file("/usr/share/docassemble/log/' + legacy + '"', collector)
                self.assertIn('/usr/share/docassemble/log/' + legacy + '\n', rotation)

    def test_forwarded_counter_files_are_precreated_before_ownership_pass(self):
        text = (ROOT / 'Docker/initialize.sh').read_text()
        start = text.index('touch /usr/share/docassemble/log/')
        end = text.index('chown -R www-data:www-data /usr/share/docassemble/log', start)
        precreation = text[start:end]
        for component in FORWARDED:
            self.assertIn(supervisor()['program:' + component]['stdout_logfile'], precreation)

    def test_supervisor_keeps_bounded_rotation(self):
        config = supervisor()
        for name in (*FORWARDED, 'uwsgilog', 'nginx'):
            with self.subTest(component=name):
                section = config['program:' + name]
                self.assertEqual(section['stdout_logfile_maxbytes'], '5MB')
                self.assertEqual(section['stdout_logfile_backups'], '7')
                self.assertEqual(section['redirect_stderr'], 'true')
        monitor = config['eventlistener:privacy-monitor']
        self.assertEqual(monitor['stderr_logfile_maxbytes'], '5MB')
        self.assertEqual(monitor['stderr_logfile_backups'], '7')

    def test_celery_receiver_does_not_duplicate_single_queue_records(self):
        text = (ROOT / 'Docker/syslog-ng.conf').read_text()
        expression = re.search(r'filter f_daworker \{ program\("([^"]+)"\); \};', text).group(1)
        self.assertIsNotNone(re.search(expression, 'celery'))
        self.assertIsNone(re.search(expression, 'celerysingle'))
        self.assertIsNone(re.search(expression, 'other-celery'))


if __name__ == '__main__':
    unittest.main()
