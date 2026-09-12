# Historical Python application logging draft (JOS-81)

Status: **frozen test reference, superseded in the candidate**. Both draft
modules now live in `tests/privacy_logging/reference/`, with their original
bytes and tests preserved. The production application uses the existing stderr
callback through [Go capture](application-logger-go.md). The behavior and
limitations below describe the historical draft, not the current runtime.

The draft replaced the `docassemble.webapp.log_initialize` entrypoint
and added its adjacent, dependency-free `privacy_logging` module. Importing the
real module installs the base `docassemble.base.logger` callback in every context.
The staged candidate previously skipped Celery, cron and `log to std`.

| Context | Safe destination for the base callback |
| --- | --- |
| Web, default | `LOG_DIRECTORY/docassemble.log`, append mode |
| Web, `SUPERVISORLOGLEVEL=debug` | Same file plus stderr; either usable sink suffices |
| Celery or cron | stderr, without opening the application log file |
| `log to std` | stderr, without opening the application log file |

The stderr choices preserve the original base logger destination in the formerly
skipped branches. Debug does not add a duplicate stderr handler in those modes.
`LOGSERVER` preserves callback selection, but both callbacks now discard legacy
message text without inspecting or stringifying it. The formatter supplies UTC
time; legacy calls produce event `UNKNOWN`, with no equivalent free-text detail.
Direct records sent to the configured `docassemble` logger may supply an exact
allowlisted `event_code` instead.

Every emitted application record has exactly `ts`, `level`, `svc`, `comp`, and
`event`. Service/component are fixed; timestamp, level and event are validated.
Message, args, exception/stack text, logger name, paths, IPs, identities, sessions,
form names and arbitrary extra attributes are discarded. Safe handlers ignore
attempts to replace their formatter. Existing handlers and filters on this
specific logger are removed and propagation is disabled.

The safe callback is registered before configuration and sink setup. Startup
probes sinks with an empty write and flush; file opens retry at most five times
with four one-second waits. No usable sink raises the fixed
`RuntimeError("Privacy logging unavailable")`, suppressing both the internal
failure and any active caller exception chain. A NullHandler prevents stdlib's
raw `lastResort` fallback. A missing helper or dependency also fails startup;
there is no fallback to the previous free-text callback once it is available.
If the base logger itself cannot import, startup fails before registration.

Later write/flush failures emit no fallback text; each safe handler keeps a local
failure count capped at 99. This module does not restart services, recover a
failed sink, bound synchronous stream-write time, or prove continued delivery
when a sink accepts the empty probe and later rejects records. Reinitialization
closes only files opened by this module. Historical contents in an existing log
file are untouched and require separately authorized retention handling.

## Local verification

Run from the fork root:

```sh
python3.14 -m unittest discover -s tests/privacy_logging -v
```

84 tests pass on Python 3.14.7. They include all 16 context/LOGSERVER/debug
combinations, hostile messages/fields, exact schema, formatter replacement,
propagation, retry exhaustion, missing/closed/failing stderr, file probe failure,
import/setup failure, write/flush failure, caller exception suppression,
reinitialization and an actual interpreter shutdown subprocess. The latter must
exit zero with empty stderr, so an import failure cannot count as a passing test.

Tests import the frozen references under their original module names using synthetic
configuration and dependency stubs. They also execute real `server.py`,
`flask_app.py`, `app_initialize.py`, and `worker.py` until the first post-logging
boundary (`secret_key` assignment). The real worker selects `in_celery=True`.
The real `cron.py` launcher runs with a stub subprocess; its `IN_CRON` value then
drives a synthetic config for the same real server import. The Flask CLI and base
configuration loader are not executed. No real application, database, task
broker, request, production configuration or production log is imported/read.

## Historical acceptance limits

The tests establish early installation, not complete application startup or
survival through subsequent Celery/Flask logging configuration. In particular:

- Web configuration imports and `setup.init_app` run before this entrypoint;
  Celery loads base configuration first. Output from those earlier operations is
  outside this module. Full synthetic startup must verify the outer capture
  boundary and later logger configuration before installation.
- Celery root/task loggers, Flask and other third-party loggers, websocket's
  separate app, SQL diagnostics, arbitrary logging factories/filters installed
  later, native extensions, direct stdout/stderr and independent file writes
  remain separate routes. A safe base callback alone does not protect them.
- Packaging must install both adjacent modules into the interpreter used by every
  applicable service. Full dependency startup, actual queue/task behavior,
  scheduled job execution, log rotation/copy/backup/restore, and process capture
  across the complete launcher lifecycle still need acceptance evidence.

Current replacement behavior, source coverage, and remaining release gates are
recorded in [application logging through Go capture](application-logger-go.md).
