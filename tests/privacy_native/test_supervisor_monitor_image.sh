#!/bin/bash
# Test the compiled monitor using an already-present Supervisor/Python 3.14 image.
set -euo pipefail
if [ "$#" -ne 1 ]; then
    printf '%s\n' 'usage: bash tests/privacy_native/test_supervisor_monitor_image.sh IMAGE' >&2
    exit 64
fi
REVIEW_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REVIEW_IMAGE=$(docker image inspect --format '{{.Id}}' "$1")
REVIEW_ARCH=$(docker image inspect --format '{{.Architecture}}' "$REVIEW_IMAGE")
case "$REVIEW_ARCH" in amd64|arm64) ;; *) exit 64 ;; esac
REVIEW_BINARY="$REVIEW_ROOT/tests/.privacy-build/privacy-monitor-linux-$REVIEW_ARCH"
test -x "$REVIEW_BINARY"
REVIEW_PROCESS="$REVIEW_ROOT/tests/.privacy-build/privacy-process-linux-$REVIEW_ARCH"
REVIEW_DIAGNOSTIC="$REVIEW_ROOT/tests/.privacy-build/privacy-diagnostic-linux-$REVIEW_ARCH"
test -x "$REVIEW_PROCESS"
test -x "$REVIEW_DIAGNOSTIC"
docker run --rm --init --pull=never --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges --user www-data \
    --tmpfs /tmp:rw,nosuid,nodev \
    --mount "type=bind,src=$REVIEW_ROOT,dst=/review,readonly" \
    --mount "type=bind,src=$REVIEW_BINARY,dst=/usr/share/docassemble/webapp/privacy-monitor,readonly" \
    --mount "type=bind,src=$REVIEW_PROCESS,dst=/usr/share/docassemble/webapp/privacy-process,readonly" \
    --mount "type=bind,src=$REVIEW_DIAGNOSTIC,dst=/usr/share/docassemble/webapp/privacy-diagnostic,readonly" \
    --entrypoint /usr/bin/env "$REVIEW_IMAGE" PYTHONDONTWRITEBYTECODE=1 \
    python3.14 -B /review/tests/privacy_native/check_supervisor_monitor_image.py
