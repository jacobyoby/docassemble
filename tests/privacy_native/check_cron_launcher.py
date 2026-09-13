"""Terminate actual installed cron launchers in the disposable synthetic image."""
from http.cookies import SimpleCookie
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('install_check', Path(__file__).with_name('check_install_image.py'))
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


def active(pid):
    try:
        value = Path(f'/proc/{pid}/stat').read_text()
    except FileNotFoundError:
        return False
    return value.rsplit(')', 1)[1].split()[0] != 'Z'


def check_stop(sig, task, pid_file, outer=False):
    pid_file.write_text('')
    env = dict(os.environ, JOS81_CRON_PID_FILE=str(pid_file))
    args = ['bash', '/etc/cron.monthly/docassemble'] if outer else ['bash', install.ROOT + '/webapp/run-cron.sh', task]
    process = subprocess.Popen(args,
                               env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    children = []
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            assert process.poll() is None, 'cron launcher exited before the interview'
            try:
                children = json.loads(pid_file.read_text())
            except json.JSONDecodeError:
                time.sleep(0.1)
                continue
            break
        assert len(children) == 3 and all(type(pid) is int and pid > 1 for pid in children)
        assert len(set(children + [process.pid])) == 4
        ancestor = children[0]
        for unused in range(8):
            parent = int(Path(f'/proc/{ancestor}/stat').read_text().rsplit(')', 1)[1].split()[1])
            if parent == process.pid:
                break
            assert parent > 1 and parent not in children
            children.append(parent)
            ancestor = parent
        else:
            raise AssertionError('cron fixture did not descend from the tested launcher')
        assert all(active(pid) for pid in children), 'expected Go, Flask and descendant processes'
        # Signal only the entrypoint PID, not its process group or descendants.
        process.send_signal(sig)
        stdout, stderr = process.communicate(timeout=40 if outer else 30)
        assert process.returncode == 143 and not stderr, 'launcher did not preserve child termination status'
        lines = stdout.splitlines()
        if outer:
            assert len(lines) == 1 and install.records(lines[0], 'maintenance')[0]['unclassified'] >= 1
        else:
            assert len(lines) == 2, 'unexpected termination records'
            assert install.records(lines[0], 'cron')[0]['unclassified'] >= 2
            assert json.loads(lines[1]) == dict(schema=1, component='cron', event='command_failed', phase='execution')
        assert all(not active(pid) for pid in children), 'cron descendant survived launcher termination'
    finally:
        # Use the launcher cleanup even if readiness failed before PID publication.
        # The enclosing disposable-container trap is the final containment bound.
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=40 if outer else 25)
        except subprocess.TimeoutExpired:
            process.kill()
        finally:
            for pid in reversed(children):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.stdout.close()
            process.stderr.close()
            process.wait(timeout=5)


def main():
    source = (REPO / 'tests/privacy_native/fixtures/cron-stop.yml').read_text()
    assert source.count('JOS81_CRON_STOP_EVENT') == 1
    with tempfile.TemporaryDirectory(prefix='jos81-cron-stop-') as directory:
        base = Path(directory)
        pid_file = base / 'processes.json'
        pid_file.touch(mode=0o600)
        os.chown(base, 33, 33)
        os.chown(pid_file, 33, 33)
        for sig, task in ((signal.SIGTERM, 'cron_stop_term'), (signal.SIGINT, 'cron_stop_int'),
                          (signal.SIGTERM, 'cron_monthly')):
            # Distinct interviews avoid waiting for the killed session's lock TTL.
            target = Path(install.SITE + f'/docassemble/privacyfixture/data/questions/{task}.yml')
            target.write_text(source.replace('JOS81_CRON_STOP_EVENT', task))
            cookies = SimpleCookie()
            path = f'/nj/?i=docassemble.privacyfixture:data/questions/{task}.yml'
            assert b'JOS81_CRON_STOP_READY' in install.fetch(path, cookies=cookies)
            try:
                check_stop(sig, task, pid_file, outer=task == 'cron_monthly')
            finally:
                target.unlink()  # Prevent subsequent scheduled jobs entering this fixture.
    install.private_output_absent((Path(install.ROOT + '/log'), Path('/var/log')))
    print('inner TERM/INT and outer monthly TERM stop Go, Flask and descendants; only safe output remains', flush=True)


if __name__ == '__main__':
    main()
