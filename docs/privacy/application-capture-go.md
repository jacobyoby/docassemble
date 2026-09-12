# Go capture for Celery and websockets

Status: integrated into the uncommitted JOS-81 candidate; **not deployed**.
The three application launchers now use the existing Go process runner. This
covers their checked bootstrap steps and captured stdout/stderr, including
output before Python logging initialization. Independently opened files and
other service launchers remain outside this boundary.

## Launch and output contract

`run-celery.sh`, `run-celery-single.sh`, and `run-websockets.sh` discard raw
bootstrap output and check virtualenv activation, configuration loading,
export evaluation, and the final exec. Failures use the fixed component/phase
records and exit statuses in [startup diagnostics](startup-diagnostics.md).
A missing diagnostic stops execution before activation. Successful exec closes
the temporary sink descriptor and preserves Supervisor's process identity.
The Go runner then starts the foreground service through its existing Linux
process protections and bounded capture path.

The selected virtualenv supplies the absolute Python/Celery executable path.
Celery queue names and worker arguments are preserved. Its concurrency remains
the CPU count capped by the configured maximum, replaced by an explicit worker
override when supplied, then reduced by one with a minimum of one. Counts must
be canonical positive decimal integers at most 1,048,576 before shell
arithmetic. Zero, negative, leading-zero, oversized, or arithmetic-expression
values fail configuration evaluation. The single queue always uses one worker.

The fixed capture components are `celery`, `celerysingle`, and `websockets`.
They use the existing 14-field cumulative snapshot schema. Valid text lines
increment `unclassified`, malformed text increments `rejected`, and oversized
lines increment `dropped`. Application text never becomes request metrics,
even when it resembles `PRIVACY_REQUEST`. All nine status/latency fields stay
zero; serialization also rejects forged nonzero request counters for these
components. Original nginx/uWSGI parsing and the frozen reference remain intact.

Supervisor retains only the launcher's fixed startup records and the runner's
counter snapshots in the existing worker/websocket log paths. Each application
section now uses one combined stream with 5 MB rotation and seven backups.
The [process monitor](process-monitor-go.md) reports these three services'
unexpected EXITED, BACKOFF, and FATAL states using fixed labels.

## Shutdown behavior

| Service | Master grace before group escalation | Supervisor stop wait |
| --- | --- | --- |
| Celery | 60 seconds | 70 seconds |
| Single-queue Celery | 60 seconds | 70 seconds |
| Websockets | 20 seconds | 30 seconds |

TERM/INT reaches the service master first. Its workers receive the full master
grace window before group signaling and KILL; the original two-second native
profile would interrupt Celery work prematurely. Remaining descendants are
signaled immediately if the master exits. The runner allows one further second
for teardown and retains its five-second output deadline. Supervisor's extra
time accommodates capture/teardown overhead. Linux parent-death protection
sends TERM to the application master if the runner dies. It cannot guarantee
drain completion when the master ignores TERM or changes credentials; the
foreground process and credential restrictions still apply.

The websocket launcher now execs the runner instead of using a shell trap that
exits without waiting for the child. Native exit codes remain observable.

## Verification record

Local verification on September 5, 2026 used synthetic data only:

- Fail-first application checks reproduced raw bootstrap output and continuation
  after startup failures in the old launchers. New profiles also failed against
  the previous Go parser before implementation.
- `bash tests/verify_privacy.sh` passed Go formatting, vet, race tests, four
  bounded fuzz targets, module verification, four host/Linux amd64/arm64
  executable builds, 126 native/application-launcher Python tests, 84 existing
  application logger tests, shell syntax, and diff whitespace.
- All Go packages passed the final Linux race suite and Linux vet. Actual shell
  launchers reached Go capture for all three roles and retained only counters
  while preserving the synthetic service's exit code. Six lifecycle cases
  covered worker completion during normal shutdown and runner death.
- An isolated mutation restoring half-window group signaling failed the Celery
  and single-queue drain checks with worker exit 93. Production source and
  assertions were unchanged by the control.
- Real Supervisor 4.3.0 ran the production listener and application sections
  as `www-data`, invoking the actual launchers with synthetic runtime commands.
  All three application logs contained counter records only; the monitor
  reported their unexpected exits and ignored expected/unrelated exits.
  The fixture uses executable files from a read-only mount and leaves `/tmp`
  non-executable. No container permissions were broadened to make it pass.
- Real nginx inspection accepted the safe profile and rejected the unsafe
  profile without output. Both profiles first passed native syntax inspection.
- A fresh Linux-targeted `govulncheck@v1.7.0` scan found no vulnerabilities in
  the Go candidate. This does not scan the full docassemble dependency set.

Evidence and before-edit copies are in
`tests/.privacy-build/application-capture-review/`. The final Linux checks used
Go 1.27.0 and the existing development image
`sha256:d318b5a18cc090c52fc2db3a9642f1e3749e6bcd64d71c93cfd36e51ea596a25`.
Containers had no network, a read-only root filesystem, no capabilities, and
no-new-privileges. Runtime state and caches stayed within this worktree.

## Remaining release work

The later [application logger replacement](application-logger-go.md) removes
the file-handler override and leaves the existing stderr callback feeding Go
capture. The Python draft and its unconsumed failure counter are now frozen
test references. No `log to std` text check or duplicated cloud configuration
loader is needed for that replacement.
The later [mail capture record](mail-capture-go.md) removes mail's direct
`/tmp/mail.log` and adds a bounded Go command profile. Cron, other independent files, and remaining
service/copy/backup routes need separate coverage.

The fixture does not run real Flask, Celery tasks, a broker, or websocket
requests. A complete candidate image, persistent-volume installation, retained
output/rotation/restore acceptance, tested rollback, monitor health checks,
and CI for the exact release commit remain required. No commit, push, merge,
or production change was made. See the [release review](review-2026-09-05.md).
