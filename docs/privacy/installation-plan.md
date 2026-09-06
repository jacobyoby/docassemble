# JOS-81 installation and rollback inventory

GitHub tracking: [JOS-81, issue 22](https://github.com/jacobyoby/docassemble/issues/22).

Status: the [explicit file catalog](install-catalog.json) is checked by the
existing privacy test suite. It lists 30 required files, 26 rollback/state requirements
and 15 protected paths. It is a file list, not a new release framework or an
installer. [Native CI at 978d8fb63](https://github.com/jacobyoby/docassemble/actions/runs/34008439014)
passed installation and rollback for the prior 29-file catalog. The added
`run-cron.sh` entry and real queue/cron acceptance require their own candidate
CI. Production has not been changed. The
[release review](review-2026-09-05.md) still blocks deployment. This inventory
does not resume the [deferred Go mail replacement](deferred-mail-go.md).

The native amd64 CI job runs `bash tests/privacy_native/test_install_image.sh`
against the exact image digest recorded in the target inventory. It boots a
fresh volume with synthetic data, installs only the non-mail catalog, and checks
custom routes, real application responses, bounded counters, protected files,
and rollback metadata/service states. It does not publish an image or deploy.
The local rehearsal reached a working stock application and custom routes, but
GNU tar failed because both local user-mode emulators lack `openat2`. No candidate
files were installed in that attempt and its partial archive is not rollback
evidence. The first native CI run on PR #23 passed installation, real/custom
routes, counter validation and protected-file checks, but tar rejected restoring
the `/var/run/uwsgi` directory through the image's `/var/run` link. The rehearsal
now restores directory metadata explicitly and archives only files/links. Native
CI must pass rollback before claiming complete installation/rollback acceptance;
the real queue/cron additions, outer scheduled commands, independent writes and
backup/restore remain coverage requirements. See [interview-cron capture](cron-capture-go.md).

Existing `tools/deployCore.sh` copies in the NJForms release worktrees export
and install only the base/webapp packages, back up those two package directories
and touch the WSGI entrypoint. They do not deliver the complete native boundary.
Their `.git` directory check also rejects linked worktrees. Those other
worktrees were inspected read-only and are unchanged.

## Coherent non-mail installation set

| Source in this worktree | Required installed state |
| --- | --- |
| `Docker/privacy-diagnostic/` | Four architecture-matched binaries in `${DA_ROOT}/webapp`: `privacy-diagnostic`, `privacy-process`, `privacy-preflight`, `privacy-monitor`; root-owned, mode 0755 |
| `Docker/run-nginx.sh`, `run-uwsgi.sh`, `run-uwsgilog.sh`, `run-celery.sh`, `run-celery-single.sh`, `run-websockets.sh`, `run-cron.sh`, `initialize.sh` | Corresponding installed scripts under `${DA_ROOT}/webapp` |
| `docassemble_webapp/docassemble/webapp/log_initialize.py` | Current comments-only module in the actual service virtualenv, installed together with native capture |
| Four `Docker/config/docassemble*.ini*` profiles/templates | Input templates and correctly rendered active profiles under `${DA_ROOT}/config` |
| `Docker/nginx.conf`, `Docker/privacy/nginx-lifecycle.conf`, nginx site templates | `/etc/nginx/nginx.conf`, `/usr/local/lib/docassemble-privacy/nginx-lifecycle.conf`, rendered sites and enabled symlinks |
| `Docker/docassemble-supervisor.conf` | `/etc/supervisor/conf.d/docassemble.conf`, with capture, monitor, stream ownership and shutdown waits |
| `Docker/docassemble-syslog-ng.conf`, `Docker/syslog-ng.conf` | Installed inputs under `${DA_ROOT}/webapp`; preserve existing system syslog configuration or select collector/forwarder only when the verified role requires it; active path `${DA_ROOT}/syslogng/syslog-ng.conf` and forwarding include `/etc/syslog-ng/conf.d/docassemble.conf` |
| `Docker/docassemble.logrotate` and existing rotation callback | Reviewed rotation ownership in `/etc/logrotate.d/docassemble` and matching installed callback |

The catalog includes the unchanged `syslog-ng-docker.conf` forwarding base as
a required input. It covers collector/forwarder inputs, preservation of existing
system syslog configuration, the main configuration symlink and forwarding-include
absence/presence. It also names nginx enabled
links, the certificate marker, the affected logger bytecode only, runtime-directory
metadata and all seven Supervisor counter files. Runtime sockets and PID files
must be recreated by clean starts; historical logs must retain their contents.

`DA_ROOT` and `SITE_PACKAGES` in the catalog describe the standard source
layout. The actual service virtualenv, active package path and volume mounts
must be resolved before using it. Current source profiles contain standard
absolute paths, so this catalog does not establish support for a custom root.
The existing test suite checks source existence, protected-path exclusion,
Supervisor command/counter coverage and actual nginx/uWSGI generated paths.
Per-architecture source hashes are review evidence, not target-installation proof.

The [read-only target inventory](target-inventory-2026-09-05.md) now confirms
the standard root, Python 3.14 virtualenv, active uWSGI package path and persistent
volume mounts on both running containers. It also found target-specific nginx
configuration. The catalog's `existing: preserve-and-validate` entries are
required rendering inputs: retain their existing bytes and metadata, then
validate the resulting effective configuration. Use the source template only
when the target is absent. Do not overwrite a customized template just because
it differs from the source hash. Unsafe retained configuration still blocks
installation; this policy is not permission to bypass preflight.

For `existing: apply-privacy-diff`, apply only this candidate's privacy changes
to the snapshotted target initializer. Preserve unrelated target lines. Record
the actual resulting hash and inspect the diff before installation; a source
hash alone cannot verify that result. Other entries require reviewed replacement
and the listed ownership/mode. These are review instructions for the existing
copy/patch tools, not an implemented installer.

`initialize.sh` renders the main and log uWSGI profiles; `run-nginx.sh` renders
the site configurations. Read-only mode skips generation. Existing volumes
can mask image-installed binaries, templates and Python packages. Exposed
profiles and Supervisor paths still assume `/usr/share/docassemble`; reconcile
actual runtime paths explicitly before any custom-root installation.

## Cutover and rollback requirements

1. Create a manifest and rollback snapshot covering binaries, scripts, package
   state, templates, rendered files, symlink targets, ownership and permissions.
   Preserve application data, user configuration, certificates and historical
   logs outside broad replacement or deletion operations.
2. Quiesce ingress and scheduled producers, stop the websocket/front end, drain
   workers and stop uWSGI services. Keep the monitor until affected services
   have stopped. Rehearse this order with actual service roles and deadlines.
   Precreate and assign ownership to every counter file before restarting any
   service. Current initialization starts Celery before its later ownership
   block, so that block cannot serve as the installer's pre-start guarantee.
   Record actual service states: Forma's `syslogng` is currently stopped, while
   demo's is running. Their active file uses system/internal sources and differs
   from both shipped templates. Compare its includes and required role before
   replacing it. Do not infer the required startup set from `role=all` alone.
3. Install the coherent set while services are stopped. Validate hashes, ELF
   architecture, executable ownership, actual virtualenv paths and generated
   configurations. Do not invoke `initialize.sh` as a generic installer: it also
   performs unrelated initialization, backup and restore operations.
4. Start and verify the monitor, then applicable backends/workers and uWSGI.
   Confirm sockets and health before nginx reopens ingress. Exercise complete
   synthetic service, failure, output-retention and rotation acceptance.
5. Restore the entire manifest on failure and repeat acceptance. A package-only
   rollback can restore raw file logging. Keep ingress closed if the restored
   installation does not meet the selected privacy acceptance requirements.

## Unresolved artifact and retention boundaries

- The Dockerfile bulk-copies shell scripts and installs the whole webapp package.
  This would include the preserved `process-email.sh` and `process_email.py`
  capture edits. A non-mail release must explicitly define and verify those
  exclusions; the deferral note does not exclude bytes automatically. Shared
  Go components can remain intact without activating deferred mail work.
- [Rotation ownership is repaired](rotation-ownership.md): four local
  `privacy-*.log` files belong to Supervisor, while the legacy collector files
  retain logrotate. Install the matching forwarding input and exact Celery
  collector filter with these paths. The precreation/ownership pass must precede
  service startup. `uwsgilog` uses Supervisor rotation and needs no logrotate
  callback entry. Existing legacy callbacks can still restart application
  services; their full installed behavior remains an acceptance requirement.
- Frozen Python references and all test-only fixture dependencies must remain
  outside production artifacts. Cron output, independent file writes, log
  copies, backup/restore and monitor-sink health still require full coverage.
- A full image build alone cannot prove installation over the existing volume.
  Exact candidate commit/CI, complete installation and rollback evidence remain
  mandatory release gates.
