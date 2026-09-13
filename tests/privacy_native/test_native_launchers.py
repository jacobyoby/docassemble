import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = "SYNTHETIC_PRIVATE_BOOTSTRAP"


class NativeLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.diagnostic = ROOT / "tests/.privacy-build/privacy-diagnostic"
        if not cls.diagnostic.is_file():
            raise RuntimeError("Build the diagnostic first: bash tests/verify_privacy.sh")

    def fixture(self, directory, *, activation_failure=False):
        root = Path(directory)
        binary = root / "runtime/bin"
        binary.mkdir(parents=True)
        (root / "config").mkdir()
        (root / "webapp").mkdir()
        shutil.copy2(self.diagnostic, root / "webapp/privacy-diagnostic")
        (binary / "activate").write_text(
            "echo SYNTHETIC_PRIVATE_BOOTSTRAP >&2\n"
            + ("echo SYNTHETIC_PRIVATE_BOOTSTRAP\nreturn 1\n" if activation_failure else "true\n"))
        interpreter = binary / "python"
        interpreter.write_text("#!" + sys.executable + "\n" + r'''import json, os, sys
args = sys.argv[1:]
if args[0] == "-m":
    print('export LOCALE="' if os.environ.get("SYNTHETIC_CONFIG_EVAL_FAIL") else 'export LOCALE="C.UTF-8 UTF-8"')
    print('export DAHOSTNAME="synthetic.invalid"')
    print('export DAREADONLYFILESYSTEM="true"')
    print('export CONFIG_PRIVATE="SYNTHETIC_PRIVATE_BOOTSTRAP"')
    print('SYNTHETIC_PRIVATE_BOOTSTRAP', file=sys.stderr)
    raise SystemExit(1 if os.environ.get("SYNTHETIC_CONFIG_FAIL") else 0)
raise SystemExit(99)
''')
        interpreter.chmod(0o755)
        (root / "config/docassemble.ini").write_text("[synthetic]\n")
        (root / "config/docassemble-expose-uwsgi.ini").write_text("[synthetic]\n")
        (root / "config/docassemblelog.ini").write_text("[synthetic]\n")
        preflight = root / "webapp/privacy-preflight"
        preflight.write_text("#!" + sys.executable + "\n" + r'''import os, sys
args = sys.argv[1:]
if not (args == ["nginx"] or len(args) == 2 and args[0] == "uwsgi" and os.path.isfile(args[1])):
    raise SystemExit(98)
print('SYNTHETIC_PRIVATE_BOOTSTRAP')
print('SYNTHETIC_PRIVATE_BOOTSTRAP', file=sys.stderr)
if os.environ.get("SYNTHETIC_PREFLIGHT_FAIL"):
    raise SystemExit(70)
if os.environ.get("SYNTHETIC_LAUNCH_FAIL"):
    os.unlink(os.path.join(os.environ["DA_ROOT"], "webapp/privacy-process"))
raise SystemExit(0)
''')
        preflight.chmod(0o755)
        runner = root / "webapp/privacy-process"
        runner.write_text("#!" + sys.executable + "\n" + r'''import json, os, sys
try:
    os.fstat(3)
    extra_sink_closed = False
except OSError:
    extra_sink_closed = True
print(json.dumps({"argv":sys.argv[1:], "pid":os.getpid(),
    "extra_sink_closed":extra_sink_closed,
    "uwsgi_options_cleared":not any(key.startswith("UWSGI_") for key in os.environ),
    "temporary_exports_cleared":"DA_EXPORTS" not in os.environ}))
''')
        runner.chmod(0o755)
        (binary / "su").write_text('#!/bin/bash\nexec "$DA_PYTHON/bin/python" -m synthetic.read_config\n')
        (binary / "su").chmod(0o755)
        return root

    def run_launcher(self, name, root, **extra):
        env = dict(os.environ, DA_ROOT=str(root), DA_PYTHON=str(root / "runtime"),
                   UWSGI_LOGTO="SYNTHETIC_PRIVATE_BOOTSTRAP", UWSGI_DAEMONIZE="synthetic", **extra)
        env["PATH"] = str(root / "runtime/bin") + os.pathsep + os.environ["PATH"]
        child = subprocess.Popen(["bash", str(ROOT / "Docker" / name)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        stdout, stderr = child.communicate(timeout=5)
        return child, stdout, stderr

    def test_both_ini_choices_and_log_role_exec_protected_foreground(self):
        for name, mode, ini in (("run-uwsgi.sh", "nginx", "docassemble.ini"),
                                ("run-uwsgi.sh", "none", "docassemble-expose-uwsgi.ini"),
                                ("run-uwsgilog.sh", "nginx", "docassemblelog.ini")):
            with self.subTest(name=name, mode=mode), tempfile.TemporaryDirectory() as directory:
                root = self.fixture(directory)
                child, stdout, stderr = self.run_launcher(name, root, DAWEBSERVER=mode)
                self.assertEqual(child.returncode, 0)
                self.assertEqual(stderr, b"")
                self.assertNotIn(PRIVATE.encode(), stdout)
                record = json.loads(stdout)
                self.assertEqual(record["pid"], child.pid)
                self.assertTrue(record["uwsgi_options_cleared"])
                self.assertTrue(record["temporary_exports_cleared"])
                self.assertTrue(record["extra_sink_closed"])
                args = record["argv"]
                self.assertEqual(args[:3], ["--component", "uwsgi", "--"])
                self.assertEqual(args[3], str(root / "runtime/bin/uwsgi"))
                self.assertEqual(args[args.index("--ini")+1], str(root / "config" / ini))
                self.assertIn("--die-on-term", args)
                self.assertEqual(args[-1], "PRIVACY_REQUEST status=%(status) msecs=%(msecs)")

    def test_bootstrap_failures_report_only_fixed_stage_and_do_not_launch(self):
        for name in ("run-uwsgi.sh", "run-uwsgilog.sh"):
            for failure in ("activation", "config", "config_eval", "preflight", "launch"):
                with self.subTest(name=name, failure=failure), tempfile.TemporaryDirectory() as directory:
                    root = self.fixture(directory, activation_failure=failure=="activation")
                    extra = {} if failure == "activation" else {"SYNTHETIC_" + failure.upper() + "_FAIL": "1"}
                    child, stdout, stderr = self.run_launcher(name, root, **extra)
                    self.assertEqual(child.returncode, 70)
                    self.assertEqual(stderr, b"")
                    self.assertNotIn(PRIVATE.encode(), stdout)
                    self.assertLess(len(stdout), 256)
                    self.assertEqual(json.loads(stdout), {
                        "schema": 1,
                        "component": "uwsgilog" if name == "run-uwsgilog.sh" else "uwsgi",
                        "event": "startup_failed",
                        "phase": failure,
                    })

    def test_missing_diagnostic_is_distinct_unavailable_exit(self):
        for name in ("run-uwsgi.sh", "run-uwsgilog.sh", "run-nginx.sh"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = self.fixture(directory)
                (root / "webapp/privacy-diagnostic").unlink()
                child, stdout, stderr = self.run_launcher(name, root)
                self.assertEqual(child.returncode, 69)
                self.assertEqual(stdout + stderr, b"")

    def test_nginx_readonly_bootstrap_handoff_and_failure_codes(self):
        # The su/config/native boundaries are synthetic; readonly=true prevents
        # the real launcher from writing nginx or certificate paths on this host.
        for failure in (None, "config", "config_eval", "preflight", "launch"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = self.fixture(directory)
                extra = {} if failure is None else {"SYNTHETIC_" + failure.upper() + "_FAIL": "1"}
                child, stdout, stderr = self.run_launcher("run-nginx.sh", root, **extra)
                self.assertEqual(stderr, b"")
                self.assertNotIn(PRIVATE.encode(), stdout)
                record = json.loads(stdout)
                if failure is None:
                    self.assertEqual(child.returncode, 0)
                    self.assertEqual(record["pid"], child.pid)
                    self.assertTrue(record["extra_sink_closed"])
                    self.assertEqual(record["argv"][:3], ["--component", "nginx", "--"])
                else:
                    self.assertEqual(child.returncode, 70)
                    self.assertEqual(record, {"schema": 1, "component": "nginx",
                                             "event": "startup_failed", "phase": failure})

    def test_broken_output_pipe_stops_bootstrap_with_sink_failure(self):
        for name in ("run-uwsgi.sh", "run-uwsgilog.sh"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = self.fixture(directory, activation_failure=True)
                read_fd, write_fd = os.pipe()
                os.close(read_fd)
                try:
                    env = dict(os.environ, DA_ROOT=str(root), DA_PYTHON=str(root / "runtime"))
                    result = subprocess.run(["bash", str(ROOT / "Docker" / name)], env=env,
                                            stdout=write_fd, stderr=subprocess.PIPE, timeout=5)
                    self.assertEqual(result.returncode, 74)
                    self.assertEqual(result.stderr, b"")
                finally:
                    os.close(write_fd)

    def test_full_output_pipe_has_a_bounded_failure_deadline(self):
        for name in ("run-uwsgi.sh", "run-uwsgilog.sh"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = self.fixture(directory, activation_failure=True)
                read_fd, write_fd = os.pipe()
                try:
                    os.set_blocking(write_fd, False)
                    for chunk in (b"x" * 4096, b"x"):
                        while True:
                            try:
                                os.write(write_fd, chunk)
                            except BlockingIOError:
                                break
                    os.set_blocking(write_fd, True)
                    env = dict(os.environ, DA_ROOT=str(root), DA_PYTHON=str(root / "runtime"))
                    started = time.monotonic()
                    result = subprocess.run(["bash", str(ROOT / "Docker" / name)], env=env,
                                            stdout=write_fd, stderr=subprocess.PIPE, timeout=4)
                    elapsed = time.monotonic() - started
                    self.assertEqual(result.returncode, 74)
                    self.assertEqual(result.stderr, b"")
                    self.assertGreater(elapsed, 0.8)
                    self.assertLess(elapsed, 3)
                finally:
                    os.close(read_fd)
                    os.close(write_fd)


if __name__ == "__main__":
    unittest.main()
