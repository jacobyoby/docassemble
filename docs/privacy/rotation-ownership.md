# Counter-file rotation and forwarding

Status: the candidate's overlapping rotation ownership and Celery collector
misrouting are repaired and locally verified. **Not deployed.** Complete
installation, callback behavior, backup/restore and retained-output coverage
remain [release gates](review-2026-09-05.md). The [mail replacement](deferred-mail-go.md)
remains deferred.

## Source repair

Supervisor and the syslog collector previously wrote the same four filenames.
Supervisor rotated these files by size while logrotate could independently
rename them. The candidate now gives the local counter streams distinct names:

| Component | Local file owned by Supervisor | Collector file owned by logrotate |
| --- | --- | --- |
| Celery | `privacy-celery.log` | `worker.log` |
| Single-queue Celery | `privacy-celerysingle.log` | `single_worker.log` |
| uWSGI | `privacy-uwsgi.log` | `uwsgi.log` |
| Websockets | `privacy-websockets.log` | `websockets.log` |

All paths are under `/usr/share/docassemble/log`. The forwarding file sources
move with the local files and retain their existing program labels. Initialization
precreates the four new files before its ownership pass, alongside the existing
legacy files. This prevents a root Supervisor from creating them after the
`www-data` ownership pass under a restrictive umask. Actual installed modes and
ownership still require installation acceptance.

The native test also showed `celerysingle` records entering `worker.log` through
the existing unanchored `celery` filter. The collector now matches `^celery$`.
The [syslog-ng filter documentation](https://syslog-ng.github.io/admin-guide/080_Log/030_Filters/005_Filter_functions/009_program.html)
confirms that `program()` accepts a regular expression; the real native test
verifies the resulting separation.

Existing `uwsgilog.log`, `nginx-safe.log` and `privacy-monitor.log` already have
distinct Supervisor destinations. Supervisor keeps its production 5 MB limit
and seven backups. Existing collector destinations, logrotate rules, Apache
rotation and the postrotate callback remain otherwise unchanged. Legacy log
rotation can still restart application services through that callback; this
repair does not claim restart-free production rotation.

## Verification

Five ownership tests cover external writer/rotator exclusion, forwarding and
collector mapping, precreation order, bounded Supervisor rotation and separate
Celery routing. The first run failed on the original ownership/mapping conflict;
a later fail-first test reproduced the collector filter overlap.

The native fixture uses real Supervisor 4.3.0, logrotate 3.22.0 and syslog-ng
4.11.0 with the freshly built Go runner. All application output is synthetic.
It runs the actual initialization precreation/ownership fragment in a private
directory under umask 0077, then uses the four actual forwarding source lines
and collector filter/destination rules over loopback TCP. Local capture and
collector files share one directory, matching the ownership hazard.

The fixture reduces Supervisor's rollover threshold to 256 bytes to exercise
seven backups promptly; source checks retain the production 5 MB requirement.
It pauses Supervisor for less than 4.5 seconds while forcing actual logrotate
over the legacy files. All capture-file inodes and hashes must remain unchanged.
The original callback is replaced by an inert test hook. The test explicitly
signals syslog-ng to reopen its collector files, then emits an 8,192-line burst
per component. Each newly created active collector file must receive the new
counter totals with the correct component and without private markers. Final
daemon liveness and the original four capture PID/start-time identities must
remain stable across a settled observation before deliberate shutdown. Final
capture archives are inspected after Supervisor stops, rejecting partial JSON
records and more than seven backups.

The disposable container has no network beyond loopback, fixed local hostname
resolution, a read-only root/source mount, no capabilities, no privilege
escalation, no Docker log retention, 512 MiB memory, 128 PIDs, and 64 MiB of
non-executable temporary storage. Inner and outer command deadlines and named
container cleanup bound failures. The native packages are test-only additions
to the existing protocol fixture image, not production dependencies.

Evidence: `tests/.privacy-build/rotation-review/` contains `fail-first.log`,
`filter-fail-first.log`, the native misrouting reproduction `native-routing.log`,
the accepted run `native-final.log`, image build/version evidence, canonical
`verification.log`, source hashes and the final hygiene record. The immutable
local Linux arm64 image is
`sha256:53259b84ca8ed8b8c0affc26a7b5f60d7be7239daf2fe54852ab2e18bf4074d1`.
The initial syslog startup timeout was resolved by providing local hostname
resolution inside the network-isolated fixture; the test's syntax deadline
remained unchanged.

```sh
bash tests/verify_privacy.sh
docker build -t privacy-candidate-check \
  -f tests/privacy_native/fixtures/privacy-check.Dockerfile tests/privacy_native/fixtures
docker build -t privacy-rotation-check \
  -f tests/privacy_native/fixtures/rotation-check.Dockerfile tests/privacy_native/fixtures
bash tests/privacy_native/test_rotation_image.sh privacy-rotation-check
```

These checks establish native ownership, rollover and continued forwarding for
the selected routes. They do not prove lossless forwarding of every snapshot,
production callback behavior, full application operation, historical-log
treatment, remote transport deployment, installation over existing volumes or
rollback. No historical logs were removed and no mail work was resumed.
