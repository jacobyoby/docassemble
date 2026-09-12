"""Host-side orderly stop/start of the already-owned native installation fixture."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import time

spec = importlib.util.spec_from_file_location('install_check', Path(__file__).with_name('check_install_image.py'))
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


def docker(*args, timeout=30, check=True):
    return subprocess.run(['docker', *args], capture_output=True, timeout=timeout, check=check)


def stopped_file(container, path, missing=False):
    result = docker('cp', container + ':' + path, '-', check=False)
    if result.returncode:
        assert missing and b'Could not find' in result.stderr, 'cannot inspect stopped-container marker'
        return None
    assert len(result.stdout) <= 2_000_000, 'oversized synthetic archive'
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode='r:') as archive:
        members = archive.getmembers()
        assert len(members) == 1 and members[0].isfile() and members[0].size < 1_000_000
        return archive.extractfile(members[0]).read()


def interrupted_start(container, directory):
    flag = directory / 'hold-startup'
    flag.write_text('hold')
    docker('cp', str(flag), container + ':/tmp/jos81-rehearsal/hold-startup')
    docker('start', container)
    probe = """from pathlib import Path
assert Path('/tmp/jos81-rehearsal/startup-held').read_text() == 'held'
assert Path('/var/run/docassemble/da_running').exists()
assert not Path('/var/run/docassemble/ready').exists()
assert Path('/usr/share/docassemble/log/jos81-restored').read_bytes() == b'JOS81_BACKUP_ONLY_RESTORE'
"""
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        result = docker('exec', container, 'python3.14', '-I', '-B', '-c', probe, check=False)
        if result.returncode == 0:
            break
        time.sleep(1)
    else:
        raise AssertionError('initializer did not reach the one-shot startup hold')
    stop = """from pathlib import Path
import json
import time
import xmlrpc.client
rpc = xmlrpc.client.ServerProxy('http://localhost:9001/RPC2')
assert rpc.supervisor.stopProcess('main:initialize', False)
assert rpc.supervisor.getProcessInfo('main:initialize')['statename'] in ('STOPPING', 'STOPPED')
Path('/tmp/jos81-rehearsal/release-startup').touch()
deadline = time.monotonic() + 40
while rpc.supervisor.getProcessInfo('main:initialize')['statename'] != 'STOPPED':
    assert time.monotonic() < deadline, 'captured initializer did not stop after its child was released'
    time.sleep(0.2)
assert Path('/var/run/docassemble/da_running').exists()
assert not Path('/var/run/docassemble/ready').exists()
info = rpc.supervisor.getProcessInfo('main:initialize')
assert info['exitstatus'] == 143, 'initializer interruption exit changed'
print(json.dumps({'initialize_log': info['stdout_logfile']}))
"""
    output = docker('exec', container, 'python3.14', '-I', '-B', '-c', stop, timeout=50)
    logpath = json.loads(output.stdout)['initialize_log']
    docker('stop', '--time', '1000', container, timeout=1020)
    state = json.loads(docker('inspect', '--format', '{{json .State}}', container).stdout)
    assert state['Running'] is False and state['OOMKilled'] is False and state['ExitCode'] == 0
    assert stopped_file(container, '/var/run/docassemble/da_running') is not None
    assert stopped_file(container, '/var/run/docassemble/ready', missing=True) is None
    install.records(stopped_file(container, logpath), 'initialize')
    marker = directory / 'jos81-unsafe-restore'
    marker.write_bytes(b'JOS81_MUST_NOT_RESTORE')
    docker('cp', str(marker), container + ':/usr/share/docassemble/backup/log/jos81-unsafe-restore')
    print('actual initializer interruption preserved unsafe-start state before a new backup-only marker was inserted', flush=True)


def main(container, directory):
    # Names and labels must identify the caller's unique disposable fixture.
    metadata = json.loads(docker('inspect', container).stdout)[0]
    assert metadata['Config']['Labels'].get('task') == 'JOS-81-install-review'
    assert metadata['Name'].startswith('/jos81-install-run.')
    assert metadata['State']['Running']
    assert metadata['HostConfig']['NetworkMode'] == 'none'
    before = json.loads(docker('exec', container, 'cat', '/tmp/jos81-rehearsal/lifecycle.json').stdout)
    # Supervisor stops its groups serially. Cover all enabled group budgets,
    # including the concurrent initialize/PostgreSQL/Redis group, with margin.
    docker('stop', '--time', '1000', container, timeout=1020)
    state = json.loads(docker('inspect', '--format', '{{json .State}}', container).stdout)
    assert state['Running'] is False and state['OOMKilled'] is False and state['ExitCode'] == 0
    for name in ('ready', 'da_running', 'status-postgres-running', 'status-redis-running',
                 'status-rabbitmq-running'):
        assert stopped_file(container, '/var/run/docassemble/' + name, missing=True) is None, 'unclean shutdown marker remains'
    assert stopped_file(container, '/usr/share/docassemble/backup/log/jos81-shutdown') == b'JOS81_SHUTDOWN_BACKUP'
    install.records(stopped_file(container, before['initialize_log']), 'initialize')
    logs = docker('logs', container)
    assert b'JOS81_PRIVATE_' not in logs.stdout + logs.stderr
    # Insert a new synthetic file into only the stopped container's backup tree.
    # Its later appearance in live logs must come from the actual startup restore.
    marker = directory / 'jos81-restored'
    marker.write_bytes(b'JOS81_BACKUP_ONLY_RESTORE')
    docker('cp', str(marker), container + ':/usr/share/docassemble/backup/log/jos81-restored')
    interrupted_start(container, directory)
    docker('start', container)
    probe = """from pathlib import Path
import json
import xmlrpc.client
assert Path('/var/run/docassemble/ready').exists()
rpc = xmlrpc.client.ServerProxy('http://localhost:9001/RPC2')
states = {p['name']: p['statename'] for p in rpc.supervisor.getAllProcessInfo()}
assert all(states.get(n) == 'RUNNING' for n in ('initialize', 'nginx', 'uwsgi', 'celery', 'celerysingle', 'websockets'))
original = json.loads(Path('/tmp/jos81-rehearsal/services.json').read_text())
for name, value in original.items():
    if value == 'STOPPED' and states.get(name) == 'RUNNING':
        assert rpc.supervisor.stopProcess(name, True)
"""
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        result = docker('exec', container, 'python3.14', '-I', '-B', '-c', probe, check=False, timeout=20)
        if result.returncode == 0:
            break
        time.sleep(2)
    else:
        raise AssertionError('candidate did not become ready after orderly restart')
    print('whole-container shutdown was clean, produced log backup and retained safe initializer output; same-volume restart is ready', flush=True)


if __name__ == '__main__':
    assert len(sys.argv) == 3
    main(sys.argv[1], Path(sys.argv[2]))
