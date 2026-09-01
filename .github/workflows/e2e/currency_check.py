"""Fail-first check for the babel-backed currency_code path (issue #343).

Run inside the container with its venv python:
    currency_check.py expect-fail   stock code silently ignores currency_code
    currency_check.py expect-pass   patched code formats via babel
"""
import sys
import docassemble.base.config
docassemble.base.config.load(arguments=["t"])
from docassemble.base.thread_context import global_context, empty_globals

mode = sys.argv[1]
g = empty_globals()
g.language = "en"
with global_context(g):
    from docassemble.base.util import currency
    eur = currency(45.2, currency_code="EUR")
    if mode == "expect-fail":
        if "€" in eur:
            print("control FAILED: stock code already honors currency_code")
            sys.exit(1)
        print("control ok: stock code silently ignores currency_code (%r)" % eur)
    elif mode == "expect-pass":
        jpy = currency(1234.56, currency_code="JPY")
        de = currency(1234.56, currency_code="EUR", locale="de_DE")
        checks = [("€45.20", eur), ("¥1,235", jpy), ("1.234,56", de)]
        for expected, got in checks:
            if expected not in got:
                print("FAIL: expected %r in %r" % (expected, got))
                sys.exit(1)
        print("pass: EUR, JPY digits, and de_DE styling all correct")
    else:
        sys.exit(2)
