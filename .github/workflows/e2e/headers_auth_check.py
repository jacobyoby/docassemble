"""Headers-endpoint auth check for docassemble#55 (M-9).

Run inside the docassemble container venv (users/views.py needs a full app
context, so the wiring is asserted statically against the installed copy
while the decorator-stack semantics are proven live on a minimal app):
    docker cp docassemble_webapp/docassemble/webapp/users/views.py da:<site-packages>/docassemble/webapp/users/views.py
    docker cp .github/workflows/e2e/headers_auth_check.py da:/tmp/headers_auth_check.py
    docker exec da <venv-python> /tmp/headers_auth_check.py [<path-to-users-views.py>]

/headers echoes request headers (Cookie, Authorization) and server
addressing: it must require authentication. login_required sits innermost
so the csrf exemption above keeps applying to the wrapped view.
"""
import sys

from flask import Flask, jsonify, request
from flask_login import LoginManager, login_required

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
views_path = sys.argv[1] if len(sys.argv) > 1 else repo + "docassemble_webapp/docassemble/webapp/users/views.py"

with open(views_path, encoding="utf-8") as handle:
    views_source = handle.read()


def show_headers_block():
    route_at = views_source.index("@users_bp.route('/headers'")
    func_at = views_source.index("def show_headers()", route_at)
    return views_source[route_at:func_at]


def endpoint_still_exists():
    assert "def show_headers():" in views_source, "endpoint removed instead of guarded"


def login_required_present():
    assert "@login_required" in show_headers_block(), "login_required missing on /headers"


def csrf_exempt_outermost():
    block = show_headers_block()
    assert block.index("@csrf.exempt") < block.index("@login_required"), "exempt must wrap the login_required view"


def stacked_app():
    app = Flask(__name__)
    app.secret_key = "check-secret"
    manager = LoginManager(app)

    @manager.user_loader
    def load_user(user_id):
        return None

    def exempt(view):
        view.csrf_exempt = True
        return view

    @app.route("/headers", methods=["POST", "GET"])
    @exempt
    @login_required
    def show_headers():
        return jsonify(headers=dict(request.headers))

    return app


def anonymous_denied():
    response = stacked_app().test_client().get("/headers")
    assert response.status_code in (401, 302, 403), response.status_code


def exempt_marker_survives_wrapping():
    view = stacked_app().view_functions["show_headers"]
    assert getattr(view, "csrf_exempt", False) is True, "csrf exemption lost through login_required wrapper"


check("/headers endpoint still exists", endpoint_still_exists)
check("/headers requires login", login_required_present)
check("csrf exemption stays outermost", csrf_exempt_outermost)
check("anonymous caller denied live", anonymous_denied)
check("exemption survives wrapper live", exempt_marker_survives_wrapping)

if failures:
    raise SystemExit("FAILURES: " + ", ".join(failures))
print("ALL PASS")
