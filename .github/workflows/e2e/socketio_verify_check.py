"""SocketIO verify check for docassemble#49 (H-17).

Run inside the docassemble container venv after installing this branch's
socketserver.py, mirroring the other e2e *_check.py scripts:
    docker cp docassemble_webapp/docassemble/webapp/socketserver.py da:<site-packages>/docassemble/webapp/socketserver.py
    docker cp .github/workflows/e2e/socketio_verify_check.py da:/tmp/socketio_verify_check.py
    docker exec da <venv-python> /tmp/socketio_verify_check.py [<path-to-socketserver.py>]

Guards two properties:
1. The socketio.init_app call carries no `verify=False` flag (removed as a
   misleading dead kwarg in #49).
2. The premise documents itself: python-socketio's Server silently swallows an
   unknown `verify` kwarg, so the flag never controlled any certificate check.
   This process is purely a server and makes no outbound TLS connections.
"""
import re
import sys

import socketio

failures = []


def check(label, func):
    try:
        func()
    except Exception as err:
        failures.append(label)
        print("FAIL " + label + ": " + type(err).__name__ + " " + str(err)[:150])
    else:
        print("PASS " + label)


def installed_source_path():
    import docassemble.webapp.socketserver as mod

    return mod.__file__


source_path = sys.argv[1] if len(sys.argv) > 1 else installed_source_path()
with open(source_path, encoding="utf-8") as handle:
    source = handle.read()


def no_verify_flag():
    calls = re.findall(r"socketio\.init_app\((.*?)\)", source, re.DOTALL)
    assert calls, "socketio.init_app call not found"
    for call in calls:
        assert "verify" not in call, "verify kwarg still present: " + call[:120]


def verify_kwarg_is_ignored():
    server = socketio.Server(verify=False)
    assert "verify" not in vars(server.eio), "verify leaked into engineio state"


def default_server_constructs():
    assert socketio.Server() is not None


check("init_app carries no verify flag", no_verify_flag)
check("verify kwarg swallowed by Server", verify_kwarg_is_ignored)
check("default Server constructs", default_server_constructs)

if failures:
    raise SystemExit("FAILURES: " + ", ".join(failures))
print("ALL PASS")
