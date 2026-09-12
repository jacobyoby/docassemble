# Bounded startup failure diagnostics

Status: implemented in the JOS-81 candidate; not deployed. This resolves the
tested bootstrap failure-reporting paths only. Full native startup, monitor
health, retained-sink acceptance, and complete logging coverage remain open.

`Docker/privacy-diagnostic` is a Go 1.27.0 module using only the standard library.
The Dockerfile builds a static binary in a separate `golang:1.27.0` stage and
installs it, root-owned with mode 0755, at
`/usr/share/docassemble/webapp/privacy-diagnostic`. The Go compiler and scanner
are not added to the final service image. Existing persistent volumes still
require explicit installation; image construction alone does not establish that
the running volume contains this binary.

## Record and process contract

The uWSGI, log-role uWSGI, nginx, Celery, single-queue Celery, websocket, and mail launchers discard raw bootstrap output and
call the diagnostic with a fixed component and phase when a checked step fails:

```json
{"schema":1,"component":"uwsgi","event":"startup_failed","phase":"activation"}
```

Components: `uwsgi`, `uwsgilog`, `nginx`, `celery`, `celerysingle`, `websockets`, `mail`.
Phases: `activation`, `config`,
`config_eval`, `preflight`, `launch`. Nginx combines activation and configuration
loading in its existing `su` command and reports that failure as `config`.
Unknown arguments produce only a fixed `launcher`/`invocation` record. No input
argument is copied into output, including invalid strings.

Output is one newline-terminated JSON record, at most 256 bytes. The helper
accepts only a pipe or socket, registers a nonblocking duplicate with Go's I/O
poller, and imposes a one-second write deadline. It restores the inherited
descriptor's flags before closing the duplicate. The launcher is waiting for
that process, so successful service execution is unaffected by these temporary
flags. Kernel-managed status bits caused by any write are not writable flags.

| Exit | Meaning |
| --- | --- |
| 64 | Invalid diagnostic invocation; fixed invocation record if deliverable |
| 69 | Diagnostic executable missing or not executable; launcher stops before bootstrap |
| 70 | Startup failed; fixed component/phase record delivered |
| 74 | Diagnostic sink unavailable, unsupported, broken, or timed out |

An OS failure to execute an otherwise executable diagnostic propagates its
nonzero shell status in the service launchers. The [mail launcher](mail-capture-go.md)
maps all its startup failures to 75, including a missing diagnostic or failed
diagnostic delivery. Failure to deliver a record is never success and never
falls back to raw stderr. Supervisor must retain/monitor these process exits;
the missing-helper and failed-sink paths cannot promise a delivered record.
The candidate now includes a [Go process-failure monitor](process-monitor-go.md),
verified with real Supervisor and synthetic services. Installing it and checking
its operational health remain part of full deployment acceptance.

Successful launch still uses `exec`, preserving Supervisor's process identity.
The extra sink descriptor is closed before native-wrapper startup. Bash keeps
the failed `exec` redirections, so the failure path recovers the sink from its
already-redirected stdout before reporting `launch`.

## Verification

```sh
bash tests/verify_privacy.sh
```

The runner keeps build/test caches in `tests/.privacy-build/`, checks formatting,
runs `go vet`, race tests, ten seconds of bounded fuzzing for each fuzz target,
module verification, host compilation, Linux amd64/arm64 compilation of all Go
packages, the Python candidate
suites, shell syntax, and tracked diff whitespace. The new GitHub workflow runs
this on Linux and adds `govulncheck@v1.7.0`. That pinned scanner is a development
tool only; it is not a runtime/module dependency. Its downloads and vulnerability
database require network access. No dependency was added to the diagnostic's
`go.mod` beyond the Go language version.

Fail-first evidence: six activation/config/preflight cases failed against the
previous silent launchers; the successful handoff control remained passing.
Expanded launcher checks execute the compiled diagnostic and cover all checked
phases, absent executables, broken/full output pipes, successful PID handoff,
and closure of the extra sink descriptor. Nginx tests use its read-only profile
with synthetic `su`, configuration, and native-execution boundaries; they do not
write system nginx paths or start nginx. Go tests also cover invalid arguments,
fixed-schema output, regular-file rejection, socket delivery, deadline behavior,
and descriptor-flag restoration.

These are focused checks, not full service acceptance. The initial image build,
installation into a persistent volume, real native services, complete logging
coverage, exit monitoring, and rollback are not established by them.

Original diagnostic verification record (2026-09-05): 122 native-profile and 84 application tests
pass. Go formatting, vet, race tests, 1,001,159 fuzz executions, module checks,
host compilation, and static Linux amd64/arm64 cross-builds pass. A source-mode
`govulncheck@v1.7.0` scan found no vulnerabilities in the diagnostic's reachable
Go code. The new workflow is authored but has not run on GitHub; the complete
Docker image has not been built. Evidence and pre-edit backups are retained in
`tests/.startup-review/`.

The later [Go aggregator](aggregation-go.md), [Go native runner](native-runner-go.md),
and [Go preflight](native-config.md) extend the candidate's capture path. The
launchers now select the Go preflight and runner. Their evidence is separate
from this original diagnostic verification record; see the current
[preflight integration record](preflight-integration-2026-09-05.md).
The later [application capture record](application-capture-go.md) extends the
checked bootstrap paths to Celery and websockets and records the current
126 native/application-launcher tests. The later [application logger replacement](application-logger-go.md)
adds 64 Linux capture combinations; the 84 Python logger tests now cover frozen
references only.
