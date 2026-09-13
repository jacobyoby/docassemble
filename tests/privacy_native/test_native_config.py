import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tests/privacy_native/reference/check_native_config.py"
SPEC = importlib.util.spec_from_file_location("check_native_config", SCRIPT)
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
UWSGI = ("[uwsgi]\nmaster = true\ndie-on-term = true\nlog-format = "
         + CHECK.UWSGI_FORMAT + "\n")
HTTP = ("log_format privacy_counts '" + CHECK.NGINX_FORMAT + "';\n"
        "access_log /dev/stdout privacy_counts;\n")
MAIN = "error_log stderr;\nworker_shutdown_timeout 2s;\nhttp {\n" + HTTP + "}\n"


def dump(*files):
    return "".join("# configuration file " + name + ":\n" + body.rstrip() + "\n"
                   for name, body in files).encode()


def single(body=MAIN):
    return dump(("/etc/nginx/nginx.conf", body))


class UwsgiValidation(unittest.TestCase):
    def reject(self, text):
        with self.assertRaises((CHECK.InvalidConfig, UnicodeError)):
            CHECK.validate_uwsgi(text.encode() if isinstance(text, str) else text)

    def test_required_positive_control(self):
        CHECK.validate_uwsgi(UWSGI.encode())

    def test_all_four_owned_templates_after_rendering(self):
        filenames = ("docassemble.ini.dist", "docassemble-expose-uwsgi.ini",
                     "docassemblelog.ini.dist", "docassemblelog-expose-uwsgi.ini")
        for filename in filenames:
            with self.subTest(template=filename):
                source = (ROOT / "Docker/config" / filename).read_text()
                for key, value in (("DA_ROOT", "/usr/share/docassemble"),
                                   ("DA_PYTHON", "/usr/share/docassemble/local3.14"),
                                   ("DAWSGIROOT", "/nj")):
                    source = source.replace("{{" + key + "}}", value)
                CHECK.validate_uwsgi(source.encode())

    def test_unrendered_templates_are_rejected(self):
        self.reject(UWSGI + "venv = {{DA_PYTHON}}\n")

    def test_unknown_override_and_privilege_options(self):
        for key in ("uid", "gid", "daemonize", "daemonize2", "logto", "logto2", "logger",
                    "req-logger", "include", "ini", "inherit", "exec-asap", "chdir"):
            with self.subTest(option=key):
                self.reject(UWSGI + key + " = SYNTHETIC_PRIVATE\n")

    def test_duplicates_sections_and_missing_required(self):
        for extra in ("master=true\n", "[uwsgi]\n", "[other]\nkey=value\n"):
            self.reject(UWSGI + extra)
        for line in UWSGI.splitlines():
            self.reject(UWSGI.replace(line + "\n", ""))

    def test_unsafe_values_and_interpolation(self):
        cases = ("master=false", "die-on-term=false", "processes=0", "threads=-1",
                 "threads=99999999", "venv=@(exec://echo secret)", "pidfile=/tmp/%(foo)",
                 "py-executable=$(BAD)", "venv=/tmp/../secret", "http-socket=:9000",
                 "module=arbitrary.application", "mount=/=arbitrary:app", "callable=other",
                 "log-format=" + CHECK.UWSGI_FORMAT + " %(uri)")
        for item in cases:
            with self.subTest(value=item):
                key = item.split("=", 1)[0]
                base = "\n".join(line for line in UWSGI.splitlines()
                                 if line.split("=", 1)[0].strip() != key) + "\n"
                self.reject(base + item + "\n")

    def test_comments_cannot_supply_required_values(self):
        self.reject(UWSGI.replace("master = true", "# master = true"))
        self.reject(UWSGI.replace("die-on-term = true", "; die-on-term = true"))
        self.reject(UWSGI.replace(CHECK.UWSGI_FORMAT, '"' + CHECK.UWSGI_FORMAT + '"'))

    def test_invalid_encoding_controls_and_limit(self):
        for data in (b"\xff", UWSGI.encode() + b"\x00", b"#" * (CHECK.MAX_BYTES + 1)):
            self.reject(data)


class NginxValidation(unittest.TestCase):
    def reject(self, data):
        with self.assertRaises((CHECK.InvalidConfig, UnicodeError)):
            CHECK.validate_nginx_dump(data)

    def test_positive_controls_levels_and_foreground(self):
        CHECK.validate_nginx_dump(single())
        for level in sorted(CHECK._LEVELS):
            CHECK.validate_nginx_dump(single(MAIN.replace("error_log stderr;", "error_log stderr " + level + ";")))
        CHECK.validate_nginx_dump(single("daemon off; master_process on;\n" + MAIN))

    def test_nested_off_and_quoted_data_not_directives(self):
        extra = ('server { access_log off; location / { error_log "stderr" warn; '
                 'return 200 "error_log /tmp/private; # } { access_log /tmp/private;"; }}')
        CHECK.validate_nginx_dump(single(MAIN.replace(HTTP, HTTP + extra)))
        CHECK.validate_nginx_dump(single(MAIN.replace(HTTP, HTTP + "server { if ($host != 'example.test') { return 301 /; } }")))

    def test_header_comment_inside_multiline_quote_is_data(self):
        extra = 'server { set $payload "first\n# configuration file /fake:\nlast"; }'
        CHECK.validate_nginx_dump(single(MAIN.replace(HTTP, HTTP + extra)))

    def test_complete_includes_relative_glob_and_repeated_contents(self):
        root = ("error_log stderr; include lifecycle.conf;\nhttp {\n" + HTTP
                + "include /etc/nginx/empty/*.conf;\n"
                "server { include shared.conf; } server { include shared.conf; } }")
        files = (("/etc/nginx/nginx.conf", root),
                 ("/etc/nginx/lifecycle.conf", "worker_shutdown_timeout 2s;"),
                 ("/etc/nginx/shared.conf", "access_log off; error_log stderr;"))
        CHECK.validate_nginx_dump(dump(*files, files[-1]))

    def test_unsafe_nested_quoted_and_conditional_overrides(self):
        overrides = ('access_log "/tmp/private" combined;', 'error_log "/tmp/private";',
                     'error_log syslog:server=127.0.0.1;', 'access_log /dev/stdout combined;',
                     'access_log /dev/stdout privacy_counts if=$foo;', 'access_log off extra;',
                     'error_log stderr debug extra;', 'error_log stderr unknown;')
        for override in overrides:
            with self.subTest(override=override):
                nested = "server { location /secret { " + override + " } }"
                self.reject(single(MAIN.replace(HTTP, HTTP + nested)))

    def test_comments_cannot_hide_bad_directives_or_supply_good_ones(self):
        self.reject(single(MAIN + "# access_log off;\nerror_log /tmp/private;\n"))
        self.reject(single(MAIN.replace("error_log stderr;", "# error_log stderr;")))
        self.reject(single(MAIN.replace("worker_shutdown_timeout 2s;", "# worker_shutdown_timeout 2s;")))
        # Inside an unquoted token, # belongs to the native filename.
        for name, safe in (("error_log", "stderr"), ("access_log", "off")):
            nested = "server { " + name + " " + safe + "#private\n; }"
            self.reject(single(MAIN.replace(HTTP, HTTP + nested)))

    def test_missing_global_baselines_cannot_be_satisfied_in_location(self):
        missing_access = MAIN.replace("access_log /dev/stdout privacy_counts;", "")
        missing_access = missing_access.replace(HTTP.splitlines()[0], HTTP.splitlines()[0]
                                               + "server { access_log /dev/stdout privacy_counts; }")
        self.reject(single(missing_access))
        self.reject(single(MAIN.replace("error_log stderr;", "").replace(HTTP, HTTP + "server { error_log stderr; }")))
        self.reject(single(MAIN.replace(HTTP.splitlines()[0], "")))
        self.reject(single(MAIN.replace("worker_shutdown_timeout 2s;", "")))

    def test_duplicate_directives_and_bad_lifecycle(self):
        for extra in ("error_log stderr;", "worker_shutdown_timeout 2s;", "daemon on;", "master_process off;"):
            self.reject(single(extra + MAIN))
        self.reject(single("daemon off; daemon off;" + MAIN))
        self.reject(single("master_process on; master_process on;" + MAIN))
        self.reject(single(MAIN.replace(HTTP, HTTP + HTTP)))
        self.reject(single(MAIN.replace("2s;", "2000ms;")))
        self.reject(single(MAIN.replace(HTTP, HTTP + "server { access_log off; access_log off; }")))

    def test_format_requires_exact_one_string(self):
        for value in (CHECK.NGINX_FORMAT + " $request_uri", "PRIVACY_REQUEST status=$status",
                      CHECK.NGINX_FORMAT.replace(" ", "  ")):
            self.reject(single(MAIN.replace(CHECK.NGINX_FORMAT, value)))
        self.reject(single(MAIN.replace("'" + CHECK.NGINX_FORMAT + "'", "escape=json '" + CHECK.NGINX_FORMAT + "'")))

    def test_malformed_and_unsupported_lexical_syntax(self):
        for suffix in ('"unterminated', "{", "}", "unknown", ";", "foo \\\n bar;", 'foo "escaped\\n";'):
            self.reject(single(MAIN + suffix))
        self.reject(single(MAIN).replace(b"stderr", b"std\x00err"))
        self.reject(b"\xff")
        self.reject(single(MAIN) + b" " * CHECK.MAX_BYTES)
        self.reject(MAIN.encode())

    def test_partial_quotes_cannot_turn_filenames_into_safe_tokens(self):
        for override in ('error_log std"err";', 'access_log o\'ff\';',
                         'error_log "stderr"private;', 'error_log "std""err";'):
            self.reject(single(MAIN.replace(HTTP, HTTP + "server {" + override + "}")))

    def test_include_completeness_cycles_and_conflicting_repeats(self):
        self.reject(single("include missing.conf;" + MAIN))
        self.reject(single("include $unknown;" + MAIN))
        self.reject(single("include nginx.conf;" + MAIN))
        self.reject(dump(("/etc/nginx/nginx.conf", MAIN), ("/etc/nginx/extra.conf", "error_log /tmp/private;")))
        self.reject(dump(("/etc/nginx/nginx.conf", MAIN), ("/etc/nginx/nginx.conf", MAIN + "error_log /tmp/private;")))

    def test_globs_do_not_cross_directory_boundaries(self):
        root = ("error_log stderr; worker_shutdown_timeout 2s; http {"
                "include /etc/nginx/conf.d/*.conf; server { include /etc/nginx/conf.d/nested/safe.conf; }}")
        # A wildcard must not promote this server-only baseline into HTTP scope.
        self.reject(dump(("/etc/nginx/nginx.conf", root),
                         ("/etc/nginx/conf.d/nested/safe.conf", HTTP)))


class SilentCli(unittest.TestCase):
    def test_uwsgi_exit_codes_and_absolute_silence(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "SYNTHETIC_PRIVATE.ini"
            for content, expected in ((UWSGI, 0), (UWSGI + "logto=/tmp/private\n", 70)):
                target.write_text(content)
                result = subprocess.run([sys.executable, str(SCRIPT), "uwsgi", str(target)],
                                        capture_output=True, timeout=5)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (expected, b"", b""))
            target.unlink()
            result = subprocess.run([sys.executable, str(SCRIPT), "uwsgi", str(target)], capture_output=True, timeout=5)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (70, b"", b""))

    def test_special_file_is_rejected_without_blocking(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "fifo"
            os.mkfifo(target)
            result = subprocess.run([sys.executable, str(SCRIPT), "uwsgi", str(target)], capture_output=True, timeout=5)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (70, b"", b""))

    def test_nginx_results_and_exceptions_remain_silent(self):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            with mock.patch.object(CHECK, "_nginx_dump", return_value=single()):
                self.assertEqual(CHECK.main(["nginx"]), 0)
            for failure in (RuntimeError("SYNTHETIC_PRIVATE"), TimeoutError("SYNTHETIC_PRIVATE")):
                with mock.patch.object(CHECK, "_nginx_dump", side_effect=failure):
                    self.assertEqual(CHECK.main(["nginx"]), 70)
            for args in ([], ["nginx", "extra"], ["uwsgi"], ["unknown"]):
                self.assertEqual(CHECK.main(args), 70)
        self.assertEqual((output.getvalue(), error.getvalue()), ("", ""))

    def test_fixed_native_command_and_capture_success(self):
        self.assertEqual(CHECK.NGINX_COMMAND, ("/usr/sbin/nginx", "-T", "-e", "stderr"))
        command = (sys.executable, "-c", "import sys;sys.stdout.buffer.write(" + repr(single())
                   + ");sys.stderr.write('SYNTHETIC_PRIVATE')")
        with mock.patch.object(CHECK, "NGINX_COMMAND", command):
            self.assertEqual(CHECK.main(["nginx"]), 0)

    def test_native_failure_timeout_and_combined_output_limit(self):
        snippets = ("import sys;sys.stderr.write('SYNTHETIC_PRIVATE');sys.exit(1)",
                    "import time;time.sleep(10)",
                    "import sys;sys.stderr.buffer.write(b'x' * 1048577)",
                    "import sys;sys.stdout.buffer.write(b'x' * 700000);sys.stderr.buffer.write(b'x' * 400000)")
        for snippet in snippets:
            with self.subTest(snippet=snippet), mock.patch.object(CHECK, "TIMEOUT_SECONDS", 0.2), \
                    mock.patch.object(CHECK, "NGINX_COMMAND", (sys.executable, "-c", snippet)):
                self.assertEqual(CHECK.main(["nginx"]), 70)


if __name__ == "__main__":
    unittest.main()
