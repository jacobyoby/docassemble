"""Subprocess-argv check for docassemble#46 (H-14).

Run inside the docassemble container venv after installing this branch's
listlog.py, mirroring the other e2e *_check.py scripts:
    docker cp docassemble_webapp/docassemble/webapp/listlog.py da:<site-packages>/docassemble/webapp/listlog.py
    docker exec da <venv-python> /tmp/subprocess_argv_check.py

Environment values must travel as single argv elements with no shell;
polling and error paths must match the old shell pipeline semantics.
"""
import os
import subprocess
from unittest import mock

import docassemble.webapp.listlog as listlog

CALLS = []


class FakeCompleted:
    def __init__(self, returncode, stdout=b''):
        self.returncode = returncode
        self.stdout = stdout


def fake_run(argv, **kwargs):
    assert isinstance(argv, list), argv
    assert kwargs.get('shell', False) is not True, argv
    CALLS.append(argv)
    return FakeCompleted(*fake_run.behavior.pop(0))


failures = []


def check(label, func):
    CALLS.clear()
    try:
        func()
    except Exception as err:
        failures.append(label)
        print("FAIL " + label + ": " + type(err).__name__ + " " + str(err)[:150])
    else:
        print("PASS " + label)


def hostile_env_flows_as_single_argv_elements():
    os.environ['DASUPERVISORUSERNAME'] = '$(touch /tmp/pwned)'
    os.environ['DASUPERVISORPASSWORD'] = 'a; rm -rf / #'
    try:
        fake_run.behavior = [(0, b''), (0, b'sync RUNNING pid 1')]
        with mock.patch.object(listlog.subprocess, 'run', fake_run):
            with mock.patch.object(listlog.os, 'listdir', return_value=['b.log', 'a.log']):
                with mock.patch.object(listlog.os.path, 'isfile', return_value=True):
                    assert listlog.list_log_files() == 'a.log\nb.log'
    finally:
        del os.environ['DASUPERVISORUSERNAME']
        del os.environ['DASUPERVISORPASSWORD']
    start_argv = CALLS[0]
    assert start_argv[0] == 'supervisorctl', start_argv
    assert '$(touch /tmp/pwned)' in start_argv, start_argv
    assert 'a; rm -rf / #' in start_argv, start_argv


def start_failure_returns_error():
    fake_run.behavior = [(1, b'')]
    with mock.patch.object(listlog.subprocess, 'run', fake_run):
        assert listlog.list_log_files() == "There was an error."
    assert len(CALLS) == 1, CALLS


def poll_loop_retries_until_running():
    fake_run.behavior = [(0, b''), (1, b''), (0, b'sync STOPPED'), (0, b'sync RUNNING pid 9')]
    with mock.patch.object(listlog.subprocess, 'run', fake_run):
        with mock.patch.object(listlog.time, 'sleep', return_value=None):
            with mock.patch.object(listlog.os, 'listdir', return_value=['x.log']):
                with mock.patch.object(listlog.os.path, 'isfile', return_value=True):
                    assert listlog.list_log_files() == 'x.log'
    assert len(CALLS) == 4, CALLS
    assert CALLS[1][-2:] == ['status', 'sync'], CALLS[1]


check("hostile env flows as single argv elements", hostile_env_flows_as_single_argv_elements)
check("start failure returns error", start_failure_returns_error)
check("poll loop retries until running", poll_loop_retries_until_running)

if failures:
    raise SystemExit("subprocess_argv_check FAILED: " + ", ".join(failures))
print("subprocess_argv_check: all checks passed")
