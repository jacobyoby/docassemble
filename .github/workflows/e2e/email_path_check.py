"""Email-path validation check for docassemble#60 (M-14).

Run inside the docassemble container venv after installing this branch's
process_email.py (now import-safe behind an __main__ guard), mirroring the
other e2e *_check.py scripts:
    docker cp docassemble_webapp/docassemble/webapp/process_email.py da:<site-packages>/docassemble/webapp/process_email.py
    docker cp .github/workflows/e2e/email_path_check.py da:/tmp/email_path_check.py
    docker exec da <venv-python> /tmp/email_path_check.py [<path-to-process_email.py>]

process_email reads its input file from sys.argv[1]. The sole in-repo
invoker (Docker/process-email.sh) always passes a mktemp file, so the path
must resolve to a regular file directly inside the system temp directory.
"""
import io
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
script_path = sys.argv[1] if len(sys.argv) > 1 else repo + "docassemble_webapp/docassemble/webapp/process_email.py"

with open(script_path, encoding="utf-8") as handle:
    script_source = "\n".join(line.split("#", 1)[0] for line in handle.read().splitlines())


SCRIPT = {"mod": None}


def import_script():
    # NB: importing must NOT run main(). On unfixed code the import itself
    # executes main() and raises SystemExit — convert that into a plain
    # assertion failure so the report stays honest instead of dying mid-run
    # (or mistaking the import-time exit for an expected validation exit).
    if SCRIPT["mod"] is None:
        saved = sys.argv
        sys.argv = saved[:1]
        try:
            try:
                import docassemble.webapp.process_email as script
            except SystemExit as err:
                raise AssertionError("import runs main(): " + str(err.code))
        finally:
            sys.argv = saved
        assert hasattr(script, "validated_email_path"), "validator missing from module"
        SCRIPT["mod"] = script
    return SCRIPT["mod"]


def no_raw_argv_open():
    assert "open(sys.argv[1]" not in script_source, "unvalidated argv path still opened"
    assert "validated_email_path" in script_source, "validator missing"
    assert "tempfile.gettempdir()" in script_source, "temp-dir restriction missing"
    assert 'if __name__ == "__main__":' in script_source, "import guard missing"


def _expect_exit(argv):
    fp = io.StringIO()
    try:
        import_script().validated_email_path(argv, fp)
    except SystemExit as err:
        assert err.code != 0, "exit code must be nonzero"
        return fp.getvalue()
    raise AssertionError("expected SystemExit for " + repr(argv))


def missing_argument_rejected():
    _expect_exit(["process_email.py"])
    _expect_exit(["process_email.py", ""])


def outside_temp_rejected():
    _expect_exit(["process_email.py", "/etc/passwd"])
    _expect_exit(["process_email.py", "/tmp/../etc/passwd"])


def symlink_escape_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        outside = os.path.join(tmp, "outside.eml")
        with open(outside, "w", encoding="utf-8") as handle:
            handle.write("From: x@y\n\nbody")
        link = os.path.join(tempfile.gettempdir(), "email_link_check.eml")
        if os.path.islink(link) or os.path.exists(link):
            os.remove(link)
        os.symlink(outside, link)
        try:
            _expect_exit(["process_email.py", link])
        finally:
            os.remove(link)


def non_files_rejected():
    _expect_exit(["process_email.py", tempfile.gettempdir()])
    _expect_exit(["process_email.py", "/dev/null"])


def legit_tmp_file_accepted():
    fd, path = tempfile.mkstemp(suffix=".eml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("From: x@y\n\nbody")
        resolved = import_script().validated_email_path(["process_email.py", path], io.StringIO())
        assert resolved == os.path.realpath(path), resolved
    finally:
        os.remove(path)


def module_imports_without_side_effects():
    import_script()


check("no raw argv path opened", no_raw_argv_open)
check("module imports without side effects", module_imports_without_side_effects)
check("missing argument rejected", missing_argument_rejected)
check("outside-temp paths rejected", outside_temp_rejected)
check("symlink escape rejected", symlink_escape_rejected)
check("directories and devices rejected", non_files_rejected)
check("legit temp file accepted", legit_tmp_file_accepted)

if failures:
    raise SystemExit("FAILURES: " + ", ".join(failures))
print("ALL PASS")
