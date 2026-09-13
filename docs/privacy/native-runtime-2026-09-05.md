# Real uWSGI acceptance — 2026-09-05

Status: local runtime acceptance passed for all four maintained uWSGI profiles.
The candidate is uncommitted and **not deployed**. This follow-up changes test
fixtures, CI wiring and documentation; production candidate bytes are unchanged.
The [Go mail replacement and Exim work remain deferred](deferred-mail-go.md).

## Scope and evidence

The fixture compiles real uWSGI 2.0.31, using the source archive digest from
[PyPI](https://pypi.org/project/uWSGI/2.0.31/#files):
`e8f8b350ccc106ff93a65247b9136f529c14bf96b936ac5b264c6ff9d0c76257`.
The test image uses Python 3.14.7 and the repository's existing setuptools
83.0.0 build-backend pin. Its local Linux arm64 image ID is
`sha256:7456f402a0bcf0806b17dcafd36535f10a8b0a68e986c1d72d3bb7d1a3cea5ab`.
These are test dependencies; no production dependency was added.

The test renders the actual `docassemble.ini.dist`, `docassemblelog.ini.dist`
and both exposed-port profiles. Main, exposed and log roles use the actual
shell launchers with freshly built Go preflight, diagnostic and capture
binaries. No current launcher selects log-exposed, so that profile is checked
by direct Go preflight and runner invocation. Application and configuration
modules are synthetic; this is not a complete docassemble application boot.

Each profile receives four real protocol requests: 200, 503, explicit 500 and
an uncaught WSGI exception. The native exception closes its connection without
response headers while recording status 500; a direct native control confirmed
that behavior. The synthetic application emits distinct private markers on
stdout, stderr and in its exception. Retained wrapper output must contain only
the exact fixed JSON schema, bounded integers, one 2xx and three 5xx requests,
four total latency observations, and captured unclassified output. No marker,
query value or synthetic interview filename may appear in retained output.

Shutdown checks record the actual master and worker PIDs, their Linux start
times and isolated process group. After TERM, the wrapper must return zero and
the observed native processes must disappear. Cleanup only signals a verified
native group. Appending an unsafe `logto` directive must fail preflight with a
fixed startup record, before the requested file exists.

An intentionally unsafe runner built from an ignored source copy bypassed the
capture pipes. The original acceptance run rejected it because request counters
remained zero. That control proves missing capture is detected; it did not
demonstrate a retained-marker failure. The production runner was never replaced.

Evidence under `tests/.privacy-build/native-runtime-review/`:

- `image-build.log`: successful native image build; the earlier missing-header
  build failure is preserved separately.
- `native-control.log`: direct native behavior with synthetic data only.
- `capture-control.log`: intentionally unsafe capture failed acceptance.
- `uwsgi-reviewed.log`: all four profiles, latency/status accounting, native
  cleanup and unsafe configuration rejection passed; image and Go binary hashes.
- `verification.log`: canonical repository verification for this follow-up.

## Reproduction and bounds

From the worktree root, with an isolated Docker runtime selected:

```sh
bash tests/verify_privacy.sh
docker build -t privacy-candidate-check \
  -f tests/privacy_native/fixtures/privacy-check.Dockerfile tests/privacy_native/fixtures
docker build -t privacy-uwsgi-check \
  -f tests/privacy_native/fixtures/uwsgi-check.Dockerfile tests/privacy_native/fixtures
bash tests/privacy_native/test_uwsgi_image.sh privacy-uwsgi-check
```

The standalone acceptance script rebuilds all three mounted Go executables from
the current checkout; cached executable existence is insufficient. Per-run
artifacts remain in the ignored `tests/.privacy-build/uwsgi-run.*` directory.
Containers have unique names and bounded cleanup, no network, no Docker log
retention, a read-only root and source mounts, no capabilities, no privilege
escalation, 512 MiB memory and 128 PIDs. Temporary filesystems are bounded and
non-executable. The inner deadline is 45 seconds plus 5 seconds to kill; the
host command deadline is 55 seconds, followed by bounded removal verification.
The workflow now runs this fixture after its nginx/Supervisor checks.

Review added actual process-removal assertions, latency totals, fresh builds and
container resource/deadline controls. Passing these checks does not establish
real Flask/Celery behavior, complete retained-output coverage, rotation,
persistent-volume installation, rollback or exact-commit remote CI. The
[installation inventory](installation-plan.md) and [release gates](review-2026-09-05.md)
remain open. No incoming mail was sent or processed by this fixture.
