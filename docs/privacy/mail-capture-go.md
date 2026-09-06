# Mail command capture through Go

Status: implemented and locally verified in the uncommitted JOS-81 candidate;
**not deployed**. This protects the mail command's bootstrap and captured
streams. Actual Exim delivery, application storage, and retained Exim logs have
not passed release acceptance.

The user subsequently deferred the Go replacement of the underlying mail
processor. Its findings and restart boundary are saved in
[the deferred work note](deferred-mail-go.md); this capture candidate remains
preserved and unreleased.

## Command boundary

`Docker/process-email.sh` checks activation and replaces itself with
`privacy-process --component mail -- /absolute/python -m
docassemble.webapp.process_email /dev/stdin`. The message stays on inherited
stdin. The shell no longer spools a second raw message through `mktemp`, and
its final cleanup command no longer hides the processor's exit status.

The existing Python processor no longer opens or writes `/tmp/mail.log`.
Its MIME, database, storage, and task code is otherwise unchanged; no new
executable production Python or dependency was added. Removing diagnostic
writes does not remove the intended operational message and attachment data.

The Go mail profile inherits the runner's descriptor sealing, core limit,
locked-thread Linux parent-death protection, bounded stream buffers, and
process-group teardown. It alone passes stdin to its child. Mail uses a
20-second master grace window plus one second for bounded teardown.

Mail emits at most **one final counter record**, below the existing 8,192-byte
record limit. Service profiles retain their periodic reporting. Each mail line
uses the application counter rules; request-looking text cannot become request
metrics. Raw message contents, recipient addresses, exceptions, and paths are
never counter fields. Bootstrap failures emit a single fixed startup record
when the diagnostic helper and sink work.

The successful command returns zero. Startup, invocation, child, capture, sink,
and teardown failures return 75. A received SIGINT or SIGTERM also returns 75,
even if the child handles shutdown and returns zero. Hard-killing the launcher
or failure to execute it is outside that exit-mapping boundary.

Exim's [pipe transport contract](https://www.exim.org/exim-html-current/doc/html/spec_html/ch-the_pipe_transport.html)
explains the constraints: stock temporary statuses include 75, combined command
output defaults to a 20 KiB maximum, and `return_output` can reject successful
commands that produce output. Final-only reporting prevents periodic counters
from eventually crossing the output limit. It does not alter Exim's timeout,
transport options, or retained logging policy.

## Verification

Run `bash tests/verify_privacy.sh`; on macOS also run the Linux Go suite.
The September 5 mail-cycle results include:

- Canonical formatting, vet, race tests, four bounded fuzz targets, module
  verification, four host/Linux amd64/arm64 executable builds, shell syntax,
  131 native/launcher Python tests, and 84 unchanged frozen-reference tests.
- Full Linux race suite and vet; a fresh Linux-targeted `govulncheck@v1.7.0`
  scan found no vulnerabilities in the Go candidate.
- Actual mail shell and Go CLI with 1.25 MiB binary stdin preserved by SHA-256,
  successful synthetic processing, native exit 17, read/unknown-recipient,
  database, and broker failures; rejected regular-file sinks and missing tools.
- Public CLI child-signal and interrupted-clean-child tests, including SIGINT
  and SIGTERM; broken and full pipe sinks return 75 within the deadline.
  Three reporting intervals and more than 20 KiB of raw child output produce
  one final record with all 3,000 lines counted. This is not a 90-second test.
- The real application logging boundary across 80 profile/context combinations,
  plus mail worker-drain and parent-death fixtures. Existing real Supervisor
  service acceptance remains separate from mail, which is MTA-invoked.

The mail processor fixture runs the real module as `__main__` and observes its
configuration-load call. Database, storage, configuration, and broker interfaces
are synthetic. It verifies MIME values and interface calls, **not actual
attachment persistence, transaction ordering, or broker delivery**.

Fail-first evidence caught the old independent log, swallowed processor exits,
periodic mail records, and interrupted delivery falsely returning success.
Source copies and logs live in `tests/.privacy-build/mail-capture-review/`.
Three independent read-only reviews covered Go lifecycle, processor contracts,
and Exim integration; one writer owns the candidate worktree.

## Unresolved release gates

The review exposed existing processor defects that the synthetic interfaces
cannot prove safe:

1. Decoded MIME payloads are bytes, while `save_attachment` calls
   `SavedFile.write_content` without its binary option. The actual method's
   default text writer raises `TypeError`. Run
   `TMPDIR="$PWD/tests/.privacy-build/tmp" python3.14 -B
   tests/privacy_native/probe_mail_storage.py` from the checkout root. This
   separate probe intentionally remains nonzero; its textual control passes
   before decoded bytes fail. The method is extracted from real source and
   uses in-memory handles, with no application import or storage writes.
2. The processor consumes the new email ID before an explicit session flush
   and queues work before the surrounding transaction commits. The synthetic
   fixture's immediate ID and task ledger do not establish correct linkage or
   ordering. Real database/broker tests, retry replay, and duplicate processing
   acceptance remain required.
3. The candidate inherits `address_pipe` from its unpinned base image. Inspect
   `exim4 -bP transport address_pipe` and
   `exim4 -bP log_file_path log_selector` inside the exact image. Verify exit-75,
   timeout and missing-launcher behavior, execution as `www-data`, configured
   runtime paths, and writable/read-only initialization. The stock transport
   discards successful/deferred command output: these counters are not yet a
   retained mail-health record. Exim main/reject/panic logs remain separate.

The complete image, persistent-volume installation, rollback, cron coverage,
retained log/copy/restore acceptance, and exact-commit CI remain required by
the [release review](review-2026-09-05.md). No production service, volume,
configuration, log, or mail queue was changed during this cycle.
