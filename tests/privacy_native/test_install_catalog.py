"""Check the documented overlay against real source paths and runtime bindings."""
import configparser
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


def catalog():
    return json.loads((ROOT / 'docs/privacy/install-catalog.json').read_text())


def target(value):
    return value.replace('{{DA_ROOT}}', '/usr/share/docassemble').replace(
        '{{SITE_PACKAGES}}', '/usr/share/docassemble/local3.14/lib/python3.14/site-packages')


class InstallCatalogTests(unittest.TestCase):
    def test_sources_exist_and_exclude_deferred_mail_and_test_material(self):
        data = catalog()
        self.assertEqual(data['scope'], 'non-mail-privacy-overlay')
        self.assertEqual((data['owner'], data['group']), ('root', 'root'))
        for item in data['files']:
            with self.subTest(item=item['id']):
                self.assertIn(item['mode'], ('0644', '0755'))
                self.assertIn(item.get('existing'), (None, 'preserve-and-validate', 'apply-privacy-diff'))
                if item['kind'] == 'binary':
                    self.assertRegex(item['source'], r'^privacy-(diagnostic|process|preflight|monitor)-linux-\{\{ARCH\}\}$')
                    continue
                self.assertEqual(item['kind'], 'source')
                path = ROOT / item['source']
                self.assertTrue(path.is_file())
                self.assertTrue(path.resolve().is_relative_to(ROOT))
                self.assertFalse(item['source'].startswith('tests/'))
                self.assertNotIn('exim', item['source'])
                self.assertNotIn(path.name, ('process-email.sh', 'process_email.py'))
                if 'patch' in item:
                    self.assertEqual(item['existing'], 'apply-privacy-diff')
                    patch = ROOT / item['patch']
                    self.assertTrue(patch.resolve().is_relative_to(ROOT / 'Docker/privacy'))
                    self.assertTrue(patch.read_text().startswith('--- a/' + item['source'] + '\n+++ b/' + item['source'] + '\n'))
                if path.suffix == '.py':
                    self.assertEqual(path.name, 'log_initialize.py')
                    self.assertTrue(all(not line.strip() or line.lstrip().startswith('#') for line in path.read_text().splitlines()))

    def test_unique_bindings_and_generated_source_references(self):
        data = catalog()
        entries = data['files'] + data['states']
        self.assertEqual(len(entries), len({item['id'] for item in entries}))
        self.assertEqual(len(entries), len({target(item['target']) for item in entries}))
        source_ids = {item['id'] for item in data['files']}
        for item in data['states']:
            self.assertTrue(set(item['sources']) <= source_ids)
            self.assertTrue(item['rollback'])
        for item in entries + data['protected']:
            resolved = target(item['target'])
            self.assertTrue(resolved.startswith('/'))
            self.assertNotIn('..', Path(resolved).parts)
            self.assertNotIn('{{', resolved)
        for item in data['files']:
            for protected in data['protected']:
                self.assertFalse(Path(target(item['target'])).is_relative_to(target(protected['target'])))

    def test_supervisor_launchers_and_counter_files_are_covered(self):
        data = catalog()
        files = {target(item['target']) for item in data['files']}
        counters = {target(item['target']) for item in data['states'] if item['kind'] == 'counter-file'}
        config = configparser.ConfigParser(interpolation=None)
        config.read(ROOT / 'Docker/docassemble-supervisor.conf')
        for name in ('nginx', 'uwsgi', 'uwsgilog', 'celery', 'celerysingle', 'websockets'):
            section = config['program:' + name]
            self.assertIn(section['command'].removeprefix('bash '), files)
            self.assertIn(section['stdout_logfile'], counters)
        monitor = config['eventlistener:privacy-monitor']
        self.assertIn(monitor['command'], files)
        self.assertIn(monitor['stderr_logfile'], counters)

    def test_actual_generated_nginx_and_uwsgi_paths_have_rollback_entries(self):
        states = {target(item['target']) for item in catalog()['states']}
        script = (ROOT / 'Docker/run-nginx.sh').read_text()
        generated = set(re.findall(r'"(/etc/nginx/sites-available/[^"\s]+)"', script))
        links = set(re.findall(r'/etc/nginx/sites-enabled/[a-z]+', script))
        self.assertEqual(len(generated), 5)
        self.assertEqual(len(links), 5)
        self.assertTrue(generated | links <= states)
        initializer = (ROOT / 'Docker/initialize.sh').read_text()
        generated_uwsgi = re.findall(r'> "\$\{DA_ROOT\}(/config/docassemble(?:log)?\.ini)"', initializer)
        self.assertEqual(len(generated_uwsgi), 2)
        self.assertTrue({'/usr/share/docassemble' + path for path in generated_uwsgi} <= states)


if __name__ == '__main__':
    unittest.main()
