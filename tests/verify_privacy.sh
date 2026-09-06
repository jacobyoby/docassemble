#!/bin/bash
# Focused candidate checks only; this does not establish full-install readiness.
set -euo pipefail
REVIEW_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REVIEW_ROOT"
REVIEW_BUILD="$REVIEW_ROOT/tests/.privacy-build"
mkdir -p "$REVIEW_BUILD/go-cache" "$REVIEW_BUILD/go-mod" "$REVIEW_BUILD/go-tmp" "$REVIEW_BUILD/tmp"
export GOCACHE="$REVIEW_BUILD/go-cache" GOMODCACHE="$REVIEW_BUILD/go-mod"
export GOTMPDIR="$REVIEW_BUILD/go-tmp" TMPDIR="$REVIEW_BUILD/tmp"
export TEST_TELEMETRY_DIR="$REVIEW_BUILD/telemetry"
export GOTOOLCHAIN=local GOPROXY=off PYTHONDONTWRITEBYTECODE=1
# Keep race detection enabled without its artificial one-second fixture exit
# sleep, which would exceed the shortened synthetic native shutdown deadlines.
export GORACE=atexit_sleep_ms=0
unset PYTHONPATH
test -z "$(gofmt -l Docker/privacy-diagnostic)"
go -C Docker/privacy-diagnostic vet ./...
go -C Docker/privacy-diagnostic test -race -count=1 -timeout 30s ./...
go -C Docker/privacy-diagnostic test -run '^$' -fuzz FuzzParseHasFixedBoundedOutput \
    -fuzztime=10s -parallel=2
go -C Docker/privacy-diagnostic test ./internal/aggregate -run '^$' \
    -fuzz FuzzFragmentationPreservesCounters -fuzztime=10s -parallel=2
go -C Docker/privacy-diagnostic test ./internal/preflight -run '^$' \
    -fuzz FuzzParsersReturnOnlyFixedErrors -fuzztime=10s -parallel=2
go -C Docker/privacy-diagnostic test ./internal/monitor -run '^$' \
    -fuzz FuzzEventRecordsHaveOnlyFixedOutput -fuzztime=10s -parallel=2
go -C Docker/privacy-diagnostic mod verify
go -C Docker/privacy-diagnostic build -trimpath -buildvcs=false -o "$REVIEW_BUILD/privacy-diagnostic" .
go -C Docker/privacy-diagnostic build -trimpath -buildvcs=false -o "$REVIEW_BUILD/privacy-process" ./cmd/privacy-process
go -C Docker/privacy-diagnostic build -trimpath -buildvcs=false -o "$REVIEW_BUILD/privacy-preflight" ./cmd/privacy-preflight
go -C Docker/privacy-diagnostic build -trimpath -buildvcs=false -o "$REVIEW_BUILD/privacy-monitor" ./cmd/privacy-monitor
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go -C Docker/privacy-diagnostic build \
    -trimpath -buildvcs=false -o "$REVIEW_BUILD/privacy-diagnostic-linux-amd64" .
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go -C Docker/privacy-diagnostic build \
    -trimpath -buildvcs=false -o "$REVIEW_BUILD/privacy-diagnostic-linux-arm64" .
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go -C Docker/privacy-diagnostic build \
    -trimpath -buildvcs=false -o "$REVIEW_BUILD/privacy-process-linux-amd64" ./cmd/privacy-process
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go -C Docker/privacy-diagnostic build \
    -trimpath -buildvcs=false -o "$REVIEW_BUILD/privacy-process-linux-arm64" ./cmd/privacy-process
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go -C Docker/privacy-diagnostic build \
    -trimpath -buildvcs=false -o "$REVIEW_BUILD/privacy-preflight-linux-amd64" ./cmd/privacy-preflight
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go -C Docker/privacy-diagnostic build \
    -trimpath -buildvcs=false -o "$REVIEW_BUILD/privacy-preflight-linux-arm64" ./cmd/privacy-preflight
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go -C Docker/privacy-diagnostic build \
    -trimpath -buildvcs=false -o "$REVIEW_BUILD/privacy-monitor-linux-amd64" ./cmd/privacy-monitor
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go -C Docker/privacy-diagnostic build \
    -trimpath -buildvcs=false -o "$REVIEW_BUILD/privacy-monitor-linux-arm64" ./cmd/privacy-monitor
# On non-Linux hosts the lifecycle tests are run separately in a Linux sandbox.
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go -C Docker/privacy-diagnostic build ./...
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go -C Docker/privacy-diagnostic build ./...
python3.14 -B -m unittest discover -s tests/privacy_native -v
# Historical Python draft assertions are retained against pinned references.
# Current application logger behavior runs through Go in the Linux suite.
python3.14 -B -m unittest discover -s tests/privacy_logging -v
bash -n Docker/run-nginx.sh
bash -n Docker/run-uwsgi.sh
bash -n Docker/run-uwsgilog.sh
bash -n Docker/run-celery.sh
bash -n Docker/run-celery-single.sh
bash -n Docker/run-websockets.sh
bash -n Docker/run-cron.sh
bash -n Docker/process-email.sh
bash -n Docker/initialize.sh
bash -n tests/verify_privacy.sh
bash -n tests/privacy_native/test_nginx_preflight_image.sh
bash -n tests/privacy_native/test_supervisor_monitor_image.sh
bash -n tests/privacy_native/test_uwsgi_image.sh
bash -n tests/privacy_native/test_rotation_image.sh
bash -n tests/privacy_native/test_install_image.sh
bash -n tests/privacy_native/fixtures/application-command.sh
bash -n tests/privacy_native/fixtures/rotation-command.sh
git diff --check
