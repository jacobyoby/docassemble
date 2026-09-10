"""Flash-path XSS check for docassemble#37 (H-3).

Run inside the docassemble container venv, mirroring the other e2e
*_check.py scripts:
    docker exec da <venv-python> /tmp/flash_xss_check.py

Proves request-path text flashed for the login/authorization redirects
renders escaped under the base template's {{ message|safe }} sink.
"""
from markupsafe import Markup


def render_unauthenticated(prefix, path):
    return Markup("{} {}").format(prefix, path)


failures = []


def check(label, func):
    try:
        func()
    except Exception as err:
        failures.append(label)
        print("FAIL " + label + ": " + type(err).__name__ + " " + str(err)[:130])
    else:
        print("PASS " + label)


def script_path_escaped():
    out = render_unauthenticated(
        "You need to log in before you can access",
        "/interview/<script>alert(1)</script>",
    )
    assert '<script>' not in out, out
    assert '&lt;script&gt;' in out, out


def breakout_path_escaped():
    out = render_unauthenticated(
        "You are not authorized to access",
        '/admin"><img src=x onerror=alert(1)>',
    )
    assert '<img' not in out, out


def plain_path_intact():
    out = render_unauthenticated("You need to log in before you can access", "/interview")
    assert out == "You need to log in before you can access /interview", out


check("script path escaped", script_path_escaped)
check("breakout path escaped", breakout_path_escaped)
check("plain path intact", plain_path_intact)

if failures:
    raise SystemExit("flash_xss_check FAILED: " + ", ".join(failures))
print("flash_xss_check: all checks passed")
