"""Template-XSS check for docassemble#51 (M-2, M-4).

Run inside the docassemble container venv after installing this branch's
develop/views.py and utils/helpers.py, mirroring the other e2e *_check.py
scripts:
    docker cp docassemble_webapp/docassemble/webapp/develop/views.py da:<site-packages>/docassemble/webapp/develop/views.py
    docker cp docassemble_webapp/docassemble/webapp/utils/helpers.py da:<site-packages>/docassemble/webapp/utils/helpers.py
    docker cp .github/workflows/e2e/template_xss_check.py da:/tmp/template_xss_check.py
    docker exec da <venv-python> /tmp/template_xss_check.py

M-2 mirrors the #38 construction (Markup.format escapes plain-str args;
_github_link escapes URL and text), so the check mirrors that same
construction and proves payloads cannot break out, plus a static assertion
that views.py no longer string-concatenates pkgname/version/author into HTML.
M-4 calls the real summarize_results: pip log lines and result values must be
escaped while structural tags survive.

M-1 (author-controlled form labels, rich text by design) and M-3
(admin-config GLOBAL_CSS/GLOBAL_JS, custom code by design) are intentionally
unchanged; see the PR body for the triage rationale.
"""
import sys

from markupsafe import Markup, escape

from docassemble.webapp.utils.helpers import summarize_results

failures = []


def check(label, func):
    try:
        func()
    except Exception as err:
        failures.append(label)
        print("FAIL " + label + ": " + type(err).__name__ + " " + str(err)[:200])
    else:
        print("PASS " + label)


def pypi_link(url, text):
    return Markup('<a target="_blank" href="') + escape(url) + Markup('">') + escape(text) + Markup('</a>')


def pypi_message(pypi_url, pkgname, pypi_version, pypi_author=None, form_version=None):
    msg = Markup("{} {}.").format('This package is', pypi_link(pypi_url + '/' + pkgname + '/' + str(pypi_version), "published on PyPI"))
    if pypi_author:
        msg = Markup("{}  {} {}.").format(Markup(msg), "The author is", pypi_author)
    if pypi_version != form_version:
        msg = Markup("{}  {} {}.  {} {}.").format(Markup(msg), "The version on PyPI is", str(pypi_version), "Your version is", str(form_version))
    return Markup(msg)


def m2_href_breakout_escaped():
    out = pypi_message('https://pypi.org/pypi', 'docassemble.foo"><script>alert(1)</script>', '1.0', None, '1.0')
    assert '<script>' not in out, out
    assert '&#34;&gt;&lt;script&gt;' in out, out


def m2_author_script_escaped():
    out = pypi_message('https://pypi.org/pypi', 'docassemble.foo', '1.0', '<img src=x onerror=alert(1)>', '1.0')
    assert '<img' not in out, out
    assert '&lt;img' in out, out


def m2_legit_layout_preserved():
    out = pypi_message('https://pypi.org/pypi', 'docassemble.foo', '1.0', 'Jane', '1.0')
    assert out == 'This package is <a target="_blank" href="https://pypi.org/pypi/docassemble.foo/1.0">published on PyPI</a>.  The author is Jane.', out


def installed_views_path():
    import glob

    if len(sys.argv) > 1:
        return sys.argv[1]
    found = glob.glob("/usr/share/docassemble/local*/lib/python3*/site-packages/docassemble/webapp/develop/views.py")
    assert found, "installed develop/views.py not found"
    return found[0]


def m2_views_uses_markup():
    with open(installed_views_path(), encoding="utf-8") as handle:
        source = handle.read()
    block = source.split("pypi_version = pypi_info", 1)[1].split("if request.method == 'POST' and validated:", 1)[0]
    code = "\n".join(line.split("#", 1)[0] for line in block.splitlines())
    assert "'<a" not in code and '"<a' not in code, "raw anchor literal still built in pypi block"
    assert "+ pypi_author +" not in code, "raw author concat still present"
    assert "+ pypi_version +" not in code, "raw version concat still present"
    assert "_github_link(" in code, "escaped link helper not used"


def m4_pip_log_escaped():
    out = summarize_results({}, '<script>alert(1)</script>\nCollecting evil"><b>pkg</b>', html=True)
    text = str(out)
    assert '<script>' not in text, text
    assert '<b>pkg</b>' not in text, text
    assert '&lt;script&gt;' in text, text
    assert '<br>' in text, text


def m4_result_values_escaped():
    out = summarize_results({'okpkg': 'installed <img src=x onerror=alert(2)>'}, '', html=True)
    text = str(out)
    assert '<img' not in text, text
    assert ':&nbsp;' in text, text


def m4_structure_preserved():
    out = summarize_results({'a': 'b'}, 'line1\nline2', html=True)
    text = str(out)
    assert text == 'a:&nbsp;b<br><br><strong>pip log:</strong><br>line1<br>line2', text


def m4_plain_path_unchanged():
    out = summarize_results({'a': 'b'}, 'line1\nline2', html=False)
    assert out == 'a: b\npip log:\nline1\nline2', repr(out)


check("M-2 href breakout escaped", m2_href_breakout_escaped)
check("M-2 author script escaped", m2_author_script_escaped)
check("M-2 legit layout byte-identical", m2_legit_layout_preserved)
check("M-2 views.py uses escaped construction", m2_views_uses_markup)
check("M-4 pip log escaped, breaks kept", m4_pip_log_escaped)
check("M-4 result values escaped", m4_result_values_escaped)
check("M-4 structure byte-identical", m4_structure_preserved)
check("M-4 plain-text path unchanged", m4_plain_path_unchanged)

if failures:
    raise SystemExit("FAILURES: " + ", ".join(failures))
print("ALL PASS")
