"""Fail-closed unpickling gate for docassemble#32 (C-4).

Run inside the docassemble container venv after installing this branch's
fixpickle.py, mirroring the other e2e *_check.py scripts:
    docker cp docassemble_webapp/docassemble/webapp/utils/fixpickle.py da:<site-packages>/docassemble/webapp/utils/fixpickle.py
    docker exec da <venv-python> /tmp/pickle_hardening_check.py

Legit stored data (containers, datetimes, plain user classes) must keep
loading; classic RCE payloads must raise instead of executing.
"""
import datetime
import pickle
import sys

from docassemble.webapp.utils.fixpickle import fix_pickle_obj, fix_pickle_dict


failures = []


def check(label, func):
    try:
        func()
    except Exception as err:
        failures.append(label)
        print("FAIL " + label + ": " + type(err).__name__ + " " + str(err)[:120])
    else:
        print("PASS " + label)


class PlainWidget:
    def __init__(self, color):
        self.color = color


def legit_obj_roundtrip():
    obj = {
        '_internal': {'version': 1},
        'when': datetime.datetime(2026, 9, 10, 12, 0, 0),
        'items': [1, 'two', b'three', {4, 5}, (6,)],
        'widget': PlainWidget('red'),
    }
    raw = pickle.dumps(obj, protocol=2)
    back = fix_pickle_dict(raw)
    assert back['widget'].color == 'red', back
    assert back['items'][0] == 1, back
    assert isinstance(back['when'], datetime.datetime), back


def legit_obj_bytes_encoding():
    raw = pickle.dumps({'_internal': {}, 'name': 'jos'}, protocol=2)
    back = fix_pickle_obj(raw)
    assert back['name'] == 'jos', back


def malicious_os_system_blocked():
    payload = b"cos\nsystem\n(S'echo pwned'\ntR."
    try:
        fix_pickle_obj(payload)
    except Exception:
        return
    raise AssertionError("os.system payload unpickled without error")


def malicious_eval_blocked():
    payload = pickle.dumps(eval, protocol=2)
    try:
        fix_pickle_obj(payload)
    except Exception:
        return
    raise AssertionError("builtins.eval reference unpickled without error")


def malicious_subprocess_blocked():
    import subprocess
    payload = pickle.dumps(subprocess.Popen, protocol=2)
    try:
        fix_pickle_obj(payload)
    except Exception:
        return
    raise AssertionError("subprocess.Popen reference unpickled without error")


def malicious_getattr_chain_blocked():
    payload = pickle.dumps(getattr, protocol=2)
    try:
        fix_pickle_obj(payload)
    except Exception:
        return
    raise AssertionError("builtins.getattr reference unpickled without error")


check("legit object roundtrip loads", legit_obj_roundtrip)
check("legit bytes-encoding path loads", legit_obj_bytes_encoding)
check("os.system payload blocked", malicious_os_system_blocked)
check("builtins.eval reference blocked", malicious_eval_blocked)
check("subprocess.Popen reference blocked", malicious_subprocess_blocked)
check("builtins.getattr reference blocked", malicious_getattr_chain_blocked)

if failures:
    raise SystemExit("pickle_hardening_check FAILED: " + ", ".join(failures))
print("pickle_hardening_check: all checks passed")
