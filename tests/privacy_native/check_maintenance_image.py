"""Real local maintenance/copy/restart acceptance in the owned synthetic image."""
from http.cookies import SimpleCookie
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

spec = importlib.util.spec_from_file_location('install_check', Path(__file__).with_name('check_install_image.py'))
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)
ROOT = Path(install.ROOT)
WORK = install.WORK
HOOK = Path(install.SITE + '/docassemble/webapp/starthook.py')
HISTORY = b'JOS81_HISTORICAL_NGINX'
SHUTDOWN = b'JOS81_SHUTDOWN_BACKUP'
RESTORE = b'JOS81_BACKUP_ONLY_RESTORE'


def scan():
    install.private_output_absent((ROOT / 'log', Path('/var/log'),
                                  ROOT / 'backup/log', ROOT / 'backup/nginxlogs'))
    day = (WORK / 'maintenance-day').read_text()
    install.private_output_absent((ROOT / 'backup' / day / 'log',))


def initializer():
    info = install.RPC.supervisor.getProcessInfo('main:initialize')
    assert info['statename'] == 'RUNNING'
    assert Path(f"/proc/{info['pid']}/exe").resolve().name == 'privacy-process'
    children = []
    for task in Path(f"/proc/{info['pid']}/task").glob('*/children'):
        children.extend(int(pid) for pid in task.read_text().split())
    assert len(children) == 1, 'initializer must have one captured Bash child'
    argv = Path(f'/proc/{children[0]}/cmdline').read_bytes().split(b'\0')[:3]
    assert argv == [b'/bin/bash', str(ROOT / 'webapp/initialize.sh').encode(), b'--privacy-captured']
    values = install.records(install.RPC.supervisor.readProcessStdoutLog('main:initialize', 0, 1_000_000),
                             'initialize')
    assert values[-1]['unclassified'] >= 2, 'startup hook output did not advance initializer counters'
    assert (WORK / 'startup-receipt').read_text().count('emitted\n') > 0, 'startup hook did not execute its positive control'
    return info


def seed():
    original = HOOK.read_bytes()
    (WORK / 'starthook-original.py').write_bytes(original)
    # A real initializer startup module emits both markers before normal config
    # loading. Other services do not execute this module.
    prefix = b"""import os
assert os.getuid() == 0 and os.getcwd() == '/tmp'
try:
    os.fstat(3)
except OSError:
    pass
else:
    raise AssertionError('launcher fd3 reached the startup module')
os.write(1, b'JOS81_PRIVATE_INITIALIZER_STDOUT\\n')
os.write(2, b'JOS81_PRIVATE_INITIALIZER_STDERR\\n')
with open('/tmp/jos81-rehearsal/startup-receipt', 'a') as receipt:
    receipt.write('emitted\\n')
from pathlib import Path
hold = Path('/tmp/jos81-rehearsal/hold-startup')
if hold.exists():
    import sys
    import time
    hold.unlink()
    hold.with_name('startup-held').write_text('held')
    deadline = time.monotonic() + 60
    while not hold.with_name('release-startup').exists():
        assert time.monotonic() < deadline, 'startup hold expired'
        time.sleep(0.1)
    sys.exit(0)
"""
    HOOK.write_bytes(prefix + original)


def command(path, expected=0, **env):
    result = subprocess.run(['bash', str(path)], env=dict(os.environ, **env),
                            capture_output=True, timeout=120)
    assert result.returncode == expected and not result.stderr, 'maintenance exit/stderr changed'
    values = install.records(result.stdout, 'maintenance')
    assert len(values) == 1, 'finite maintenance command emitted periodic/raw output'
    return values[0]


def prepare():
    initializer()
    history = Path('/var/log/nginx/jos81-history')
    history.write_bytes(HISTORY)
    os.chmod(history, 0o600)
    # These are the installed scripts and real local operations, not copied command fragments.
    command(ROOT / 'webapp/sync.sh')
    command('/etc/cron.hourly/docassemble')
    command('/etc/cron.weekly/docassemble')
    command('/etc/cron.monthly/docassemble')
    command('/etc/cron.daily/docassemble')
    day = install.run('date', '+%m-%d').decode().strip()
    (WORK / 'maintenance-day').write_text(day)
    for path in (ROOT / 'log/jos81-history', ROOT / 'backup/log/jos81-history',
                 ROOT / 'backup/nginxlogs/jos81-history', ROOT / 'backup' / day / 'log/jos81-history'):
        assert path.read_bytes() == HISTORY, 'local maintenance did not preserve/copy historical bytes'
    assert (ROOT / 'backup/log/jos81-preserve-sentinel').read_text() == 'JOS81_PRESERVE_log'
    assert (ROOT / 'backup/files/jos81-preserve-sentinel').read_text() == 'JOS81_PRESERVE_files'
    assert (ROOT / 'backup/config.yml').read_bytes() == (ROOT / 'config/config.yml').read_bytes()
    assert any((ROOT / 'backup/postgres').iterdir()), 'database backup missing'
    # Force the actual non-mail logrotate stanza and callback after local copying.
    rotation = Path('/etc/logrotate.d/docassemble').read_text()
    assert rotation.count('/var/mail/mail\n') == 1
    nonmail = WORK / 'non-mail-logrotate'
    nonmail.write_text(rotation.split('/var/mail/mail\n', 1)[0])
    legacy = ROOT / 'log/worker.log'
    prior = legacy.read_bytes() + b'JOS81_HISTORICAL_ROTATION\n'
    legacy.write_bytes(prior)
    pids = {name: install.RPC.supervisor.getProcessInfo(name)['pid']
            for name in ('celery', 'celerysingle', 'websockets', 'uwsgi')}
    output = install.run('logrotate', '-f', '-s', str(WORK / 'logrotate-state'), str(nonmail),
                         env=dict(os.environ, CONTAINERROLE=':all:'), timeout=180)
    assert len(install.records(output, 'maintenance')) == 1, 'rotation callback did not emit safe output'
    assert (ROOT / 'log/worker.log.1').read_bytes() == prior, 'rotation changed historical bytes'
    for name, pid in pids.items():
        current = install.RPC.supervisor.getProcessInfo(name)
        assert current['statename'] == 'RUNNING'
        assert (current['pid'] == pid) == (name == 'uwsgi'), 'rotation callback service behavior changed'
    install.routes()
    install.read_counters()
    assert install.protected() == json.loads((WORK / 'protected.json').read_text())
    scan()
    # This marker appears only after daily backup, proving the shutdown path copies it.
    assert not (ROOT / 'backup/log/jos81-shutdown').exists()
    (ROOT / 'log/jos81-shutdown').write_bytes(SHUTDOWN)
    os.chown(ROOT / 'log/jos81-shutdown', 33, 33)
    assert not (ROOT / 'log/jos81-restored').exists()
    (WORK / 'lifecycle.json').write_text(json.dumps({
        'initialize_log': initializer()['stdout_logfile'],
        'startup_receipts': (WORK / 'startup-receipt').read_text().count('emitted\n')}))
    print('installed hourly/daily/weekly/monthly/sync and rotation callback pass; historical copies preserved', flush=True)


def resume():
    install.routes()
    initializer()
    before = json.loads((WORK / 'lifecycle.json').read_text())
    assert (WORK / 'startup-receipt').read_text().count('emitted\n') >= before['startup_receipts'] + 2, 'both restart attempts must execute the startup marker control'
    assert (ROOT / 'log/jos81-restored').read_bytes() == RESTORE, 'backup-only sentinel was not restored'
    assert (ROOT / 'backup/log/jos81-unsafe-restore').read_bytes() == b'JOS81_MUST_NOT_RESTORE'
    assert not (ROOT / 'log/jos81-unsafe-restore').exists(), 'interrupted-start guard restored backup logs'
    for path in (ROOT / 'log/jos81-shutdown', ROOT / 'backup/log/jos81-shutdown'):
        assert path.read_bytes() == SHUTDOWN
    assert (ROOT / 'files/jos81-preserve-sentinel').read_text() == 'JOS81_PRESERVE_files'
    assert install.protected() == json.loads((WORK / 'protected.json').read_text())
    cookies = SimpleCookie()
    cookies.load(json.loads((WORK / 'cron-session.json').read_text()))
    path = '/nj/?i=docassemble.privacyfixture:data/questions/cron.yml'
    assert b'JOS81_CRON_COUNT_2' in install.fetch(path, cookies=cookies), 'database session did not survive restart'
    install.records(install.run('bash', str(ROOT / 'webapp/run-cron.sh'), 'cron_hourly'), 'cron')
    assert b'JOS81_CRON_COUNT_3' in install.fetch(path, cookies=cookies)
    install.queued_job()
    scan()
    shutil.copyfile(WORK / 'starthook-original.py', HOOK)
    print('orderly same-volume restart restored backup-only logs and preserved configuration, upload and database session; queue/cron still work', flush=True)


if __name__ == '__main__':
    assert sys.argv[1:] in (['seed'], ['prepare'], ['resume'])
    {'seed': seed, 'prepare': prepare, 'resume': resume}[sys.argv[1]]()
