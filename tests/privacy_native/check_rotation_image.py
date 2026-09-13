"""Real Supervisor, Go capture, syslog TCP forwarding and native logrotate."""
import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import tempfile
import time

from test_rotation_ownership import FORWARDED, ROOT, supervisor


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=2)
        raise AssertionError('native rotation fixture did not stop')


def rows(path, component, syslog=False, live=True):
    data = path.read_text() if path.exists() else ''
    assert 'SYNTHETIC_PRIVATE' not in data and 'synthetic.yml' not in data, path
    result = []
    if not live:
        assert not data or data.endswith('\n'), ('truncated retained counter', path)
    expected = {'schema', 'component', 'status_1xx', 'status_2xx', 'status_3xx', 'status_4xx',
                'status_5xx', 'latency_fast', 'latency_medium', 'latency_slow', 'latency_timeout',
                'unclassified', 'rejected', 'dropped'}
    # A file can be observed between writes; only inspect complete records.
    for line in data.splitlines(keepends=True):
        if not line.endswith('\n'):
            continue
        if syslog:
            line = line[line.index('{'):]
        row = json.loads(line)
        assert set(row) == expected and row['schema'] == 1 and row['component'] == component, (path, row)
        assert all(type(value) is int and 0 <= value <= 2147483647
                   for key, value in row.items() if key != 'component')
        result.append(row)
    return result


def await_condition(condition, processes, message, timeout=20):
    deadline = time.monotonic() + timeout
    while True:
        assert all(process.poll() is None for process in processes), 'native fixture exited early'
        if condition():
            return
        assert time.monotonic() < deadline, message
        time.sleep(0.05)


def capture_identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    except FileNotFoundError:
        return None
    if fields[0] in ('Z', 'X'):
        return None
    return int(fields[1]), int(fields[19])  # Parent PID and Linux start time.


def syslog_config(directory, name, text):
    config = directory / (name + '.conf')
    config.write_text('@version: 4.3\n@include "scl.conf"\n'
                      'options { flush_lines(0); stats(freq(0)); };\n' + text)
    command = ['syslog-ng', '--foreground', '--no-caps', '--cfgfile', str(config),
               '--persist-file', str(directory / (name + '.persist')),
               '--pidfile', str(directory / (name + '.pid')),
               '--control', str(directory / (name + '.ctl'))]
    try:
        subprocess.run([*command, '--syntax-only'], check=True, timeout=5, capture_output=True)
    except subprocess.SubprocessError as error:
        print(getattr(error, 'stderr', b'') or b'')
        raise
    return command


def main():
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix='privacy-rotation-') as temporary:
        directory = Path(temporary)
        local = remote = directory / 'logs'
        local.mkdir()
        # Execute the exact production precreation/ownership fragment, with only
        # its absolute log directory mapped into this private fixture directory.
        initialization = (ROOT / 'Docker/initialize.sh').read_text()
        start = initialization.index('touch /usr/share/docassemble/log/')
        end = initialization.index('chown -R www-data:www-data /usr/share/docassemble/log', start)
        end += len('chown -R www-data:www-data /usr/share/docassemble/log')
        subprocess.run(['bash', '-c', initialization[start:end].replace('/usr/share/docassemble/log', str(local))],
                       check=True, capture_output=True, timeout=5)
        original = supervisor()
        capture = {name: local / Path(original['program:' + name]['stdout_logfile']).name for name in FORWARDED}
        for path in capture.values():
            assert path.stat().st_uid == os.getuid() and path.stat().st_mode & 0o777 == 0o600
        # Keep actual source lines and program labels. Only fixture directories
        # and the loopback TCP port differ from the maintained syslog route.
        shipper_source = (ROOT / 'Docker/docassemble-syslog-ng.conf').read_text()
        file_lines = [line for line in shipper_source.splitlines()
                      if any(f'program-override("{name}")' in line for name in FORWARDED)]
        assert len(file_lines) == 4
        shipper = ('source s_docassemble {\n' + '\n'.join(file_lines) + '\n};\n'
                   'destination d_network { syslog("127.0.0.1" transport("tcp") port(10514)); };\n'
                   'log { source(s_docassemble); destination(d_network); };\n')
        shipper = shipper.replace('/usr/share/docassemble/log', str(local))
        receiver_source = (ROOT / 'Docker/syslog-ng.conf').read_text()
        keys = ('daworker', 'daworkersingle', 'uwsgi', 'websockets')
        receiver_lines = [line for line in receiver_source.splitlines()
                          if any(line.startswith(prefix + key + ' ') for key in keys
                                 for prefix in ('destination d_', 'filter f_'))
                          or any('filter(f_' + key + '); destination(d_' + key + ');' in line for key in keys)]
        assert len(receiver_lines) == 12
        receiver = 'source s_network { syslog(transport("tcp") port(10514)); };\n' + '\n'.join(receiver_lines)
        receiver = receiver.replace('/usr/share/docassemble/log', str(remote))
        receiver_command = syslog_config(directory, 'receiver', receiver)
        shipper_command = syslog_config(directory, 'shipper', shipper)
        config = configparser.ConfigParser(interpolation=None)
        config['supervisord'] = {'nodaemon': 'true', 'logfile': str(directory / 'supervisor.log'),
                                'pidfile': str(directory / 'supervisor.pid'), 'childlogdir': temporary,
                                'loglevel': 'info'}
        for name, path in capture.items():
            section = dict(original['program:' + name])
            section.update(command='/usr/share/docassemble/webapp/privacy-process --component ' + name
                           + ' -- /bin/sh /review/tests/privacy_native/fixtures/rotation-command.sh '
                           + str(directory / 'after-rotation') + ' --die-on-term',
                           stdout_logfile=str(path), stdout_logfile_maxbytes='256',
                           autostart='true', autorestart='false')
            assert section['stdout_logfile_backups'] == '7'
            config['program:' + name] = section
        path = directory / 'supervisor.conf'
        with path.open('w') as stream:
            config.write(stream)
        processes = []
        with (directory / 'console').open('wb') as console:
            try:
                collector = subprocess.Popen(receiver_command, stdout=console, stderr=subprocess.STDOUT,
                                             start_new_session=True)
                processes.append(collector)
                def collector_ready():
                    try:
                        with socket.create_connection(('127.0.0.1', 10514), timeout=0.2):
                            return True
                    except OSError:
                        return False
                await_condition(collector_ready, processes, 'collector did not bind its test port', timeout=5)
                forwarder = subprocess.Popen(shipper_command, stdout=console, stderr=subprocess.STDOUT,
                                             start_new_session=True)
                processes.append(forwarder)
                manager = subprocess.Popen(['supervisord', '-c', str(path)], stdout=console,
                                           stderr=subprocess.STDOUT, start_new_session=True)
                processes.append(manager)
                await_condition(lambda: all(Path(str(path) + '.7').exists() for path in capture.values()),
                                processes, 'Supervisor did not retain seven rotations')
                await_condition(lambda: all(rows(remote / legacy, name, True) for name, legacy in FORWARDED.items()),
                                processes, 'native forwarding did not deliver all four program labels')
                before = {name: rows(remote / legacy, name, True)[-1]['unclassified'] for name, legacy in FORWARDED.items()}
                child_file = Path(f'/proc/{manager.pid}/task/{manager.pid}/children')
                children = child_file.read_text().split()
                assert len(children) == 4
                identities = {pid: capture_identity(pid) for pid in children}
                assert all(identity and identity[0] == manager.pid for identity in identities.values())
                # Pause only Supervisor so its own rotation cannot race the
                # independent logrotate inode/hash comparison. Its pipes buffer
                # the tiny synthetic input until it is resumed below.
                os.kill(manager.pid, signal.SIGSTOP)
                paused = time.monotonic()
                try:
                    await_condition(lambda: Path(f'/proc/{manager.pid}/status').read_text().split('State:', 1)[1].lstrip().startswith('T'),
                                    processes, 'Supervisor did not pause', timeout=2)
                    def fingerprints():
                        return {str(path): (path.stat().st_ino, hashlib.sha256(path.read_bytes()).hexdigest())
                                for base in capture.values() for path in local.glob(base.name + '*')}
                    previous = fingerprints()
                    # Collector and local capture files share the same directory,
                    # as on a combined service/log-role installation. The actual
                    # callback's unrelated service restarts remain out of scope.
                    rotation = (ROOT / 'Docker/docassemble.logrotate').read_text()
                    rotation = rotation.replace('/usr/share/docassemble/log', str(local))
                    rotation = rotation.replace('/var/mail/mail', str(directory / 'absent-mail'))
                    rotation = rotation.replace('/usr/share/docassemble/webapp/restart-post-logrotate.sh', '/bin/true')
                    rotation_path = directory / 'logrotate.conf'
                    rotation_path.write_text(rotation)
                    subprocess.run(['logrotate', '--force', '--state', str(directory / 'logrotate.state'), str(rotation_path)],
                                   check=True, capture_output=True, timeout=3)
                    assert fingerprints() == previous, 'logrotate touched Supervisor-owned files'
                    assert all((local / (legacy + '.1')).stat().st_size for legacy in FORWARDED.values())
                    assert child_file.read_text().split() == children, 'rotation replaced a capture process'
                finally:
                    os.kill(manager.pid, signal.SIGCONT)
                assert time.monotonic() - paused < 4.5, 'fixture paused capture too long'
                # Explicitly reopen collector destinations. This exercises native
                # syslog reopening, not the unmodified production callback.
                os.kill(collector.pid, signal.SIGHUP)
                (directory / 'after-rotation').touch()
                def delivered_after_rotation():
                    for name, legacy in FORWARDED.items():
                        observed = rows(remote / legacy, name, True)
                        if not observed or observed[-1]['unclassified'] < before[name] + 8192:
                            return False
                    return True
                await_condition(delivered_after_rotation,
                                processes, 'forwarding stopped after independent log rotation', timeout=10)
                for observation in range(2):
                    assert all(process.poll() is None for process in processes), 'native daemon exited after forwarding'
                    assert {pid: capture_identity(pid) for pid in children} == identities, 'capture exited or was replaced after rotation'
                    if observation == 0:
                        time.sleep(0.2)
                stop(manager)
                assert manager.returncode == 0, 'Supervisor did not shut down cleanly'
                for name, base in capture.items():
                    files = list(local.glob(base.name + '*'))
                    assert len(files) == 8 and not Path(str(base) + '.8').exists()
                    observed = [row for path in files for row in rows(path, name, live=False)]
                    assert observed and max(row['unclassified'] for row in observed) >= before[name] + 8192
                print('Rotation acceptance: four Go streams retained seven Supervisor backups; legacy logrotate left capture files unchanged; all four syslog TCP routes continued with fixed counters', flush=True)
            except Exception:
                print((directory / 'console').read_text())
                raise
            finally:
                failures = []
                for process in reversed(processes):
                    try:
                        stop(process)
                    except Exception as error:
                        failures.append(error)
                if failures:
                    raise ExceptionGroup('native fixture cleanup failed', failures)


if __name__ == '__main__':
    main()
