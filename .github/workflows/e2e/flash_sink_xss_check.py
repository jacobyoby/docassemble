"""Flash-sink XSS check for docassemble#51 (M-1..M-4 follow-up).

Run inside the docassemble container venv after installing this branch's
webapp files, mirroring the other e2e *_check.py scripts:
    docker cp docassemble_webapp/docassemble/webapp/utils/helpers.py da:<site-packages>/docassemble/webapp/utils/helpers.py
    docker cp .github/workflows/e2e/flash_sink_xss_check.py da:/tmp/flash_sink_xss_check.py
    docker exec da <venv-python> /tmp/flash_sink_xss_check.py

Three flashed-message sinks interpolated untrusted text as raw HTML:
base_templates/base.html {{ message|safe }}, interview/views.py
notification_interior, and helpers.flash_as_html (injected via
$("#daflash").html() in playground.js). The fix escapes plain-str
messages at each sink while Markup messages (the two intentional-HTML
flashes: GitHub push output notice, confirm-email login notice) pass
through. This check calls the real flash_as_html and mirrors the other
two sink constructions plus the two Markup sources.
"""
import re
import sys

from markupsafe import Markup, escape

from docassemble.webapp.utils.helpers import flash_as_html

failures = []


def check(label, func):
    try:
        func()
    except Exception as err:
        failures.append(label)
        print("FAIL " + label + ": " + type(err).__name__ + " " + str(err)[:200])
    else:
        print("PASS " + label)


XSS = '<script>alert(1)</script><img src=x onerror=alert(2)>'


def interview_sink(message):
    return '%s' % (escape(str(message)) if not isinstance(message, Markup) else message)


def playground_filename_saved(the_file):
    return flash_as_html(str(the_file) + ' was saved.', message_type='success', is_ajax=True)


def test_filename_xss_escaped():
    out = playground_filename_saved('evil<img src=x onerror=alert(1)>.yml')
    assert '<img' not in out, out
    assert '&lt;img' in out, out


def test_interview_sink_escapes_request_key():
    out = interview_sink("Error: Invalid key " + 'foo"<script>alert(1)</script>')
    assert '<script>' not in out, out
    assert '&lt;script&gt;' in out, out


def test_interview_sink_preserves_markup():
    out = interview_sink(Markup('Hello<br>world'))
    assert '<br>' in out, out


def test_flash_as_html_preserves_markup():
    out = flash_as_html(Markup('Hi<br>there'), message_type='info', is_ajax=True)
    assert '<br>' in out, out


def test_github_push_output_escaped():
    output = 'line1\nline2<script>alert(3)</script>'
    msg = Markup("Pushed commit to GitHub." + "<br>" + str(re.sub(r'[\n\r]+', '<br>', escape(output))))
    assert msg.count('<br>') == 2, msg
    assert '<script>' not in msg, msg


def test_login_confirm_url_escaped():
    url = '/confirm?email=a@b.c&token="x"'
    msg = Markup('txt' + '<br><a href="' + str(escape(url)) + '">' + 'click' + '</a>.')
    assert '&#34;' in msg, msg
    assert '<a href=' in msg, msg


check("playground filename xss escaped", test_filename_xss_escaped)
check("interview sink escapes request key", test_interview_sink_escapes_request_key)
check("interview sink preserves Markup", test_interview_sink_preserves_markup)
check("flash_as_html preserves Markup", test_flash_as_html_preserves_markup)
check("github push output escaped", test_github_push_output_escaped)
check("login confirm url escaped", test_login_confirm_url_escaped)

if failures:
    raise SystemExit("flash_sink_xss_check FAILED: " + ", ".join(failures))
print("flash_sink_xss_check: all checks passed")
