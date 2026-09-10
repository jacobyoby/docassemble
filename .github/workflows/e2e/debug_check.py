"""Debug-flag check for docassemble#53 (M-7).

Run inside the docassemble container venv after installing this branch's
parse.py (testrun.py is a dev-only entry script and is asserted statically;
it calls app.run() at import, so it is never imported here):
    docker cp docassemble_base/docassemble/base/parse.py da:<site-packages>/docassemble/base/parse.py
    docker cp .github/workflows/e2e/debug_check.py da:/tmp/debug_check.py
    docker exec da <venv-python> /tmp/debug_check.py [parse.py testrun.py]

parse.DEBUG is never True in shipped code, and the dev-only testrun server
enables the Werkzeug debugger only through DOCASSEMBLE_TESTRUN_DEBUG.
"""
import sys

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
parse_path = sys.argv[1] if len(sys.argv) > 1 else repo + "docassemble_base/docassemble/base/parse.py"
testrun_path = sys.argv[2] if len(sys.argv) > 2 else repo + "docassemble_webapp/docassemble/webapp/testrun.py"


def code_only(path):
    with open(path, encoding="utf-8") as handle:
        return "\n".join(line.split("#", 1)[0] for line in handle.read().splitlines())


def parse_no_debug_true():
    code = code_only(parse_path)
    assert "DEBUG = True" not in code, "DEBUG = True still present"


def testrun_no_hardcoded_debug():
    code = code_only(testrun_path)
    assert "debug=True" not in code, "hardcoded debug=True still present"
    assert "DOCASSEMBLE_TESTRUN_DEBUG" in code, "env gate missing"


def parse_debug_is_false_live():
    from docassemble.base.parse import DEBUG

    assert DEBUG is False, repr(DEBUG)


check("parse.py has no DEBUG = True", parse_no_debug_true)
check("testrun.py gates debugger behind env", testrun_no_hardcoded_debug)
check("imported parse.DEBUG is False", parse_debug_is_false_live)

if failures:
    raise SystemExit("FAILURES: " + ", ".join(failures))
print("ALL PASS")
