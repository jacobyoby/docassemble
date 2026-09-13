# Go foreground native runner

Status: integrated into the JOS-81 candidate's nginx, uWSGI, log-role, Celery,
single-queue Celery, websocket, and mail launchers; **not deployed**. Process and launcher tests have run on Linux,
including the race detector. [Real uWSGI acceptance](native-runtime-2026-09-05.md)
now covers all four profiles with synthetic application/configuration modules.
A complete docassemble image, full native/application services, persistent-volume
installation, monitoring, and rollback still need acceptance before release.

The standard-library Go executable at
`/usr/share/docassemble/webapp/privacy-process` replaces the unreleased Python
process wrapper and parent-death helper. It imports the
[Go aggregation library](aggregation-go.md). The Dockerfile builds all four Go
executables as static binaries and installs them root-owned, mode 0755. It
copies only the nginx lifecycle configuration from `Docker/privacy`. The
[Go preflight](native-config.md) validates native configuration before capture.
All four superseded Python helper files have moved unchanged
to `tests/privacy_native/reference`; they are no longer production runtime
dependencies. The canonical test suite still checks the frozen counter
algorithm against its pinned SHA-256.

## Invocation and lifecycle

```text
privacy-process --component nginx -- /usr/sbin/nginx -e stderr -g 'daemon off;'
privacy-process --component uwsgi -- /absolute/uwsgi --ini /absolute/profile --die-on-term
privacy-process --component celery -- /absolute/celery -A docassemble.webapp.worker worker
privacy-process --component websockets -- /absolute/python -u -m docassemble.webapp.socketserver
privacy-process --component mail -- /absolute/python -m docassemble.webapp.process_email /dev/stdin
```

The component, separator, absolute executable path, and NUL-free arguments are
validated before launch. uWSGI requires `--die-on-term`. Production invocation
has no bypass for parent-death protection and rejects non-Linux platforms.
Configuration validation remains a separate launcher step; the runner does
not claim arbitrary commands or configurations are safe native profiles.

The runner permanently disables core dumps, seals descriptors beyond standard
input/output/error with close-on-exec, and starts a new child session. Linux
`PDEATHSIG` sends nginx `SIGQUIT`, or uWSGI/application services `SIGTERM`, if the runner dies. The
creating Go thread stays locked for the child lifecycle so thread retirement
cannot trigger premature parent-death signals. Set-id and file-capability
executables are rejected because those transitions can clear this protection.
Service binaries/configuration must remain immutable through validation and
exec; later credential changes and daemonization remain prohibited by the
maintained native profile.

Service children receive `/dev/null` on stdin; mail alone inherits the message
stream. All children receive distinct stdout/stderr pipes. Two
readers use fixed 4 KiB buffers and a two-slot event channel. Aggregation occurs
on one goroutine. Captured bytes are never replayed or included in errors;
reader buffers, consumed events, and retained partial lines are cleared on
consumption or teardown. This bounds retained application payloads, not total
Go runtime RSS, kernel buffers, or every possible memory copy.

Cumulative service snapshots are emitted initially, at most once per second
while running when input changed, and finally after both streams finish. Mail
emits at most one final record to bound total output to the MTA. One writer
may be active; no unbounded output queue exists. Output accepts only a pipe or
socket. Each complete record has a five-second write deadline; collection and
signal handling continue while the sink is blocked. A partial stream write may
leave a truncated final JSON record if the sink fails; it is never reported as
success and is never followed by a raw-output fallback.

TERM/INT requests graceful native shutdown. HUP and USR1 are forwarded to the
master while running. The runner signals the process group if descendants
remain after master exit. Native profiles send group TERM/QUIT halfway through
a two-second grace window and group KILL at its end. Application profiles
allow the master its full 60-second Celery or 20-second websocket/mail grace window
before group escalation. All profiles allow one further second for teardown.
The [application capture record](application-capture-go.md) explains the service
shutdown and Supervisor margins. Escaped descendants retaining pipes cannot
extend the wait indefinitely; incomplete teardown returns failure. Native
exit codes are preserved; signal exits become 128 plus the signal number.
Mail maps every failure and interrupted delivery to temporary exit 75.

| Exit | Meaning |
| --- | --- |
| 64 | Invalid invocation |
| 70 | Unsupported platform, setup, capture, or teardown failure |
| 74 | Invalid, broken, timed-out, or unsuccessfully closed output sink |
| 75 | Mail-only temporary failure, including interrupted delivery |

Runner failures produce fixed exit statuses without error text. The candidate's
[Go process monitor](process-monitor-go.md) reports Supervisor failure states;
its installation and operational health checks remain release gates. A launcher unable to execute the binary reports its existing
bounded startup diagnostic for phase `launch`.

## Verification and limits

`bash tests/verify_privacy.sh` runs all applicable Go tests, formatting, vet,
fuzzing, host and Linux builds, 140 native/application-launcher Python tests, 84 frozen application
draft tests, shell syntax, and diff whitespace. On Linux it includes real process
lifecycle and launcher-to-Go capture tests under the race detector. On macOS
those Linux-specific tests must additionally run in a Linux environment.
`GORACE=atexit_sleep_ms=0` removes only the race runtime's artificial exit sleep,
which would interfere with shortened fixture shutdown deadlines; race
diagnostics and failure exits remain enabled.

Local Linux checks used disposable containers with no network, a read-only
root filesystem, all capabilities dropped, no-new-privileges, and an init
reaper. Source was mounted read-only, with caches confined to this worktree.
The Linux Go 1.27.0 archive was verified against the official SHA-256
`51798d2c42d0e1c6ed7fd9f48728b4193abac9e8aad6dbac2fe96a81f5909bda`.
The tests exercise real Linux pipes/processes/signals but use synthetic native
programs and bootstrap configuration; they do not boot docassemble services.

Checks cover final counters and native exit codes, separate streams, malformed
and oversized output, regular-file/broken/full sink rejection, graceful signal
selection, HUP/USR1 forwarding, parent death, stubborn masters, orphan workers,
core limits, inherited descriptors, and shared sink-flag restoration. The
actual uWSGI and log-role shell launchers reach both Go preflight and process
CLIs and preserve the synthetic native exit code. Unsafe selected profiles and
missing preflight helpers stop before native launch. The nginx shell's argument routing remains covered
by the existing synthetic launcher test. An isolated mutation removing
descriptor sealing fails the descriptor-inheritance test with native exit 95.
Linux `go vet` and a Linux-targeted `govulncheck@v1.7.0` scan passed; the scanner
found no vulnerabilities. These checks cover the Go candidate, not the entire
docassemble dependency set or installed service image.

Evidence is recorded in `tests/.privacy-build/runner-review/`, including test
logs, before-edit copies, the mutation control, security scan, and source
hashes. Earlier aggregator/startup evidence is historical and does not describe
the new source layout. The later [preflight integration record](preflight-integration-2026-09-05.md)
records current launcher checks and real nginx configuration inspection.
The later [application capture record](application-capture-go.md) covers Celery
and websocket integration, full worker grace windows, and real Supervisor
acceptance using synthetic runtime commands.
The [application logger replacement](application-logger-go.md) removes the
independent file handler and verifies the real base logger under Go capture
across 80 profile/context combinations. The [mail capture record](mail-capture-go.md)
documents stdin preservation, bounded total output, retry exits, and unresolved
real mail processing and transport acceptance.
The [release review](review-2026-09-05.md) retains the
remaining implementation, full-installation, monitoring, and release gates.
