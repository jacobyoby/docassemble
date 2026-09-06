# Go process-failure monitor

Status: implemented in the JOS-81 candidate and verified with synthetic
processes under real Supervisor 4.3.0; **not deployed**. This covers nginx,
uWSGI, log-role, Celery, single-queue Celery, and websocket process failures.
The later [application logger replacement](application-logger-go.md) removes
the Python handler's unconsumed failure counter. Full installation and monitor
health gates remain open.

`privacy-monitor` is a standard-library Go executable installed at
`/usr/share/docassemble/webapp/privacy-monitor`. The Dockerfile builds it with
the other three Go helpers, root-owned with mode 0755. The new Supervisor
listener runs as `www-data`, starts before the native services, and restarts
after failure. It receives process EXITED, BACKOFF, FATAL, and TICK_60 events.
Supervisor's [documented event protocol](https://supervisord.org/events.html#event-notification-protocol)
provides the input framing and acknowledgement contract.

## Output and failure behavior

Only fixed service/state labels reach the report sink:

```json
{"schema":1,"component":"uwsgi","event":"process_failed","state":"exited"}
```

Components are `nginx`, `uwsgi`, `uwsgilog`, `celery`, `celerysingle`,
`websockets`, and `monitor`. Process failures use
states `exited`, `backoff`, or `fatal`; monitor readiness/liveness uses `ready`.
An unexpected exit produces a failure record. A missing executable, early exit,
or exhausted startup retries produces BACKOFF/FATAL records as supplied by
Supervisor. Expected exits and unrelated services produce no failure record.
No PID, process/group name from input, serial, server name, command, path, raw
log output, or exception is retained in these records. These state events do
not contain the numeric native exit code, so the monitor does not invent it.

Stdout carries only `READY`/`RESULT` protocol messages and is not logged. Fixed
JSON records go to stderr, which Supervisor retains in `privacy-monitor.log`
with 5 MB rotation and seven backups. `redirect_stderr` remains false so records
cannot corrupt the acknowledgement stream. A readiness record precedes the
first READY; each received TICK_60 produces a liveness record. A malformed frame
produces a fixed `monitor`/`protocol_failed`/`invalid` record when deliverable.

The dedicated Linux process disables core dumps and seals extra inherited
descriptors. It accepts only pipes/sockets for its three standard descriptors.
Header storage is 1 KiB including its newline; payloads are limited to 1 KiB,
with at most 16 fields per token set. Control/non-ASCII bytes, duplicate fields,
invalid framing, and oversized declared payloads reject. Idle waits are allowed;
after a frame begins, five seconds bounds its complete header/payload. Each
protocol or record write has a five-second deadline. Buffers are cleared after
processing; this does not promise erasure of runtime copies or kernel memory.

| Exit | Meaning |
| --- | --- |
| 0 | Supervisor closed input between events |
| 64 | Unsupported invocation arguments |
| 70 | Unsupported platform, process protection, or event-protocol failure |
| 74 | Unavailable, unsupported, broken, blocked, or unsuccessfully closed pipe |

The listener acknowledges a reportable event only after the record is accepted
by its output pipe. A failed delivery exits without acknowledgement, allowing
Supervisor to requeue the event. Acknowledgement loss can therefore produce
duplicates; output acceptance is not a filesystem durability guarantee. The
listener pool buffers 256 events. Queue overflow and the monitor's own
unavailability remain visible through Supervisor's activity log/state; they
must be covered by deployment health checks. A missing liveness record is not
proof that services are healthy. No external notification or service-control
API call is performed.

## Verification

```sh
bash tests/verify_privacy.sh
docker build -t privacy-candidate-check \
  -f tests/privacy_native/fixtures/privacy-check.Dockerfile tests/privacy_native/fixtures
bash tests/privacy_native/test_nginx_preflight_image.sh privacy-candidate-check
bash tests/privacy_native/test_supervisor_monitor_image.sh privacy-candidate-check
```

The disposable test image's Python, gcc, Bash, Supervisor, and nginx are
development tools: Python runs the existing reference suites and fixtures, gcc
supports Linux race tests, and Bash/native services exercise their real
protocols. They add no Go module dependencies. The Supervisor harness runs as
the same `www-data` identity and uses the production listener section, changing
only its log destination to a temporary directory. Native programs are
synthetic: a clean exit, an unexpected exit, a missing executable, and an
unrelated process. The container has no network, a read-only root filesystem,
no capabilities, no-new-privileges, and temporary writable `/tmp`.
The expanded harness also runs the actual application launchers and compiled
Go capture with synthetic runtime executables from the read-only source mount;
it checks their retained counters and unexpected process exits.

Original monitor verification record on September 5, 2026:

- The canonical suite passed: formatting, vet, race tests, module verification,
  four host/Linux amd64/arm64 executable builds, 122 native-profile and 84
  application Python tests, shell syntax, and diff whitespace.
- All Go packages passed Linux race tests; Linux vet passed. The
  Linux-targeted `govulncheck@v1.7.0` scan found no vulnerabilities.
- Four bounded fuzz targets passed; the new monitor target ran 1,094,705
  executions. Parser tests validate fixed output, malformed input, and ignored
  events. Linux pipe tests cover truncated/oversized/stalled frames, full and
  broken sinks, delivery before acknowledgement, and descriptor-flag restoration.
- The compiled monitor passed real Supervisor 4.3.0 acceptance with the synthetic
  processes. An isolated mutation acknowledging before delivery failed the
  broken-sink test with an unexpected `RESULT` token. Production source and
  assertions were unchanged by that mutation.
- Final checks covered 92 candidate files: no supported credential markers,
  generated junk, broken local documentation links, or trailing whitespace;
  workflow YAML parsed and all Go files remained below 500 lines. This is scoped
  hygiene, not a complete service/dependency security audit.

The workflow now includes both real-protocol checks, but it has not run on
GitHub for this uncommitted candidate. Evidence, before-edit copies, the
mutation, and manifests are in `tests/.privacy-build/monitor-review/`. The
shared Linux runtime was found stopped; this cycle used a separate runtime
whose files/caches are confined to this worktree. Its test image was
`sha256:d318b5a18cc090c52fc2db3a9642f1e3749e6bcd64d71c93cfd36e51ea596a25`
(Linux arm64, Python 3.14.7, Supervisor 4.3.0, nginx 1.30.4). No production
services, logs, or volumes were changed. All disposable containers finished,
and the worktree's VM was stopped after verification. The application boundary,
complete candidate image, persistent-volume installer, rollback, retained-output
coverage, and exact-commit CI remain required by the [release review](review-2026-09-05.md).
The later [application capture record](application-capture-go.md) records the
expanded six-service coverage and current verification.
