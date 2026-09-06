"""Full-image installation/rollback test using only synthetic local data."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import time
import urllib.request
import urllib.error
import xmlrpc.client

REPO = Path(__file__).resolve().parents[2]
WORK = Path('/tmp/jos81-rehearsal')
ROOT = '/usr/share/docassemble'
SITE = ROOT + '/local3.14/lib/python3.14/site-packages'
CATALOG = json.loads((REPO / 'docs/privacy/install-catalog.json').read_text())
RPC = xmlrpc.client.ServerProxy('http://localhost:9001/RPC2')
COMPONENTS = ('celery', 'celerysingle', 'websockets', 'uwsgi', 'nginx')
COUNTERS = {'privacy-celery.log': 'celery', 'privacy-celerysingle.log': 'celerysingle',
            'privacy-websockets.log': 'websockets', 'privacy-uwsgi.log': 'uwsgi',
            'nginx-safe.log': 'nginx'}


def records(data, component):
    def unique(pairs):
        assert len({key for key, unused in pairs}) == len(pairs), 'duplicate counter fields'
        return dict(pairs)
    values = [json.loads(line, object_pairs_hook=unique) for line in data.splitlines()]
    assert values, 'missing counters for ' + component
    keys = {'schema', 'component', 'status_1xx', 'status_2xx', 'status_3xx', 'status_4xx',
            'status_5xx', 'latency_fast', 'latency_medium', 'latency_slow', 'latency_timeout',
            'unclassified', 'rejected', 'dropped'}
    for value in values:
        assert isinstance(value, dict) and set(value) == keys, 'unexpected counter fields'
        assert value['schema'] == 1 and value['component'] == component, 'counter identity'
        assert all(type(count) is int and 0 <= count <= 2147483647
                   for key, count in value.items() if key != 'component'), 'counter bounds'
        if component in ('celery', 'celerysingle', 'websockets'):
            assert all(count == 0 for key, count in value.items()
                       if key.startswith(('status_', 'latency_'))), 'application request counts'
    return values


def read_counters():
    return {component: records(Path(ROOT + '/log/' + name).read_text(), component)
            for name, component in COUNTERS.items()}


def run(*args, timeout=100, **kwargs):
    result = subprocess.run(args, capture_output=True, timeout=timeout, **kwargs)
    if result.returncode:
        raise RuntimeError(str(args[:3]) + '\n' + result.stdout.decode(errors='replace')[-2500:] + result.stderr.decode(errors='replace')[-2500:])
    return result.stdout


def resolve(value):
    return Path(value.replace('{{DA_ROOT}}', ROOT).replace('{{SITE_PACKAGES}}', SITE))


def state(path, contents=True):
    try:
        value = path.lstat()
    except FileNotFoundError:
        return {'kind': 'absent'}
    result = {'mode': stat.S_IMODE(value.st_mode), 'uid': value.st_uid, 'gid': value.st_gid}
    if path.is_symlink():
        result.update(kind='link', target=os.readlink(path))
    elif path.is_dir():
        result['kind'] = 'directory'
    elif path.is_file():
        result['kind'] = 'file'
        if contents:
            result['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        result['kind'] = 'special'
    return result


def protected():
    result = {}
    for item in CATALOG['protected']:
        base = resolve(item['target'])
        # Active logs and uploads keep a fixed synthetic sentinel, not a changing tree.
        if item['id'] in ('uploads', 'historical-logs'):
            base /= 'jos81-preserve-sentinel'
        result[str(base)] = state(base)
        if base.is_dir():
            for path in sorted(base.rglob('*')):
                result[str(path)] = state(path)
    return result


def statuses():
    return {item['name']: item['statename'] for item in RPC.supervisor.getAllProcessInfo()}


def stop_services():
    for name in ('nginx', 'cron', 'exim4', 'websockets', 'celery', 'celerysingle', 'uwsgi', 'privacy-monitor'):
        if statuses().get(name) == 'RUNNING':
            RPC.supervisor.stopProcess(name, True)
    check = subprocess.run(['pgrep', '-x', 'uwsgi'], capture_output=True)
    assert check.returncode == 1, 'uWSGI process remains after stop'
    sockpath = Path('/var/run/uwsgi/docassemble.sock')
    if sockpath.exists():
        assert stat.S_ISSOCK(sockpath.lstat().st_mode)
        with socket.socket(socket.AF_UNIX) as probe:
            try:
                probe.connect(str(sockpath))
            except ConnectionRefusedError:
                pass
            else:
                raise AssertionError('application socket still accepts connections')
        sockpath.unlink()
    Path('/var/run/uwsgi/uwsgi.pid').unlink(missing_ok=True)


def start_services(candidate):
    run('supervisorctl', '-s', 'http://localhost:9001', 'reread')
    run('supervisorctl', '-s', 'http://localhost:9001', 'update')
    if candidate:
        for unused in range(30):
            if statuses().get('privacy-monitor') == 'RUNNING':
                break
            time.sleep(0.2)
        assert statuses()['privacy-monitor'] == 'RUNNING'
    for name in COMPONENTS:
        if statuses().get(name) != 'RUNNING':
            assert RPC.supervisor.startProcess(name, True)
    assert all(statuses()[name] == 'RUNNING' for name in COMPONENTS)


def fetch(path, port=80):
    request = urllib.request.Request('http://127.0.0.1:' + str(port) + path, headers={'Host': 'privacy-install.test'})
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read(2_000_000)
        assert response.status == 200
        return body


def ready(path, marker, port=80):
    deadline = time.monotonic() + 30
    while True:
        try:
            body = fetch(path, port)
            assert marker in body and b'is starting' not in body
            return
        except (urllib.error.URLError, TimeoutError, AssertionError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.5)


def routes():
    ready('/kept-rewrite', b'JOS81_KEEP_REWRITE')
    ready('/', b'JOS81_KEEP_SITE', 8088)
    ready('/nj/', b'JOS81_APPLICATION_OK')


def configure():
    import yaml  # Existing application dependency, not a new test/service dependency.
    package = Path(SITE + '/docassemble/privacyfixture')
    (package / 'data/questions').mkdir(parents=True)
    (package / '__init__.py').write_text('')
    (package / 'data/questions/install.yml').write_text(
        'metadata:\n  title: Privacy installation check\n---\nmandatory: True\n'
        'question: Privacy installation check\nsubquestion: JOS81_APPLICATION_OK\n')
    path = Path(ROOT + '/config/config.yml')
    config = yaml.safe_load(path.read_text())
    assert config['allow demo'] is False
    assert config['enable playground'] is False
    assert config['allow log viewing'] is False
    assert config['allow configuration editing'] is False
    assert config['behind https load balancer'] is True
    config['default interview'] = 'docassemble.privacyfixture:data/questions/install.yml'
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    assert RPC.supervisor.stopProcess('uwsgi', True)
    assert RPC.supervisor.startProcess('uwsgi', True)
    ready('/nj/', b'JOS81_APPLICATION_OK')
    print('real application serves synthetic interview with demo access disabled', flush=True)


def seed():
    assert Path('/var/run/docassemble/ready').exists()
    assert all(statuses()[name] == 'RUNNING' for name in COMPONENTS)
    WORK.mkdir(mode=0o700)
    template = Path(ROOT + '/config/nginx-http.dist')
    text = template.read_text()
    assert 'form_rewrite_rules' not in text
    template.write_text(text.replace('    location {{DAWSGIROOT}}', '    include /etc/nginx/form_rewrite_rules.conf;\n    location {{DAWSGIROOT}}', 1))
    Path('/etc/nginx/form_rewrite_rules.conf').write_text('location = /kept-rewrite { return 200 "JOS81_KEEP_REWRITE"; }\n')
    site = Path('/etc/nginx/sites-available/formapauperis')
    site.write_text('server { listen 127.0.0.1:8088; server_name privacy-install.test; location / { return 200 "JOS81_KEEP_SITE"; } }\n')
    Path('/etc/nginx/sites-enabled/formapauperis').symlink_to(site)
    for dirname in ('files', 'log'):
        Path(ROOT + '/' + dirname + '/jos81-preserve-sentinel').write_text('JOS81_PRESERVE_' + dirname)
    # Exercise metadata restoration for existing counter files, without historical data.
    for item in CATALOG['states']:
        if item['kind'] == 'counter-file':
            path = resolve(item['target'])
            if item['id'] == 'monitor-log':
                assert not path.exists()
                continue
            assert not path.exists() or path.stat().st_size == 0
            path.touch()
            os.chmod(path, 0o640)
            os.chown(path, 0, 0)
    # A stopped producer must remain stopped after rollback.
    if statuses().get('cron') == 'RUNNING':
        assert RPC.supervisor.stopProcess('cron', True)
    assert RPC.supervisor.stopProcess('nginx', True)
    assert RPC.supervisor.startProcess('nginx', True)
    routes()
    snapshot()


def snapshot():
    assert all(statuses()[name] == 'RUNNING' for name in COMPONENTS)
    routes()
    original = statuses()
    assert not set(original.values()) & {'STARTING', 'STOPPING', 'BACKOFF'}, 'unstable baseline'
    (WORK / 'services.json').write_text(json.dumps(original, indent=2))
    stop_services()
    metadata = {str(resolve(item['target'])): state(resolve(item['target']), contents=False)
                for item in CATALOG['states'] if item['kind'] == 'counter-file'}
    (WORK / 'counter-metadata.json').write_text(json.dumps(metadata, indent=2))
    paths = [resolve(item['target']) for item in CATALOG['files']]
    for item in CATALOG['states']:
        if item['kind'] == 'counter-file':
            continue
        path = resolve(item['target'])
        if item['kind'] == 'logger-bytecode-only':
            paths.extend(path.glob('log_initialize.*.pyc'))
        else:
            paths.append(path)
    paths = sorted(set(paths))
    baseline = {str(path): state(path) for path in paths}
    (WORK / 'baseline.json').write_text(json.dumps(baseline, indent=2))
    (WORK / 'protected.json').write_text(json.dumps(protected(), indent=2))
    # Directory metadata is restored explicitly; archiving /var/run/uwsgi would
    # make tar traverse the image's /var/run -> /run link during extraction.
    existing = [str(path).lstrip('/') for path in paths
                if baseline[str(path)]['kind'] not in ('absent', 'directory')]
    (WORK / 'restore-list.txt').write_text('\n'.join(existing) + '\n')
    run('tar', '--numeric-owner', '--no-recursion', '-cpf', str(WORK / 'rollback.tar'), '-C', '/', '-T', str(WORK / 'restore-list.txt'))
    print('baseline routes pass; file snapshot, counter metadata and service states saved', flush=True)


def install():
    expected = json.loads((WORK / 'baseline.json').read_text())
    assert all(state(Path(path)) == value for path, value in expected.items())
    patched = WORK / 'patched' / 'Docker'
    patched.mkdir(parents=True)
    shutil.copy2(ROOT + '/webapp/initialize.sh', patched / 'initialize.sh')
    run('patch', '--batch', '--fuzz=0', '-p1', '-d', str(patched.parent), '-i', str(REPO / 'tests/.privacy-build/initialize-privacy.patch'))
    installed = {}
    for item in CATALOG['files']:
        target = resolve(item['target'])
        if item.get('existing') == 'preserve-and-validate' and target.exists():
            installed[str(target)] = state(target)
            continue
        if item['kind'] == 'binary':
            source = REPO / 'tests/.privacy-build' / item['source'].replace('{{ARCH}}', 'amd64')
            raw = source.read_bytes()
            assert raw[:4] == b'\x7fELF' and int.from_bytes(raw[18:20], 'little') == 62
        elif item.get('existing') == 'apply-privacy-diff':
            source = patched / 'initialize.sh'
        else:
            source = REPO / item['source']
        target.parent.mkdir(parents=True, exist_ok=True)
        run('install', '-o', 'root', '-g', 'root', '-m', item['mode'], str(source), str(target))
        installed[str(target)] = state(target)
        assert installed[str(target)]['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    for source, destination in (('docassemble.ini.dist', 'docassemble.ini'), ('docassemblelog.ini.dist', 'docassemblelog.ini')):
        text = Path(ROOT + '/config/' + source).read_text()
        text = text.replace('{{DA_PYTHON}}', ROOT + '/local3.14').replace('{{DA_ROOT}}', ROOT).replace('{{DAWSGIROOT}}', '/nj')
        assert '{{' not in text
        Path(ROOT + '/config/' + destination).write_text(text)
    for path in Path(SITE + '/docassemble/webapp/__pycache__').glob('log_initialize.*.pyc'):
        path.unlink()
    for item in CATALOG['states']:
        if item['kind'] == 'counter-file':
            path = resolve(item['target'])
            path.touch(exist_ok=True)
            os.chmod(path, 0o600)
            os.chown(path, 33, 33)
    (WORK / 'installed.json').write_text(json.dumps(installed, indent=2))
    assert protected() == json.loads((WORK / 'protected.json').read_text())
    start_services(True)
    time.sleep(2)
    before = read_counters()
    routes()
    assert protected() == json.loads((WORK / 'protected.json').read_text())
    for unused in range(50):
        time.sleep(0.2)
        counters = read_counters()
        if all(counters[name][-1]['status_2xx'] > before[name][-1]['status_2xx']
               for name in ('nginx', 'uwsgi')):
            break
    else:
        raise AssertionError('real requests did not advance nginx/uWSGI counters')
    (WORK / 'counters.json').write_text(json.dumps(counters, indent=2))
    print('candidate services and custom/application routes pass; protected paths unchanged', flush=True)


def rollback():
    stop_services()
    metadata = json.loads((WORK / 'counter-metadata.json').read_text())
    counter_hashes = {path: state(Path(path))['sha256'] for path in metadata}
    expected = json.loads((WORK / 'baseline.json').read_text())
    for path, value in expected.items():
        item = Path(path)
        if value['kind'] == 'absent' and (item.exists() or item.is_symlink()):
            if item.is_dir():
                continue
            item.unlink()
    run('tar', '--numeric-owner', '-xpf', str(WORK / 'rollback.tar'), '-C', '/')
    for path, value in sorted(expected.items(), key=lambda item: len(item[0]), reverse=True):
        item = Path(path)
        if value['kind'] == 'directory':
            assert item.is_dir() and not item.is_symlink()
            os.chown(item, value['uid'], value['gid'])
            os.chmod(item, value['mode'])
        if value['kind'] == 'absent' and item.is_dir():
            item.rmdir()
        assert state(item) == value, path + ' did not restore exactly'
    for path, value in metadata.items():
        item = Path(path)
        if value['kind'] != 'absent':
            assert value['kind'] == 'file'
            os.chown(item, value['uid'], value['gid'])
            os.chmod(item, value['mode'])
            assert state(item, contents=False) == value, 'counter metadata changed'
        assert state(item)['sha256'] == counter_hashes[path], 'counter contents changed'
    assert protected() == json.loads((WORK / 'protected.json').read_text())
    start_services(False)
    routes()
    assert 'privacy-monitor' not in statuses()
    original = json.loads((WORK / 'services.json').read_text())
    for name, value in original.items():
        if value == 'RUNNING' and statuses().get(name) != 'RUNNING':
            assert RPC.supervisor.startProcess(name, True)
    assert statuses() == original, 'service states differ from baseline'
    assert protected() == json.loads((WORK / 'protected.json').read_text())
    assert all(state(Path(path))['sha256'] == digest for path, digest in counter_hashes.items())
    print('rollback files/metadata, preserved counters, original service states and routes pass', flush=True)


if __name__ == '__main__':
    if len(sys.argv) != 1:
        raise SystemExit('run without arguments inside the disposable test container')
    socket.setdefaulttimeout(90)
    configure()
    seed()
    install()
    rollback()
