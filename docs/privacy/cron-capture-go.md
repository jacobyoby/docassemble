# Interview-cron output capture

`run-cron.sh` now uses the existing Go capture process for the Flask cron
command. The fixed `cron` profile treats stdout/stderr as application output,
emits one final counter record, and preserves the command's exit status. It
does not forward stdin or use mail's temporary-failure mapping. Existing mail
enum values and behavior remain unchanged.

Scheduled root invocations drop to `www-data` before starting Go. The launcher
sets the matching identity environment and retains niceness 19. Go directly
starts the absolute virtualenv Flask executable. Checked bootstrap failures
produce fixed startup diagnostics. The waiting root wrapper reports a generic
`command_failed` record when its child fails, including failures in privilege
dropping, while retaining the child's exit code. It does not describe every
command failure as a startup failure. It forwards TERM/INT to its child and
waits for cleanup before exiting. Cron's existing output/mail plumbing and
Exim configuration remain unchanged.

The full-image rehearsal includes synthetic real queue and cron interviews.
The queue returns a known result after emitting stdout/stderr markers. The
cron interview saves a changed counter while emitting a response and stderr;
it also checks UID/GID, identity environment and niceness. Missing configuration
and a missing privilege-drop executable exercise failure records. A long-running
real interview checks that TERM/INT sent only to the root launcher stop Go,
Flask and a spawned descendant, preserve the child's termination status and
emit only fixed records. Diagnostic
files, gzip logs and container stdout/stderr are scanned for the synthetic
private markers. Separate controls prove that the scan detects raw and
compressed markers across read boundaries. These additions require native CI;
source assertions alone are not an acceptance result.

Native CI on a32541b4d passed the interview launch, result, failure and shutdown
checks described above. The [maintenance extension](maintenance-capture-go.md)
now wraps parent scheduled scripts and exercises local copies, backup and
restore separately. A stream capture cannot filter bytes copied from files.
Historical logs must not be deleted merely to make a privacy test pass.
Manual Python cron invocation remains outside the supported launch path.
The Go mail replacement remains deferred.
