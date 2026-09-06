# JOS-81 target inventory

Read-only observations collected on `forms-vps` around 2026-09-06 02:31 UTC
(September 5 Pacific). No candidate files were installed, no services restarted,
and no logs or application data were copied. This resolves target paths and
reveals configuration differences; it does not prove installation or rollback.

## Confirmed runtime

| Property | Forma | Retiring demo |
| --- | --- | --- |
| Container | `docassemble-forma` | `docassemble-demo` |
| Architecture | Linux amd64 | Linux amd64 |
| Container role | `all` | `all` |
| Persistent volume at `/usr/share/docassemble` | `da_forma`, read/write | `da_live`, read/write |
| Active uWSGI profile | `config/docassemble.ini` | `config/docassemble.ini` |
| uWSGI application mount | `/nj` | `/` |
| Python | 3.14.4 | 3.14.4 |
| uWSGI / Supervisor | 2.0.31 / 4.3.0 | 2.0.31 / 4.3.0 |
| nginx / syslog-ng / logrotate | 1.28.3 / 4.8.1 / 3.22.0 | 1.28.3 / 4.8.1 / 3.22.0 |

Both containers use image ID
`sha256:c0b0a707a6cd2149d5777ee83af1ea1de544210e597371eac93e67a1503c395c`.
The running uWSGI executable is
`/usr/share/docassemble/local3.14/bin/uwsgi`; the rendered profile names
`/usr/share/docassemble/local3.14/bin/python` and the same virtualenv. Interpreter
inspection, without importing the application, resolves its package directory
to `/usr/share/docassemble/local3.14/lib/python3.14/site-packages`.

The webapp directory and root are root-owned mode 0755. The log and uWSGI runtime
directories are owned by `www-data` (uid/gid 33), mode 0755. All four privacy
binaries, the lifecycle include and `run-uwsgilog.sh` are absent. Image changes
alone would be masked beneath the existing volume.

Both configurations select nginx, an HTTPS load balancer, no local HTTPS or
Let's Encrypt, and omit read-only filesystem mode. Observed container environment
agrees on the load balancer and route prefix. Configuration rendering and
startup behavior must still be exercised against the candidate.

## Preserve target differences

- Forma has an additional enabled `formapauperis` nginx site. Its config and
  symlink are now explicit protected catalog entries. Demo instead customizes
  `nginx-http.dist` with additional public hostnames and
  `/etc/nginx/form_rewrite_rules.conf`; that include is also protected. Preserve
  all existing nginx templates and validate their rendered outputs. Do not
  replace demo's HTTP template with the unmodified repository template.
- Both installed initializers lack the fork base's unrelated Apache HTTPS-port
  changes. Apply only the privacy diff to the installed initializer; copying
  the entire candidate would also change that unrelated behavior.
- Both targets already have `sharedscripts` in the application logrotate stanza;
  Forma differs only in its placement. Keep exactly one directive and preserve
  the separate mail stanza. The installed rotation callback matches the source.
- The ordinary launchers, application logger, uWSGI templates/profiles,
  Supervisor configuration and syslog input templates match the repository base.
  The nginx main configuration is a distro-style file rather than the base's
  empty placeholder; its effective directives still need comparison when the
  candidate is rehearsed.

Both targets use `/etc/syslog-ng/syslog-ng.conf` as a symlink into the volume;
the forwarding include is absent. The active files share hash
`b267e9e9a1b9e75536205511b49744e8189a6e031fc720c29ab2cce9e77db18a`, which
matches neither shipped syslog template. A follow-up source comparison finds
`system()` and `internal()` inputs, ordinary system-log destinations and a
`/etc/syslog-ng/conf.d/*.conf` include; the main file has none of the collector
template's application TCP routes. Its effective includes and required routing
still need review before any replacement. Preserve the existing system logging
configuration unless a reviewed privacy requirement calls for a specific change.

Supervisor reports `syslogng` stopped on Forma and running on demo. nginx, uWSGI,
both Celery workers, websockets, cron
and Exim are running on both. The privacy monitor and `uwsgilog` are not configured.
Demo reports Apache `FATAL` while Forma reports it stopped; nginx is the configured
web server. These are baseline observations, not changes caused by this candidate.
Do not start every role-compatible service merely to make the two targets alike.

## Evidence and remaining work

Private local evidence is in `tests/.privacy-build/target-review/`: selected
Docker identity/mount metadata, catalog path hashes and ownership, process path
observations, safe configuration selections, native versions, and selected source
diffs. Root could not inspect some other-user `/proc` entries; a second probe as
`www-data` verified the active uWSGI executable and profile without expanding
container capabilities. `supervisorctl --version` was unsupported; the successful
`supervisord --version` check reported 4.3.0 on both targets.

The path inventory covers all 29 required files and 26 state entries. Protected
regular-file hashes and selected link metadata were read; protected directory
trees, uploads and historical logs were not recursively read or snapshotted.
Counter-file contents were not read. Free space was approximately 112.5 GB on
the volume filesystem, which does not establish snapshot size or restore safety.

Still required: a private restorable snapshot, complete protected-tree verification,
target-specific rendered configuration checks, installation and rollback rehearsal,
full application/output coverage and exact candidate commit/CI. Earlier native
fixtures used nginx 1.30.4 and syslog-ng 4.11.0, so their passes alone do not prove
the installed versions above. Go mail replacement and Exim changes remain
[deferred](deferred-mail-go.md).
