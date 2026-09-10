"""Secure-cookie default check for docassemble#54 (M-8).

Run inside the docassemble container venv (setup.py needs a full app context,
so the wiring is asserted statically against the installed copy while the
resolution semantics and the resulting Set-Cookie behavior are proven live):
    docker cp docassemble_webapp/docassemble/webapp/setup.py da:<site-packages>/docassemble/webapp/setup.py
    docker cp .github/workflows/e2e/cookie_check.py da:/tmp/cookie_check.py
    docker exec da <venv-python> /tmp/cookie_check.py [<path-to-setup.py>]

Session cookies must be Secure by default; only a plain-HTTP deployment opts
out explicitly with `secure cookies: false`.
"""
import sys

from flask import Flask, session

failures = []


def check(label, func):
    try:
        func()
    except Exception as err:
        failures.append(label)
        print("FAIL " + label + ": " + type(err).__name__ + " " + str(err)[:200])
    else:
        print("PASS " + label)


repo = "/Users/jacobrakai/Projects/docassemble/"
setup_path = sys.argv[1] if len(sys.argv) > 1 else repo + "docassemble_webapp/docassemble/webapp/setup.py"

with open(setup_path, encoding="utf-8") as handle:
    setup_source = "\n".join(line.split("#", 1)[0] for line in handle.read().splitlines())


def resolve_secure(daconfig):
    # Mirrors the setup.py one-liner; the static test below pins them together.
    return daconfig.get('secure cookies', True)


def default_is_true():
    assert "daconfig.get('secure cookies', True)" in setup_source, "secure-by-default wiring missing"
    assert "or daconfig.get('behind https load balancer', False)" not in setup_source, "old opt-in expression remains"


def remember_follows_session():
    assert "app.config['REMEMBER_COOKIE_SECURE'] = app.config['SESSION_COOKIE_SECURE']" in setup_source, "remember-cookie linkage missing"


def resolution_matrix():
    assert resolve_secure({}) is True
    assert resolve_secure({'use https': True}) is True
    assert resolve_secure({'use https': False}) is True
    assert resolve_secure({'behind https load balancer': True}) is True
    assert resolve_secure({'secure cookies': False}) is False
    assert resolve_secure({'secure cookies': True}) is True


def cookie_carries_secure_flag(secure_value):
    app = Flask(__name__)
    app.secret_key = "check-secret"
    app.config["SESSION_COOKIE_SECURE"] = secure_value

    @app.route("/")
    def index():
        session["x"] = "y"
        return "ok"

    response = app.test_client().get("/")
    header = response.headers.get("Set-Cookie", "")
    assert "session=" in header, header
    return "Secure" in header


def secure_default_reaches_wire():
    assert cookie_carries_secure_flag(resolve_secure({})) is True


def explicit_opt_out_reaches_wire():
    assert cookie_carries_secure_flag(resolve_secure({'secure cookies': False})) is False


check("setup.py defaults Secure to True", default_is_true)
check("remember cookie follows session cookie", remember_follows_session)
check("resolution matrix", resolution_matrix)
check("default produces Secure Set-Cookie", secure_default_reaches_wire)
check("opt-out produces non-Secure Set-Cookie", explicit_opt_out_reaches_wire)

if failures:
    raise SystemExit("FAILURES: " + ", ".join(failures))
print("ALL PASS")
