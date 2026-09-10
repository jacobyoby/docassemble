"""SSH TOFU wrapper check for docassemble#48 (H-16).

Run inside the docassemble container venv after installing this branch's
develop/helpers.py, mirroring the other e2e *_check.py scripts:
    docker cp docassemble_webapp/docassemble/webapp/develop/helpers.py da:<site-packages>/docassemble/webapp/develop/helpers.py
    docker exec da <venv-python> /tmp/ssh_tofu_check.py

The generated GIT_SSH wrapper must pin host keys (accept-new with a
persistent known_hosts file), never blindly accept them.
"""
import os
import stat
import subprocess
import tempfile

from docassemble.webapp.develop.helpers import write_git_ssh_script

failures = []


def check(label, func):
    try:
        func()
    except Exception as err:
        failures.append(label)
        print("FAIL " + label + ": " + type(err).__name__ + " " + str(err)[:150])
    else:
        print("PASS " + label)


def wrapper_pins_host_keys():
    keydir = tempfile.mkdtemp(prefix='sshtofu')
    keyfile = os.path.join(keydir, '.ssh-private')
    with open(keyfile, 'w', encoding='utf-8'):
        pass
    script = write_git_ssh_script(keyfile)
    try:
        with open(script, encoding='utf-8') as fp:
            content = fp.read()
        assert 'StrictHostKeyChecking=accept-new' in content, content
        assert 'StrictHostKeyChecking=no' not in content, content
        assert '/dev/null' not in content, content
        assert os.path.join(keydir, '.ssh-known-hosts') in content, content
        info = os.stat(os.path.join(keydir, '.ssh-known-hosts'))
        assert info.st_mode & 0o777 == 0o600, oct(info.st_mode)
        assert os.stat(script).st_mode & 0o111, "wrapper not executable"
    finally:
        os.unlink(script)


def known_hosts_persists_across_wrappers():
    keydir = tempfile.mkdtemp(prefix='sshtofu')
    keyfile = os.path.join(keydir, '.ssh-private')
    with open(keyfile, 'w', encoding='utf-8'):
        pass
    first = write_git_ssh_script(keyfile)
    try:
        known = os.path.join(keydir, '.ssh-known-hosts')
        with open(known, 'w', encoding='utf-8') as fp:
            fp.write('github.com ssh-ed25519 AAAAPINNEDKEY\n')
        second = write_git_ssh_script(keyfile)
        try:
            with open(known, encoding='utf-8') as fp:
                assert 'AAAAPINNEDKEY' in fp.read(), "pinned key lost"
        finally:
            os.unlink(second)
    finally:
        os.unlink(first)


def ssh_binary_accepts_options():
    keydir = tempfile.mkdtemp(prefix='sshtofu')
    keyfile = os.path.join(keydir, '.ssh-private')
    with open(keyfile, 'w', encoding='utf-8'):
        pass
    script = write_git_ssh_script(keyfile)
    try:
        out = subprocess.run(
            ['bash', script, '-G', 'github.com'],
            capture_output=True, text=True, check=False,
        )
        combined = out.stdout + out.stderr
        assert 'accept-new' in combined or 'stricthostkeychecking accept-new' in combined, combined[:300]
    finally:
        os.unlink(script)


check("wrapper pins host keys", wrapper_pins_host_keys)
check("known hosts persists across wrappers", known_hosts_persists_across_wrappers)
check("ssh binary accepts options", ssh_binary_accepts_options)

if failures:
    raise SystemExit("ssh_tofu_check FAILED: " + ", ".join(failures))
print("ssh_tofu_check: all checks passed")
