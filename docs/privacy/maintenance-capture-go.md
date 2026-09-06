# Maintenance and initialization capture

The candidate reuses the Go runner for the four scheduled docassemble scripts,
`sync.sh`, the rotation callback and `initialize.sh`. A small re-exec prelude
enters capture before activation or configuration. Existing commands, role
checks, arguments and working directory are retained. No backup framework or
content filter is added.

The internal `--privacy-captured` handoff prevents recursion. Supported callers
invoke the scripts normally without it; it is not an authorization boundary.
Missing capture executables fail before activation with a fixed diagnostic.
The finite `maintenance` profile emits one final counter snapshot and preserves
the script exit code. Its 30-second shutdown grace encloses the inner cron
runner's 20-second grace, one-second teardown and five-second sink deadline.
Supervisor allows 40 seconds for sync.

Nested interview-cron records are counted as application text by the outer
runner. Their detailed phase/event labels are not forwarded. Legacy shell
exit behavior also remains: an early failing command can be followed by a
successful final command. This change does not claim per-command failure
detection or introduce blanket `set -e`.

The `initialize` profile reports periodic counters. Its 610-second shutdown
grace accommodates PostgreSQL's existing 600-second budget and final cleanup;
Supervisor allows 630 seconds. The shared `main` group still stops initializer,
PostgreSQL and Redis together. The monitor accepts only the exact
`initialize/main` pair and emits fixed unexpected-exit/backoff/fatal records.
Other accepted process/group pairs remain unchanged.

The native image rehearsal now covers:

- Real installed hourly/daily/weekly/monthly and sync operations, local and
  rolling log backups, and historical sentinel bytes.
- The actual non-mail logrotate stanza and callback in its configured cron
  role context, preserved rotated bytes and expected worker PID changes.
- TERM through the outer monthly script into a real cron interview, plus
  the existing inner TERM/INT checks.
- A real initializer startup module that checks root identity, working
  directory and closed inherited fd3, emits stdout/stderr markers, and
  writes a success receipt. A newer receipt is required after restart.
- Whole-container orderly shutdown, absent running/ready markers, a
  shutdown-only backup sentinel, valid final initializer counters and
  same-volume restart. The host inserts a backup-only file while stopped;
  its later appearance in live logs proves the actual restore path ran.
- A one-shot startup hold in that same synthetic module, before the real
  initializer installs its shutdown trap. Supervisor interrupts the captured
  initializer, and its unfinished-start marker must survive. A new backup-only
  file must remain absent from live logs on the next startup, proving the
  existing unsafe-restore guard still applies.
- Preserved configuration, upload and database session state, working
  queue/cron after restart, stopped-service reconciliation and rollback.

The container's explicit 1000-second stop budget covers serial Supervisor
group shutdown; it is not just the initializer's timeout. Each main-group
update waits for initialization readiness before checking state or restoring
counter metadata. The old initializer's normal log-directory ownership pass
must finish first.

These additions require native CI before acceptance is claimed. Historical
diagnostic content is preserved separately from new private-output markers.
Scans cover current, rotated, copied and local/rolling backup diagnostic
destinations; application documents and database dumps are not treated as logs.
Target checks establish local backups and disable S3/Azure. Conditional cloud,
Apache and explicit log-role paths, arbitrary third-party handlers and manual
bypasses are not proven by this fixture. Native CI for the added lifecycle
controls and final target-specific release checks remain open. Mail stays
deferred and its rotation stanza is excluded.
