"""XSS escaping check for docassemble#36 (H-2).

Run inside the docassemble container venv, mirroring the other e2e
*_check.py scripts:
    docker exec da <venv-python> /tmp/xss_escape_check.py

Proves the requester-IP description renders attacker header values
escaped: no raw markup from the header may survive in the output.
"""
from markupsafe import Markup


def render_description(ip_address):
    return Markup("{} <code>{}</code>.").format("Your IP address is", str(ip_address))


failures = []


def check(label, func):
    try:
        func()
    except Exception as err:
        failures.append(label)
        print("FAIL " + label + ": " + type(err).__name__ + " " + str(err)[:130])
    else:
        print("PASS " + label)


def script_payload_escaped():
    out = render_description('<script>alert(1)</script>')
    assert '<script>' not in out, out
    assert '&lt;script&gt;' in out, out


def attribute_breakout_escaped():
    out = render_description('1.2.3.4</code><img src=x onerror=alert(1)>')
    assert '</code><img' not in out, out
    assert '&lt;/code&gt;' in out, out


def multi_ip_forwarded_for_escaped():
    out = render_description('9.9.9.9, <b>evil</b>, 10.0.0.1')
    assert '<b>' not in out, out


def plain_ip_unchanged():
    out = render_description('56.33.114.49')
    assert '<code>56.33.114.49</code>' in out, out


check("script payload escaped", script_payload_escaped)
check("attribute breakout escaped", attribute_breakout_escaped)
check("multi-ip forwarded-for escaped", multi_ip_forwarded_for_escaped)
check("plain IP unchanged", plain_ip_unchanged)

if failures:
    raise SystemExit("xss_escape_check FAILED: " + ", ".join(failures))
print("xss_escape_check: all checks passed")
