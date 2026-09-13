# Native configuration preflight

Status: integrated into the JOS-81 candidate's three native launchers; **not deployed**. The standard-library Go CLI at `/usr/share/docassemble/webapp/privacy-preflight` never prints configuration, paths, command output, exception details, or a success message. Exit `0` means accepted; every rejection or operational failure returns `70`.

```
privacy-preflight uwsgi CONFIG_PATH
privacy-preflight nginx
```

The dedicated Linux process disables core dumps and seals inherited descriptors beyond standard input/output/error. Other platforms reject invocation. The uWSGI command opens the path nonblocking, rejects nonregular files before reading, and reads at most 1 MiB plus one overflow byte. Its exact option-name allowlist comes from the four maintained `Docker/config/docassemble*.ini*` templates. It rejects duplicate options/sections, other sections/options, interpolation, unrendered placeholders, arbitrary modules/mount targets, and noncanonical values. `master = true`, `die-on-term = true`, and `log-format = PRIVACY_REQUEST status=%(status) msecs=%(msecs)` are mandatory. This deliberately does not accept the full uWSGI configuration language. The launcher separately clears `UWSGI_*` environment overrides and must use the checked file without an intervening mutation.

The nginx command executes only `/usr/sbin/nginx -T -e stderr`. Both output streams count toward a combined 1 MiB limit; only stdout is retained for parsing. Execution has a 10-second deadline and at most one additional second to finish readers. A nonzero exit, overflow, timeout, malformed dump, or unsupported syntax rejects startup. Captured output is never replayed. The child runs in a new session with Linux parent-death protection on a locked OS thread; set-id and file-capability executables are rejected. The subprocess group is killed on cancellation and after leader exit, including descendants that retain capture pipes.

The parser handles quoted strings, comments, braces, semicolons and `${variable}` tokens. It resolves the dump's file-header sections and include graph without reading another file, preserving each include's native context. Repeated includes in separate contexts and identical repeated file sections are supported. Missing exact includes, unreachable sections, conflicting repeated sections, include cycles, and ambiguous/unsupported syntax reject. Backslash escapes and partial quoted/unquoted token concatenation are intentionally unsupported. Include globs cannot cross directory boundaries. A `#` embedded in an unquoted token remains part of that token. The parser limits each file to 100,000 tokens and 63 nested blocks, and include expansion to 100,000 visited directives. Invalid UTF-8, disallowed control bytes, and input over 1 MiB reject before parsing.

Every explicit `access_log` must be `off` or `/dev/stdout privacy_counts`; no options or conditional logging are accepted. Every explicit `error_log` must be `stderr`, with at most one standard severity. Each context permits at most one of each. The main context requires `error_log stderr` and `worker_shutdown_timeout 2s`. Exactly one HTTP context must define the exact one-string format `PRIVACY_REQUEST status=$status seconds=$request_time` as `privacy_counts`, plus the `/dev/stdout privacy_counts` baseline. Local `access_log off` is permitted. Safe directives inside a server/location cannot supply missing global baselines.

Explicit `master_process` must be `on`; explicit `daemon` must be `off`, both only in the main context and without duplicates. These may be absent: the maintained launcher supplies `-g 'daemon off;'` and relies on nginx's normal master-process default. The validator does not alter launch arguments, log files, configuration, environment, or retention settings.

The check covers native access/error routing in the complete tested dump. It does not prove arbitrary third-party module code, Python output, historical logs, or downstream copies safe. No custom include is exempt from inspection; deployment must also prevent config/module changes between preflight and launch. Native `-T` remains a real executable/configuration test, not a side-effect-free parser. Its behavior and the actual launcher remain part of disposable-image acceptance.

The Dockerfile builds and installs the preflight, process runner, process monitor, and startup
diagnostic as static, root-owned executables with mode 0755. Only the nginx
lifecycle data file is copied from `Docker/privacy`. All four former native
Python helpers are frozen test references under `tests/privacy_native/reference`;
none is installed as a production helper.

## Verification and limits

Run the focused suite from the checkout root without installing the runtime or
setting `PYTHONPATH`:

```
bash tests/verify_privacy.sh
```

This checks all Go packages with formatting, vet, race tests, four bounded fuzz
targets, module verification, and host/Linux amd64/arm64 builds. It also runs 126
native/application-launcher tests and 84 frozen application draft tests, shell
syntax, and diff checks. On Linux the [application logger tests](application-logger-go.md)
also exercise 64 combinations through the actual Go capture process.
The frozen preflight reference is checked against SHA-256
`694f6a7bb916882234969544f994ba396efe16d2936631c94d5947762821f9ac`;
the Go decisions and 10,000 deterministic include-glob cases are compared with
that reference. The reference is evidence of preserved behavior, not independent
proof of native configuration correctness.

Linux tests exercise actual Go preflight and process capture through both uWSGI
launchers, including standard, exposed, and log profiles. Unsafe selected INI
files and missing helpers stop before native execution. Synthetic capture tests
cover successful output, nonzero exits, stream/combined overflow, timeouts, and
orphan cleanup. The fixture launcher tests retain their original exec-failure
expectations after replacing the former Python preflight stub. These tests use
synthetic activation, application configuration, and native programs.

A separate smoke check runs the compiled Go helper against real nginx `-T`:

```sh
bash tests/privacy_native/test_nginx_preflight_image.sh EXISTING_IMAGE
```

Supply a local Linux amd64/arm64 image containing `/usr/sbin/nginx`. The script
never pulls an image and starts only configuration inspection, with no public
listener. It mounts synthetic configuration and the compiled helper read-only
in a disposable container with no network, no capabilities, no-new-privileges,
and a temporary writable `/tmp`. Both fixtures must first pass native `-T`
inspection, so rejection cannot be attributed to a syntax or installation
failure. The Go helper must then return `0` for the safe include and `70` for an
unsafe access-log destination. Both helper paths must emit zero bytes.
These checks passed with the cached docassemble image's nginx 1.28.3. Full
Linux race tests, Linux vet, and a Linux-targeted `govulncheck@v1.7.0` scan also
passed; that scan found no Go vulnerabilities. The [integration record](preflight-integration-2026-09-05.md)
records evidence and the remaining release gates.

The validator itself remains silent. Its launcher now reports failed preflight
through the [bounded startup diagnostic](startup-diagnostics.md), with no raw
validator output. These checks do not boot uWSGI, Supervisor, or the complete
application, install into a persistent volume, or prove monitoring and rollback.
See the [release review](review-2026-09-05.md) for those open gates and the
[Go runner](native-runner-go.md) for the subsequent process-capture boundary.
