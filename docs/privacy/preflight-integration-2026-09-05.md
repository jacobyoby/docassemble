# Native preflight integration — 2026-09-05

Status: the Go configuration preflight is integrated and locally verified in
`fix/jos81-private-logging`, based on
`63d22c44b7bd008a521f0bcb8ab442b2143ee557`. **The candidate is uncommitted and
not deployed.** This record covers the native preflight and its launcher
integration; it does not close the [full release gates](review-2026-09-05.md).

## Changes and review findings

The three native launchers call `privacy-preflight` before `privacy-process`.
The Dockerfile builds all three standard-library Go executables and installs
them root-owned, mode 0755. Its native helper data directory now contains only
the nginx lifecycle configuration. The former Python preflight moved unchanged
to `tests/privacy_native/reference/check_native_config.py`; all four replaced
native Python helpers are now test references. The new application Python
logging draft remains an unresolved implementation requirement.

The interrupted integration left three launcher exec-failure tests failing:
their injection still lived in the retired Python preflight fixture. Moved that
injection into the Go-helper fixture, retained the same assertions, and checked
its argument routing. The fixture still emits synthetic private markers on both
streams to verify bootstrap suppression. The preflight reference harness now
resolves its test import from its new location without `PYTHONPATH`.

Linux launcher tests now exercise the actual Go preflight and capture code,
including standard/exposed uWSGI and the log role. Only the selected profile is
safe in each positive case; the alternatives deliberately reject. Unsafe
selected files and missing preflight helpers must stop before the native
program creates its startup marker. A separate real-nginx smoke script checks
the compiled production helper rather than a test binary.

## Machine feedback

| Check | Verified result | Boundary |
| --- | --- | --- |
| `bash tests/verify_privacy.sh` | Passed: formatting, vet, race tests, module verification, host and static Linux amd64/arm64 builds, 122 native and 84 application Python tests, shell syntax, diff whitespace | macOS host; Linux-specific tests run separately |
| Three 10-second fuzz targets | Passed: diagnostic 936,101 executions; aggregation 200,873; preflight 126,091 | Bounded fuzzing, not exhaustive proof |
| All Go packages on Linux with `-race -count=1 -timeout=30s` | Passed, including preflight subprocess lifecycle and both uWSGI launcher paths | Real Linux processes/pipes/signals; synthetic native programs |
| Linux `go vet ./...` | Passed | Go candidate only |
| Linux-targeted `govulncheck@v1.7.0 ./...` | No vulnerabilities found | Reachable Go code and dependencies, not the complete service image |
| Real nginx `-T` smoke | Both fixtures pass native inspection; Go helper accepts safe configuration with exit 0 and rejects unsafe access logging with exit 70; both helper paths emit zero bytes | Configuration inspection only, no service boot or requests |
| Frozen native reference hashes | All four unchanged | Preserves prior design/test material |
| Final hygiene and documentation | 81 candidate files checked; no supported credential markers, generated junk, broken local documentation links, or trailing whitespace; workflow YAML parsed; all Go files below 500 lines | Scoped checks, not a full secrets or application security audit |

The canonical suite gained shell syntax validation for the new smoke script
after its complete passing run; that added check and the revised smoke script
were also run separately. No production code changed after those Go builds and
checks. The smoke test's native success controls ensure its unsafe rejection is
not merely an nginx syntax or installation error.

The smoke command is reproducible with a caller-selected, already-present image:

```sh
bash tests/verify_privacy.sh
bash tests/privacy_native/test_nginx_preflight_image.sh EXISTING_IMAGE
```

This local run used nginx 1.28.3 in the cached Linux arm64 image
`sha256:c0b0a707a6cd2149d5777ee83af1ea1de544210e597371eac93e67a1503c395c`.
Containers had no network, a read-only root filesystem, no capabilities,
no-new-privileges, and an init reaper. Source/configuration was read-only;
host-side caches and evidence stayed inside this worktree. No production
configuration, services, logs, or persistent volumes were changed.

Evidence is under `tests/.privacy-build/preflight-review/`: the original fixture
failure, repaired launcher tests, complete canonical output, Linux CLI and full
race logs, Linux vet, vulnerability scan, real-nginx smoke, hygiene results,
before-edit copies, and source hashes. The older `runner-review`, aggregator,
and startup records remain historical and are not current source manifests.

## Remaining release work

At this stage, the complete candidate still needed a compliant application logging boundary,
observable sink/process failures, full service and retained-output coverage,
an atomic installer for the existing persistent volume, and tested rollback.
The full candidate image has not been built and booted. The current GitHub
checks are for the unchanged base, not this patch; the candidate workflow has
not run remotely. Complete those requirements before deployment.

Later [process monitoring](process-monitor-go.md) and [application logger
replacement](application-logger-go.md) address the corresponding source-level
gaps. The [release review](review-2026-09-05.md) tracks current acceptance work.
