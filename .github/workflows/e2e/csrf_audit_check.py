"""CSRF-exemption audit check for docassemble#41 (H-9).

Run inside the docassemble container venv (no branch files need installing;
the invariant is structural, with the key-ambient property proven live):
    docker cp .github/workflows/e2e/csrf_audit_check.py da:/tmp/csrf_audit_check.py
    docker exec da <venv-python> /tmp/csrf_audit_check.py [webapp-dir]

Every @csrf.exempt in main/api.py, monitor/views.py, react/api.py,
users/api.py, and interview/api.py must sit on a handler gated by
`if not api_verify(` — API keys come from query/body/header only, never
cookies (non-ambient, so CSRF cannot present them) — except the two Twilio
voice webhooks in monitor/views.py, which cannot present CSRF tokens
(server-to-server) and check the posted AccountSid instead. Any new
exemption without one of those properties fails this check.
"""
import os
import re
import sys

from flask import Flask

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
webapp_dir = sys.argv[1] if len(sys.argv) > 1 else repo + "docassemble_webapp/docassemble/webapp/"

AUDITED = ["main/api.py", "monitor/views.py", "react/api.py", "users/api.py", "interview/api.py"]
WEBHOOK_EXCEPTIONS = {"digits_endpoint", "voice"}


def handlers_with_exemptions(path):
    src = open(path, encoding="utf-8").read()
    found = []
    for match in re.finditer(r"^@csrf\.exempt$", src, re.MULTILINE):
        rest = src[match.end():]
        func = re.search(r"^def (\w+)\(", rest, re.MULTILINE)
        assert func, "handler not found after exemption in " + path
        name = func.group(1)
        def_offset = match.end() + rest.index(func.group(0))
        body_start = def_offset + len(func.group(0))
        tail = src[body_start:]
        end = re.search(r"^(?:def |@\w+_bp\.route)", tail, re.MULTILINE)
        body = tail[: end.start() if end else len(tail)]
        found.append((name, body))
    return found


def gate_denies(body):
    gate_at = body.index("if not api_verify(")
    following = body[gate_at:].split("\n", 1)[1]
    return following.strip().startswith("return")


def exemptions_gated_or_documented():
    problems = []
    for rel in AUDITED:
        for name, body in handlers_with_exemptions(os.path.join(webapp_dir, rel)):
            if "if not api_verify(" in body and gate_denies(body):
                continue
            if name in WEBHOOK_EXCEPTIONS and "account sid" in body:
                continue
            problems.append(rel + "::" + name)
    assert not problems, "ungated exemptions: " + ", ".join(problems)


def dead_interview_endpoint_gone():
    with open(os.path.join(webapp_dir, "react/api.py"), encoding="utf-8") as handle:
        code = "\n".join(line.split("#", 1)[0] for line in handle.read().splitlines())
    assert "def api_interview" not in code, "dead exempt endpoint back"
    assert "csrf.exempt" not in code, "exemption remains in react/api.py"


def keys_never_from_cookies():
    with open(os.path.join(webapp_dir, "api/helpers.py"), encoding="utf-8") as handle:
        code = handle.read()
    start = code.index("def get_api_key():")
    end = code.index("\ndef ", start + 1)
    body = code[start:end]
    assert "request.cookies" not in body, "cookie key source in get_api_key"
    assert "cookies are deliberately NOT accepted" in body, "documented rationale missing"


def cookie_only_request_yields_no_key():
    saved = sys.argv
    sys.argv = saved[:1]
    try:
        from docassemble.webapp.api.helpers import get_api_key
    finally:
        sys.argv = saved
    app = Flask(__name__)
    # A cookie NAMED like a key must still yield nothing: cookies are ambient
    # credentials, so honoring them would CSRF-expose every exempt route.
    with app.test_request_context("/", headers={"Cookie": "X-API-Key=stolen-from-nowhere"}):
        assert get_api_key() is None


check("all exemptions gated or documented", exemptions_gated_or_documented)
check("dead react endpoint stays gone", dead_interview_endpoint_gone)
check("api keys never read from cookies", keys_never_from_cookies)
check("cookie-only request yields no key live", cookie_only_request_yields_no_key)

if failures:
    raise SystemExit("FAILURES: " + ", ".join(failures))
print("ALL PASS")
