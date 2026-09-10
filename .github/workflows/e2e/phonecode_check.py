"""Phone-code-in-URL check for docassemble#56 (M-10).

Run inside the docassemble container venv after installing this branch's
phonelogin/views.py, mirroring the other e2e *_check.py scripts:
    docker cp docassemble_webapp/docassemble/webapp/phonelogin/views.py da:<site-packages>/docassemble/webapp/phonelogin/views.py
    docker cp .github/workflows/e2e/phonecode_check.py da:/tmp/phonecode_check.py
    docker exec da <venv-python> /tmp/phonecode_check.py [<path-to-views.py>]

Verification codes must never travel in URLs (history, referers, access
logs): no magic link is texted, and /pv accepts the code only from the
POSTed form body with the phone number from the server session.
"""
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
views_path = sys.argv[1] if len(sys.argv) > 1 else repo + "docassemble_webapp/docassemble/webapp/phonelogin/views.py"

with open(views_path, encoding="utf-8") as handle:
    views_source = "\n".join(line.split("#", 1)[0] for line in handle.read().splitlines())


def no_code_in_url():
    assert "request.args.get('c'" not in views_source, "code still read from URL"
    assert "'c' in request.args" not in views_source, "code branch still present"
    assert "c=verification_code" not in views_source, "magic link still built"


def phone_from_session_only():
    assert "session.get('phone_number'" in views_source, "session lookup missing"
    assert "request.args.get('p'" not in views_source, "phone still read from URL"


def no_mobile_link_machinery():
    assert "detect_mobile" not in views_source, "dead link-branch machinery remains"


def import_views():
    # NB: daconfig load parses sys.argv for config-file arguments, so scrub
    # our file-path argv before importing the views module.
    saved = sys.argv
    sys.argv = saved[:1]
    try:
        import docassemble.webapp.phonelogin.views as views
    finally:
        sys.argv = saved
    return views


def patched_module_imports():
    views = import_views()
    assert hasattr(views, "phone_login_verify"), "verify handler missing"


def magic_link_get_is_dead():
    views = import_views()
    app = Flask(__name__)
    app.secret_key = "check-secret"
    app.config["USE_PHONE_LOGIN"] = True
    app.register_blueprint(views.phonelogin_bp)
    response = app.test_client().get("/pv?p=%2B15551234567&c=123456")
    assert response.status_code == 404, response.status_code


check("no verification code in URLs", no_code_in_url)
check("phone number from session only", phone_from_session_only)
check("no dead magic-link machinery", no_mobile_link_machinery)
check("patched views module imports", patched_module_imports)
check("magic-link GET no longer authenticates", magic_link_get_is_dead)

if failures:
    raise SystemExit("FAILURES: " + ", ".join(failures))
print("ALL PASS")
