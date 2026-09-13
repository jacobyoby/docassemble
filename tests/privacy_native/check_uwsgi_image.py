"""Real uWSGI + Go capture acceptance with synthetic configuration/application."""
import json
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import tempfile
import time

ROOT = Path('/review')
DA_ROOT = Path('/usr/share/docassemble')
RUNTIME = DA_ROOT / 'local3.14'
MARKER = b'SYNTHETIC_PRIVATE'
APP = '''import sys
def application(environ, start_response):
    print('SYNTHETIC_PRIVATE stdout ' + environ.get('QUERY_STRING', ''), flush=True)
    print('SYNTHETIC_PRIVATE stderr ' + environ.get('REMOTE_ADDR', ''), file=sys.stderr, flush=True)
    if environ['PATH_INFO'] == '/failure':
        raise RuntimeError('SYNTHETIC_PRIVATE exception synthetic.yml')
    status = {'/unavailable': '503 Service Unavailable', '/error-response': '500 Internal Server Error'}.get(environ['PATH_INFO'], '200 OK')
    start_response(status, [('Content-Type', 'text/plain')])
    return [b'synthetic-response']
app = application
'''


def request(endpoint, http, path, address):
    query = 'form=synthetic.yml&session=SYNTHETIC_PRIVATE'
    if http:
        data = (f'GET {path}?{query} HTTP/1.0\r\nHost: synthetic.invalid\r\n\r\n').encode()
    else:
        fields = {'REQUEST_METHOD': 'GET', 'SCRIPT_NAME': '', 'PATH_INFO': path,
                  'QUERY_STRING': query, 'REQUEST_URI': path + '?' + query,
                  'SERVER_NAME': 'synthetic.invalid', 'SERVER_PORT': '80',
                  'SERVER_PROTOCOL': 'HTTP/1.0', 'REMOTE_ADDR': address}
        payload = bytearray()
        for key, value in fields.items():
            key, value = key.encode(), value.encode()
            payload.extend(struct.pack('<H', len(key)) + key + struct.pack('<H', len(value)) + value)
        data = struct.pack('<BHB', 0, len(payload), 0) + payload
    deadline = time.monotonic() + 5
    while True:
        client = socket.socket(socket.AF_INET if http else socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(5)
        try:
            client.connect(endpoint)
            break
        except (ConnectionRefusedError, FileNotFoundError):
            client.close()
            if time.monotonic() >= deadline:
                raise AssertionError('real uWSGI did not open its configured socket')
            time.sleep(0.02)
    with client:
        client.sendall(data)
        response = bytearray()
        while chunk := client.recv(16384):
            response.extend(chunk)
            assert len(response) < 65536, 'unbounded synthetic response'
    return bytes(response)


def records(data):
    assert MARKER not in data and b'synthetic.yml' not in data, 'request/application content retained'
    result = [json.loads(line) for line in data.splitlines()]
    assert result, 'missing native counters'
    expected = {'schema', 'component', 'status_1xx', 'status_2xx', 'status_3xx', 'status_4xx',
                'status_5xx', 'latency_fast', 'latency_medium', 'latency_slow', 'latency_timeout',
                'unclassified', 'rejected', 'dropped'}
    for item in result:
        assert set(item) == expected, item
        assert item['schema'] == 1 and item['component'] == 'uwsgi', item
        for key, value in item.items():
            if key != 'component':
                assert type(value) is int and 0 <= value <= 2147483647, key
    return result[-1]


def process_state(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    except FileNotFoundError:
        return None
    return {'parent': int(fields[1]), 'group': int(fields[2]),
            'session': int(fields[3]), 'start': int(fields[19])}


def native_processes(process, log_role):
    pidfile = Path('/var/run/uwsgi/uwsgilog.pid' if log_role else '/var/run/uwsgi/uwsgi.pid')
    master = int(pidfile.read_text())
    state = process_state(master)
    assert state and state['parent'] == process.pid, 'native master is not the wrapper child'
    assert state['group'] == state['session'] == master, 'native session is not isolated'
    members = {}
    for path in Path('/proc').iterdir():
        if path.name.isdecimal():
            pid = int(path.name)
            state = process_state(pid)
            if state and state['group'] == master and state['session'] == master:
                members[pid] = state['start']
    assert master in members and len(members) >= 2, 'native master/worker pair not observed'
    return master, members


def remaining_processes(members):
    return [pid for pid, start in members.items()
            if (state := process_state(pid)) and state['start'] == start]


def await_native_exit(members):
    deadline = time.monotonic() + 2
    while remaining := remaining_processes(members):
        assert time.monotonic() < deadline, ('native processes survived wrapper exit', remaining)
        time.sleep(0.02)


def main():
    with tempfile.TemporaryDirectory(prefix='uwsgi-runtime-') as directory:
        modules = Path(directory) / 'modules'
        for package in ('docassemble', 'docassemble/base', 'docassemble/webapp'):
            target = modules / package
            target.mkdir(parents=True, exist_ok=True)
            (target / '__init__.py').write_text('')
        (modules / 'docassemble/base/read_config.py').write_text(
            'import sys\nprint("SYNTHETIC_PRIVATE bootstrap", file=sys.stderr)\n'
            'print(\'export LOCALE="C.UTF-8 UTF-8"\')\n')
        for module in ('run', 'listlog'):
            (modules / ('docassemble/webapp/' + module + '.py')).write_text(APP)
        config = DA_ROOT / 'config'
        for name in ('docassemble.ini.dist', 'docassemblelog.ini.dist',
                     'docassemble-expose-uwsgi.ini', 'docassemblelog-expose-uwsgi.ini'):
            text = (ROOT / 'Docker/config' / name).read_text()
            for key, value in {'DA_PYTHON': str(RUNTIME), 'DA_ROOT': str(DA_ROOT), 'DAWSGIROOT': '/'}.items():
                text = text.replace('{{' + key + '}}', value)
            (config / name.removesuffix('.dist')).write_text(text)
        for name, http, log_role in (('main', False, False), ('exposed', True, False),
                                     ('log', False, True), ('log-exposed', True, True)):
            env = dict(os.environ, PYTHONPATH=str(modules), PYTHONDONTWRITEBYTECODE='1',
                       DA_ROOT=str(DA_ROOT), DA_PYTHON=str(RUNTIME), DAWEBSERVER='none' if http else 'nginx')
            if name == 'log-exposed':
                ini = config / 'docassemblelog-expose-uwsgi.ini'
                preflight = subprocess.run([str(DA_ROOT / 'webapp/privacy-preflight'), 'uwsgi', str(ini)],
                                           capture_output=True, timeout=5)
                assert preflight.returncode == 0 and not preflight.stdout and not preflight.stderr
                command = [str(DA_ROOT / 'webapp/privacy-process'), '--component', 'uwsgi', '--',
                           str(RUNTIME / 'bin/uwsgi'), '--ini', str(ini), '--die-on-term']
            else:
                launcher = 'run-uwsgilog.sh' if log_role else 'run-uwsgi.sh'
                command = ['bash', str(ROOT / 'Docker' / launcher)]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            endpoint = ('127.0.0.1', 80) if http else '/var/run/uwsgi/docassemble' + ('log' if log_role else '') + '.sock'
            master, members = None, {}
            try:
                for path, address, expected in (('/', '203.0.113.7', b'200'),
                                                 ('/unavailable', '2001:db8::7', b'503'),
                                                 ('/error-response', '203.0.113.8', b'500'),
                                                 ('/failure', '203.0.113.9', None)):
                    response = request(endpoint, http, path, address)
                    if expected is None:
                        # Native control confirms uncaught WSGI exceptions close
                        # the connection without headers but increment status 500.
                        assert response == b'', (name, response)
                    else:
                        assert response.split(b'\r\n', 1)[0].split()[1] == expected, (name, response)
                master, members = native_processes(process, log_role)
                process.send_signal(signal.SIGTERM)
                out, err = process.communicate(timeout=8)
                assert process.returncode == 0 and err == b'', (name, process.returncode, out, err)
                await_native_exit(members)
                final = records(out)
                assert final['status_2xx'] == 1 and final['status_5xx'] == 3, (name, final)
                assert final['status_1xx'] == final['status_3xx'] == final['status_4xx'] == 0, (name, final)
                assert sum(final[key] for key in ('latency_fast', 'latency_medium',
                                                  'latency_slow', 'latency_timeout')) == 4, (name, final)
                assert final['unclassified'] >= 8, (name, final)
                print(f'uWSGI {name}: responses 200/503/500 and uncaught exception passed; safe status/latency counters; native master/workers exited', flush=True)
            finally:
                # Only signal the isolated group if one of the observed process
                # identities still belongs to it. The outer container deadline
                # also handles failures before a native PID could be observed.
                for pid in remaining_processes(members):
                    state = process_state(pid)
                    if state and state['start'] == members[pid] and state['group'] == master:
                        try:
                            os.killpg(master, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        break
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=8)
        # The actual launcher must reject a retained file logger before native startup.
        with (config / 'docassemble.ini').open('a') as stream:
            stream.write('\nlogto = /tmp/SYNTHETIC_PRIVATE.log\n')
        env['DAWEBSERVER'] = 'nginx'
        rejected = subprocess.run(['bash', str(ROOT / 'Docker/run-uwsgi.sh')], env=env,
                                  capture_output=True, timeout=5)
        assert rejected.returncode == 70 and rejected.stderr == b''
        assert json.loads(rejected.stdout) == {'schema': 1, 'component': 'uwsgi', 'event': 'startup_failed', 'phase': 'preflight'}
        assert not Path('/tmp/SYNTHETIC_PRIVATE.log').exists()
        print('uWSGI unsafe logger: rejected before native startup', flush=True)


if __name__ == '__main__':
    main()
