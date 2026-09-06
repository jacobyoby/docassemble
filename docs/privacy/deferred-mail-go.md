# Deferred: incoming mail replacement in Go

User decision on September 5, 2026: implement the incoming-mail replacement in
Go, then **save it for later**. Do not resume this replacement or its proposed
Exim transport changes without a new user request. No reminder or scheduled
resume was created.

## Saved state

- Worktree: `/Users/jacobrakai/Projects/docassemble-jos81`;
  branch `fix/jos81-private-logging`; HEAD
  `63d22c44b7bd008a521f0bcb8ab442b2143ee557`.
- The existing uncommitted [mail capture candidate](mail-capture-go.md) remains
  preserved. It routes the legacy processor through Go capture, removes its
  diagnostic file and shell spool, and maps command failures to 75. It does
  not replace the actual Python mail processor.
- Last candidate verification: 131 native/launcher tests, 84 unchanged frozen
  reference tests, full Linux race/vet, Go vulnerability scan, and real
  Supervisor acceptance passed. Evidence is in
  `tests/.privacy-build/mail-capture-review/`. Those checks are bounded capture
  verification, not real incoming-mail delivery acceptance.
- The replacement's parser was discussed but no `internal/mailparse` package
  was created before the user deferred work. No production Python repairs,
  new dependencies, Exim changes, mail sends, or deployment occurred in this
  follow-up. Working agents were interrupted. The task Linux VM remains off.
- Deferral does not resolve the [release gates](review-2026-09-05.md). Other
  JOS-81 work may continue without restarting this mail replacement.

## Findings to carry forward

1. **The storage caller selects the wrong mode.** `process_email.save_attachment`
   passes decoded MIME bytes to `SavedFile.write_content` without its binary
   option. The generic writer's default text behavior is correct. The saved
   `probe_mail_storage.py` demonstrates that mismatch by invoking the actual
   method directly; it must not become a requirement to change that default.
   A replacement acceptance test must exercise the real caller/storage contract.
2. **IDs and publication ordering need real transaction tests.** The existing
   processor reads `Email.id` before an explicit flush and publishes its task
   before `session_scope` commits. Its upload-number allocator uses Flask's
   scoped session even though the standalone mail entrypoint establishes no
   Flask application context. Use one explicit Go database transaction for
   related records and capture scalar task data before commit. Publishing
   after commit alone does not provide an outbox or duplicate protection.
3. **Preserve the consumer's storage layout.** `Uploads` stores `key`, `filename`,
   `yamlfile`, and default private/persistent flags. Local upload ID 77 maps to
   `<uploads>/000/000/000/04d/file`, with `file.<extension>` pointing to the same
   content. Cloud object keys use decimal IDs: `files/77/file` and
   `files/77/file.<extension>`. S3/Azure behavior, MIME metadata, rollback
   residues, and existing file collisions require acceptance.
4. **Preserve the existing incoming-mail task.** Its name is
   `tasks.background_action`; the action is `incoming_email` with the numeric
   email ID. The consumer immediately retrieves committed email/attachment
   rows. `tasks/app_object.py` selects the configured `rabbitmq` broker or a
   default `pyamqp` URL, with Redis as the result backend. Exact Celery message
   protocol, routing, broker variants, confirmations, and retry behavior have
   not been mapped or implemented in Go.
5. **Keep Exim transport work explicit.** A proposed dedicated
   `docassemble_mail_pipe` would avoid modifying unrelated `address_pipe`
   consumers. Candidate settings need real Exim queue tests for 75, execution
   failure 127, timeout deferral, and signal freezing. Freezing needs manual
   intervention; it is not automatic retry. Native output logging includes
   recipient context and cannot stand in for a private fixed-counter sink.

## Resume boundary

Start by reading `process_email.py`, `emailserver/models.py`,
`emailserver/helpers.py`, `files/savedfile.py`, `files/file_number.py`,
`main/models.py`, `tasks/app_object.py`, and `config_worker.py` in the webapp
package. Confirm current source and dependencies before implementation.

The proposed first Go API was `mailparse.Parse(io.Reader, Limits)` returning
typed metadata and MIME parts with fixed, content-free errors. Caller-supplied
positive bounds would cover raw/decoded bytes, part count, and nesting depth.
Preserve ordered headers, addresses, recipient selection, text/PDF bytes, and
consumer-required filenames. Resolve RFC2047, platform MIME extension, and
nested-message differences through tests against the legacy contract.

That parser would be only one part of a complete Go ingestion path. Do not
activate a parser-only replacement or route production to an incomplete
database/storage/queue implementation. Estimated scope: several hours of
implementation and integration acceptance, beyond a simple email test.
