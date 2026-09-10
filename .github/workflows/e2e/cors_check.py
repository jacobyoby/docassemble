"""CORS allowlist check for docassemble#52 (M-5, M-6).

Run inside the docassemble container venv (no branch files need installing;
the check reads repo sources given as argv, defaulting to the installed
copies):
    docker cp .github/workflows/e2e/cors_check.py da:/tmp/cors_check.py
    docker exec da <venv-python> /tmp/cors_check.py [api.py views.py socketserver.py]

M-5: the 7 playground/Office `@cross_origin(origins='*')` decorators
overrode the global flask-cors allowlist from app_initialize.py. They must
now honor the admin-configured 'cross site domains', keeping '*' only as the
unconfigured fallback.
M-6: socketserver must never default to a wildcard: explicit allowlist, else
[url root], else None (engine.io same-origin enforcement).

Live sections prove the underlying mechanisms: engine.io rejects foreign
origins for an explicit list and for None while '*' lets them through, and
flask-cors emits restrictive ACAO headers for a configured allowlist.
"""
import sys

import engineio
from flask import Flask
from flask_cors import cross_origin

failures = []


def check(label, func):
    try:
        func()
    except Exception as err:
        failures.append(label)
        print("FAIL " + label + ": " + type(err).__name__ + " " + str(err)[:200])
    else:
        print("PASS " + label)


def source_of(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def code_only(source):
    return "\n".join(line.split("#", 1)[0] for line in source.splitlines())


repo = "/Users/jacobrakai/Projects/docassemble/"
api_path = sys.argv[1] if len(sys.argv) > 1 else repo + "docassemble_webapp/docassemble/webapp/develop/api.py"
views_path = sys.argv[2] if len(sys.argv) > 2 else repo + "docassemble_webapp/docassemble/webapp/develop/views.py"
sock_path = sys.argv[3] if len(sys.argv) > 3 else repo + "docassemble_webapp/docassemble/webapp/socketserver.py"


def m5_no_wildcard_literals():
    for path in (api_path, views_path):
        code = code_only(source_of(path))
        assert "origins='*'" not in code and 'origins="*"' not in code, "wildcard decorator in " + path


def m5_uses_config_allowlist():
    for path in (api_path, views_path):
        code = code_only(source_of(path))
        assert "cross site domains" in code, "allowlist config missing in " + path
        assert "origins=CORS_ORIGINS" in code, "decorators not wired to CORS_ORIGINS in " + path


def m6_no_wildcard_default():
    code = code_only(source_of(sock_path))
    assignments = [line.strip() for line in code.splitlines() if line.strip().startswith("origins =")]
    assert assignments, "origins assignments not found"
    for line in assignments:
        assert "'*'" not in line and '"*"' not in line, "wildcard default remains: " + line[:100]
    assert "origins = None" in assignments, "same-origin None fallback missing: " + repr(assignments)


def engineio_verdict(allowed, origin):
    server = engineio.Server(cors_allowed_origins=allowed)
    captured = {}

    def start_response(status, headers):
        captured["status"] = status

    environ = {
        "REQUEST_METHOD": "GET",
        "QUERY_STRING": "transport=polling",
        "HTTP_ORIGIN": origin,
        "HTTP_HOST": "good.example",
        "wsgi.url_scheme": "https",
    }
    body = b"".join(server.handle_request(environ, start_response))
    return captured.get("status", ""), body


def m6_engineio_rejects_foreign_for_list():
    status, body = engineio_verdict(["https://good.example"], "https://evil.example")
    assert status.startswith("400"), status
    assert b"Not an accepted origin" in body, body[:80]


def m6_engineio_rejects_foreign_for_none():
    status, body = engineio_verdict(None, "https://evil.example")
    assert status.startswith("400"), status
    assert b"Not an accepted origin" in body, body[:80]


def m6_engineio_allows_foreign_for_star():
    status, body = engineio_verdict("*", "https://evil.example")
    assert b"Not an accepted origin" not in body, body[:80]


def m5_flask_cors_allowlist_headers():
    app = Flask(__name__)

    @app.route("/locked")
    @cross_origin(origins=["https://good.example"], methods=["GET"], automatic_options=True)
    def locked():
        return "ok"

    client = app.test_client()
    foreign = client.get("/locked", headers={"Origin": "https://evil.example"})
    assert foreign.headers.get("Access-Control-Allow-Origin") in (None, "https://good.example"), foreign.headers.get("Access-Control-Allow-Origin")
    assert foreign.headers.get("Access-Control-Allow-Origin") != "*", "wildcard emitted for allowlisted route"
    allowed = client.get("/locked", headers={"Origin": "https://good.example"})
    assert allowed.headers.get("Access-Control-Allow-Origin") == "https://good.example", allowed.headers


check("M-5 no wildcard decorator literals", m5_no_wildcard_literals)
check("M-5 decorators wired to config allowlist", m5_uses_config_allowlist)
check("M-6 no wildcard default in socketserver", m6_no_wildcard_default)
check("M-6 engine.io rejects foreign origin for list", m6_engineio_rejects_foreign_for_list)
check("M-6 engine.io rejects foreign origin for None", m6_engineio_rejects_foreign_for_none)
check("M-6 engine.io lets foreign through for star", m6_engineio_allows_foreign_for_star)
check("M-5 flask-cors allowlist headers restrictive", m5_flask_cors_allowlist_headers)

if failures:
    raise SystemExit("FAILURES: " + ", ".join(failures))
print("ALL PASS")
