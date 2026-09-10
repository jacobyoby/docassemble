"""GitHub-message XSS check for docassemble#38 (H-4).

Run inside the docassemble container venv, mirroring the other e2e
*_check.py scripts:
    docker exec da <venv-python> /tmp/github_message_check.py

Mirrors the develop/views.py message construction (Markup.format with
Markup-preserved accumulator, escaped dynamics) and proves
attacker-controlled API data cannot break out while legit messages
render byte-identical to the pre-fix layout.
"""
from markupsafe import Markup, escape


def github_link(url, text):
    return Markup('<a target="_blank" href="') + escape(url) + Markup('">') + escape(text) + Markup('</a>')


def published_message(html_url, author_name=None):
    msg = Markup("{} {}.").format('This package is', github_link(html_url, "published on GitHub"))
    if author_name:
        msg = Markup("{}  {} {}.").format(Markup(msg), "The author is", author_name)
    return Markup(msg)


def branch_message(html_url, branch, commit):
    branch_link = Markup('<a target="_blank" href="') + escape(html_url) + Markup('/tree/') + escape(branch) + Markup('">') + escape(branch) + Markup('</a>')
    commit_link = Markup('<a target="_blank" href="') + escape(html_url) + Markup('/commit/') + escape(commit) + Markup('"><code>') + escape(commit[0:7]) + Markup('</code></a>')
    addition = Markup('  ' + 'The current branch is %s and the current commit is %s.' % (branch_link, commit_link))
    return Markup("{}{}").format(Markup('Prior message.'), addition)


failures = []


def check(label, func):
    try:
        func()
    except Exception as err:
        failures.append(label)
        print("FAIL " + label + ": " + type(err).__name__ + " " + str(err)[:200])
    else:
        print("PASS " + label)


def author_name_script_escaped():
    out = published_message('https://github.com/u/p', '<script>alert(1)</script>')
    assert '<script>' not in out, out
    assert '&lt;script&gt;' in out, out


def href_breakout_escaped():
    out = published_message('https://github.com/u/p"><script>alert(1)</script><a href="')
    assert '"><script>' not in out, out
    assert '&#34;&gt;&lt;script&gt;' in out, out


def branch_name_markup_escaped():
    out = branch_message('https://github.com/u/p', '"><img src=x onerror=alert(1)>', 'abc123def456')
    assert '<img' not in out, out
    assert '&lt;img' in out, out


def legit_messages_intact():
    out = published_message('https://github.com/jacobyoby/docassemble-foo', 'Jane Doe')
    assert out == 'This package is <a target="_blank" href="https://github.com/jacobyoby/docassemble-foo">published on GitHub</a>.  The author is Jane Doe.', out
    out2 = branch_message('https://github.com/u/p', 'main', 'abc123def456')
    assert '>main</a>' in out2 and '<code>abc123d</code>' in out2, out2
    assert 'Prior message.  The current branch is' in out2, out2


check("author name script escaped", author_name_script_escaped)
check("href breakout escaped", href_breakout_escaped)
check("branch name markup escaped", branch_name_markup_escaped)
check("legit messages intact", legit_messages_intact)

if failures:
    raise SystemExit("github_message_check FAILED: " + ", ".join(failures))
print("github_message_check: all checks passed")
