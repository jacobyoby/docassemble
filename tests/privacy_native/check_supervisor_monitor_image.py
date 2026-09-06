"""Run only in a disposable Linux test container; all processes/data are synthetic."""
import configparser
import json
import os
from pathlib import Path
import pwd
import shutil
import signal
import subprocess
import sys
import tempfile
import time


def main():
    root = Path('/review')
    source = configparser.ConfigParser(interpolation=None)
    source.read(root / 'Docker/docassemble-supervisor.conf')
    section = 'eventlistener:privacy-monitor'
    assert source[section]['redirect_stderr'] == 'false'
    assert source[section]['stdout_logfile'] == 'NONE'
    assert source[section]['user'] == 'www-data'
    assert os.getuid() == pwd.getpwnam('www-data').pw_uid
    with tempfile.TemporaryDirectory(prefix='synthetic-monitor-') as temporary:
        directory = Path(temporary)
        report = directory / 'monitor.log'
        config = configparser.ConfigParser(interpolation=None)
        config['supervisord'] = {
            'nodaemon': 'true', 'logfile': str(directory / 'supervisor.log'),
            'pidfile': str(directory / 'supervisor.pid'),
            'childlogdir': temporary, 'loglevel': 'info',
        }
        config[section] = dict(source[section])
        # Keep the production command, identity and protocol policy. Only the
        # retained destination changes to this fixture's temporary directory.
        config[section]['stderr_logfile'] = str(report)
        commands = {
            'nginx': '/bin/sh -c "sleep 2; exit 0"',
            'uwsgi': '/bin/sh -c "sleep 2; exit 74"',
            'uwsgilog': '/missing-synthetic-privacy-helper',
            'initialize': '/bin/sh -c "sleep 2; exit 74"',
            'SYNTHETIC_PRIVATE_192.0.2.1': '/bin/false',
        }
        for name, command in commands.items():
            config['program:' + name] = {
                'command': command, 'autostart': 'true', 'autorestart': 'false',
                'startsecs': '1', 'startretries': '0', 'priority': '500',
                'stdout_logfile': 'NONE', 'stderr_logfile': 'NONE',
                'stopasgroup': 'true', 'killasgroup': 'true',
            }
        config['group:main'] = {'programs': 'initialize'}
        application = directory / 'application'
        (application / 'runtime/bin').mkdir(parents=True)
        (application / 'webapp').mkdir()
        (application / 'webapp/privacy-process').symlink_to('/usr/share/docassemble/webapp/privacy-process')
        (application / 'webapp/privacy-diagnostic').symlink_to('/usr/share/docassemble/webapp/privacy-diagnostic')
        (application / 'runtime/bin/activate').write_text("printf 'SYNTHETIC_PRIVATE_BOOTSTRAP\\n' >&2\n")
        # Keep /tmp noexec. Synthetic executables live in the read-only source
        # mount, just as installed service executables live outside writable logs.
        command = root / 'tests/privacy_native/fixtures/application-command.sh'
        for name in ('python', 'celery'):
            (application / 'runtime/bin' / name).symlink_to(command)
        profiles = {'celery': 'run-celery.sh', 'celerysingle': 'run-celery-single.sh',
                    'websockets': 'run-websockets.sh'}
        for name, script in profiles.items():
            program = 'program:' + name
            config[program] = dict(source[program])
            config[program]['command'] = 'bash /review/Docker/' + script
            config[program]['environment'] = f'DA_ROOT="{application}",DA_PYTHON="{application}/runtime"'
            config[program]['autostart'] = 'true'
            config[program]['autorestart'] = 'false'
            config[program]['stdout_logfile'] = str(directory / (name + '.log'))
            assert config[program]['redirect_stderr'] == 'true'
        path = directory / 'supervisor.conf'
        with path.open('w') as stream:
            config.write(stream)
        executable = shutil.which('supervisord')
        assert executable is not None, 'Supervisor is missing from test image'
        with (directory / 'console').open('wb') as console:
            process = subprocess.Popen([executable, '-c', str(path)], stdout=console,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            try:
                wanted = {('monitor', 'monitor_ready', 'ready'),
                          ('uwsgi', 'process_failed', 'exited'),
                          ('uwsgilog', 'process_failed', 'backoff'),
                          ('uwsgilog', 'process_failed', 'fatal')}
                wanted.add(('initialize', 'process_failed', 'exited'))
                wanted.update((name, 'process_failed', 'exited') for name in profiles)
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    assert process.poll() is None, 'Supervisor exited before verification'
                    data = report.read_text() if report.exists() else ''
                    assert 'SYNTHETIC_PRIVATE' not in data
                    rows = [json.loads(line) for line in data.splitlines()]
                    for row in rows:
                        assert set(row) == {'schema', 'component', 'event', 'state'}
                        assert row['schema'] == 1
                    observed = {(row['component'], row['event'], row['state']) for row in rows}
                    assert not any(row['component'] == 'nginx' for row in rows), 'expected exit reported as failure'
                    if wanted <= observed:
                        break
                    time.sleep(0.05)
                else:
                    raise AssertionError('real Supervisor did not deliver required fixed records')
                activity = (directory / 'supervisor.log').read_text()
                assert "spawned: 'privacy-monitor'" in activity
                assert 'unknown state' not in activity.lower()
                assert 'buffer overflow' not in activity.lower()
                for name in profiles:
                    data = (directory / (name + '.log')).read_text()
                    assert 'SYNTHETIC_PRIVATE' not in data
                    records = [json.loads(line) for line in data.splitlines()]
                    assert records and all(len(row) == 14 and row['component'] == name for row in records)
                    assert records[-1]['unclassified'] == 10
                    assert all(row[key] == 0 for row in records for key in row if key.startswith(('status_', 'latency_')))
                print('Supervisor integration: native/application failures reported; real application launchers and logger initialization emitted counters only; expected/unrelated exits ignored')
            except Exception:
                # This directory contains only configuration and output from
                # this synthetic fixture. Preserve failure evidence in CI output.
                for name in ('console', 'supervisor.log', 'monitor.log',
                             *(profile + '.log' for profile in profiles)):
                    artifact = directory / name
                    if artifact.exists():
                        print(name + ':\n' + artifact.read_text(), file=sys.stderr)
                raise
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=2)
                    raise AssertionError('Supervisor did not stop its fixture processes')


if __name__ == '__main__':
    main()
