# Application logging through Go capture

Status: implemented in the uncommitted JOS-81 candidate; **not deployed**.
The application no longer installs its independent `docassemble.log` handler.
Its existing base logger writes to stderr, which the supported service
launchers feed into the Go capture process. The production change removes the
logging override; it adds no executable Python, runtime dependency, or new
configuration parser.

## Runtime boundary

`docassemble.webapp.app_initialize` still imports `log_initialize` at the same
point. That module now contains only explanatory comments. The existing
`docassemble.base.logger.default_logmessage` callback remains unchanged.
First-party source search found no consumers of the removed module's private
functions or `sys_logger` variable. The `docassemble.webapp.utils.logger`
re-export continues to use the base callback.

This removes the separate file-handler selection and its request-context
formatting. `log to std`, `LOGSERVER`, `log format`, and debug settings no
longer cause this entrypoint to open a log file or change the callback.
The configuration loader, including its cloud overlays and key normalization,
is untouched. This does not disable unrelated application configuration.

Supported nginx/uWSGI and application launchers must be installed together with
the [Go runner](native-runner-go.md), [startup diagnostic](startup-diagnostics.md),
and [Supervisor monitor](process-monitor-go.md). The Go process captures output
before, during, and after Python logger initialization. It emits cumulative
14-field counter snapshots with fixed component names. Per-message text,
exception details, and the old five-field application event records are not
retained. Application lines contribute to `unclassified`, `rejected`, or
`dropped`; native request metrics retain their existing profile rules.

The discarded Python handler's local `failure_count` is no longer a production
failure mechanism. Go owns the bounded output sink and process teardown;
delivery failures return 74, and Supervisor failure states provide fixed
reports when the monitor's own sink is available. Existing broken/full-sink,
shutdown, and acknowledgement tests remain applicable. Pipe acceptance is
still not a filesystem durability guarantee.

## Preserved reference and tests

The unreleased Python draft moved byte-for-byte into
`tests/privacy_logging/reference/`. Its two SHA-256 values are enforced by the
test loader:

| Reference | SHA-256 |
| --- | --- |
| `log_initialize.py` | `93f5e7b14ff7162edef330246bf99d30b34d96fadfac1314eaa593103dd89cb1` |
| `privacy_logging.py` | `0cf784e0d0e3997ba334b511c419fc47ed0f37d560777c1ad1b1c0dc39843634` |

All 84 existing draft tests retain their assertions. They now exercise this
frozen design reference and do not prove current production behavior. The
reference is outside the application package and is not installed by the
Dockerfile. The prior [application logging document](application-logging.md)
describes that historical design.

Current behavior is checked by `TestApplicationLoggerUsesOnlyCapturedStreams`
and `tests/privacy_native/fixtures/application-logger.py`. The fixture imports
the real base logger and executes the real `app_initialize.init_app` through
the first post-logging boundary. Configuration and downstream dependencies
are synthetic. It emits known private markers before setup, during setup,
after initialization, after standard-library logging reconfiguration, through
the base callback again, and directly to stdout.

The Linux test runs that fixture through the actual Go runner across five
capture profiles, four application contexts, two log-server settings, and two
debug settings: **80 combinations**, including mail. Each must exit successfully, leave the
independent log directory empty, preserve the base callback across reimport,
and produce exactly six unclassified lines in the final safe snapshot. No
private marker may appear in retained output. A direct fail-first run against
the previous draft stopped because initialization opened an independent file.

## Verification and remaining work

Run `bash tests/verify_privacy.sh`. On macOS, also run the Linux-specific Go
tests in the disposable Linux environment. Local September 5 verification
passed the 64-case Linux integration test, the complete Linux race suite,
Linux vet, and the unchanged 84 reference tests. The canonical suite passed
formatting, vet, race tests, four bounded fuzz targets, module verification,
host/Linux builds, 126 native/application-launcher Python tests, and the
reference suite separately. A fresh Linux-targeted Go vulnerability scan found
no vulnerabilities in the Go candidate; it does not cover all application
dependencies. The expanded real Supervisor test also ran the production
application launchers with real logger initialization and the original four
synthetic output controls. Each retained exactly ten unclassified lines and
reported its unexpected exit through the fixed monitor records.
Evidence and before-edit copies are in
`tests/.privacy-build/application-logger-review/`.

This closes the source-level new-Python and unconsumed-handler-counter issues
for this entrypoint. It does not establish full Flask/Celery/broker startup or
protect independently opened files, custom package handlers, or launchers
that still bypass Go capture. The later [mail capture record](mail-capture-go.md)
removes the direct `/tmp/mail.log` and verifies the expanded 80-case matrix;
actual mail storage and Exim transport acceptance remain open. The synthetic cron
context in the matrix is not an acceptance test of `Docker/run-cron.sh`.
Historical files and their rotation/copy/backup/restore paths remain separate
release work. A package-only installation would leave stderr unprotected in
an older service profile and must not be used.

The complete image, persistent-volume installation, tested rollback, monitor
health, retained-output acceptance, and CI for the exact release commit remain
required by the [release review](review-2026-09-05.md). No production service,
volume, log, or configuration was changed.
