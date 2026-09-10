"""File role-scope check for docassemble#57 (M-11).

Run inside the docassemble container venv (the file-access functions need a
live DB, so the narrowing is asserted statically against the installed
copies while the edited modules must still import cleanly):
    docker cp docassemble_webapp/docassemble/webapp/files/common.py da:<site-packages>/docassemble/webapp/files/common.py
    docker cp docassemble_webapp/docassemble/webapp/files/file_access.py da:<site-packages>/docassemble/webapp/files/file_access.py
    docker cp docassemble_webapp/docassemble/webapp/files/helpers.py da:<site-packages>/docassemble/webapp/files/helpers.py
    docker cp .github/workflows/e2e/file_access_check.py da:/tmp/file_access_check.py
    docker exec da <venv-python> /tmp/file_access_check.py [common.py file_access.py helpers.py]

Advocates and trainers must not bypass per-file checks: they reach files
only through granular grants (own session keys, UploadsUserAuth,
UploadsRoleAuth). Admin/developer bypasses are unchanged.
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
base = repo + "docassemble_webapp/docassemble/webapp/files/"
common_path = sys.argv[1] if len(sys.argv) > 1 else base + "common.py"
access_path = sys.argv[2] if len(sys.argv) > 2 else base + "file_access.py"
helpers_path = sys.argv[3] if len(sys.argv) > 3 else base + "helpers.py"


def code_only(path):
    with open(path, encoding="utf-8") as handle:
        return "\n".join(line.split("#", 1)[0] for line in handle.read().splitlines())


def common_narrowed():
    code = code_only(common_path)
    assert "'advocate'" not in code and "'trainer'" not in code, "advocate/trainer still bypass in common.py"
    assert "has_role('admin', 'developer')" in code, "admin/developer bypass missing in common.py"
    assert "UploadsRoleAuth" in code, "granular role-grant path missing in common.py"


def file_access_narrowed():
    code = code_only(access_path)
    assert "'advocate'" not in code and "'trainer'" not in code, "advocate/trainer still bypass in file_access.py"
    assert "has_role('admin', 'developer')" in code, "admin/developer bypass missing in file_access.py"


def helpers_serve_paths_narrowed():
    code = code_only(helpers_path)
    assert "has_role('admin', 'advocate')" not in code, "advocate serve bypass remains in helpers.py"
    assert code.count("has_role('admin')") >= 4, "expected narrowed serve flags"


def edited_modules_import():
    # NB: daconfig load parses sys.argv for config-file arguments, so scrub
    # our file-path argv before importing the modules.
    saved = sys.argv
    sys.argv = saved[:1]
    try:
        import docassemble.webapp.files.common as common
        import docassemble.webapp.files.file_access as access
        import docassemble.webapp.files.helpers as helpers
    finally:
        sys.argv = saved
    assert hasattr(common, "can_access_file_number")
    assert hasattr(access, "get_info_from_file_number")
    assert hasattr(helpers, "do_serve_stored_file")


check("common.py bypass narrowed to admin/developer", common_narrowed)
check("file_access.py bypass narrowed to admin/developer", file_access_narrowed)
check("helpers.py serve bypasses narrowed to admin", helpers_serve_paths_narrowed)
check("edited modules still import", edited_modules_import)

if failures:
    raise SystemExit("FAILURES: " + ", ".join(failures))
print("ALL PASS")
