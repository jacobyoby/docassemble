"""File-API filename check for docassemble#59 (M-13).

Run inside the docassemble container venv after installing this branch's
files/api.py, mirroring the other e2e *_check.py scripts:
    docker cp docassemble_webapp/docassemble/webapp/files/api.py da:<site-packages>/docassemble/webapp/files/api.py
    docker cp .github/workflows/e2e/file_api_check.py da:/tmp/file_api_check.py
    docker exec da <venv-python> /tmp/file_api_check.py [<path-to-api.py>]

Both user-controlled selectors (?extension=, ?filename=) are sanitized, but
isfile() follows symlinks — so the resolved path must additionally stay
inside the upload's own directory. The route decorator also honors the
admin-configured CORS allowlist (#52 follow-through).
"""
import os
import sys
import tempfile

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
api_path = sys.argv[1] if len(sys.argv) > 1 else repo + "docassemble_webapp/docassemble/webapp/files/api.py"

with open(api_path, encoding="utf-8") as handle:
    api_source = "\n".join(line.split("#", 1)[0] for line in handle.read().splitlines())


def saved_argv():
    saved = sys.argv
    sys.argv = saved[:1]
    return saved


def confinement_wired():
    assert api_source.count("os.path.realpath") >= 3, "realpath confinement missing"
    assert "os.path.dirname(the_path) != base_dir" in api_source, "containment comparison missing"


def no_advocate_blanket():
    assert "'advocate'" not in api_source and "'trainer'" not in api_source, "role blanket remains"


def cors_wired():
    assert "origins='*'" not in api_source and 'origins="*"' not in api_source, "wildcard decorator remains"
    assert "daconfig.get('cross site domains', '*')" in api_source, "allowlist wiring missing"
    assert "origins=CORS_ORIGINS" in api_source, "decorator not wired"


def sanitizer_kills_separators():
    saved = saved_argv()
    try:
        from docassemble.webapp.utils.filenames import secure_filename_unicode_ok
    finally:
        sys.argv = saved
    for payload in ("../../etc/passwd", "..\\..\\secret", "/abs/path", "....//evil"):
        clean = secure_filename_unicode_ok(payload)
        assert "/" not in clean and "\\" not in clean, repr(clean)
        assert os.path.basename(clean) == clean, repr(clean)


def resolve_like_branch(base_dir, name):
    base = os.path.realpath(base_dir)
    the_path = os.path.realpath(os.path.join(base, name))
    if os.path.dirname(the_path) != base or not os.path.isfile(the_path):
        return None
    return the_path


def symlink_escape_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        outside = os.path.join(tmp, "outside.txt")
        with open(outside, "w", encoding="utf-8") as handle:
            handle.write("secret")
        sub = os.path.join(tmp, "sub")
        os.mkdir(sub)
        os.symlink(outside, os.path.join(sub, "link.txt"))
        legit = os.path.join(sub, "real.txt")
        with open(legit, "w", encoding="utf-8") as handle:
            handle.write("ok")
        assert resolve_like_branch(sub, "link.txt") is None, "symlink escape accepted"
        assert resolve_like_branch(sub, "real.txt") == os.path.realpath(legit), "legit file rejected"
        assert resolve_like_branch(sub, "") is None, "empty name accepted"
        assert resolve_like_branch(sub, "...") is None, "dot-only name accepted"


def api_module_imports():
    saved = saved_argv()
    try:
        import docassemble.webapp.files.api as api
    finally:
        sys.argv = saved
    assert hasattr(api, "api_file"), "handler missing"


check("realpath confinement wired in both branches", confinement_wired)
check("no advocate/trainer blanket bypass", no_advocate_blanket)
check("CORS decorator honors allowlist", cors_wired)
check("sanitizer kills separators live", sanitizer_kills_separators)
check("symlink escape rejected, legit served", symlink_escape_rejected)
check("api module imports", api_module_imports)

if failures:
    raise SystemExit("FAILURES: " + ", ".join(failures))
print("ALL PASS")
