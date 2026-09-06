#!/bin/bash
# Real uWSGI acceptance only; uses synthetic application/configuration modules.
set -euo pipefail
if [ "$#" -ne 1 ]; then
    printf '%s\n' 'usage: bash tests/privacy_native/test_uwsgi_image.sh IMAGE' >&2
    exit 64
fi
REVIEW_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REVIEW_BUILD="$REVIEW_ROOT/tests/.privacy-build"
mkdir -p "$REVIEW_BUILD/go-cache" "$REVIEW_BUILD/go-mod" "$REVIEW_BUILD/go-tmp" "$REVIEW_BUILD/tmp"
export GOCACHE="$REVIEW_BUILD/go-cache" GOMODCACHE="$REVIEW_BUILD/go-mod"
export GOTMPDIR="$REVIEW_BUILD/go-tmp" TMPDIR="$REVIEW_BUILD/tmp"
export TEST_TELEMETRY_DIR="$REVIEW_BUILD/telemetry" GOTOOLCHAIN=local GOPROXY=off
export PYTHONDONTWRITEBYTECODE=1
REVIEW_IMAGE=$(docker image inspect --format '{{.Id}}' "$1")
REVIEW_ARCH=$(docker image inspect --format '{{.Architecture}}' "$REVIEW_IMAGE")
case "$REVIEW_ARCH" in amd64|arm64) ;; *) exit 64 ;; esac
REVIEW_RUN=$(mktemp -d "$REVIEW_BUILD/uwsgi-run.XXXXXXXX")
REVIEW_NAME="jos81-$(basename "$REVIEW_RUN")"
cleanup() {
    REVIEW_STATUS=$?
    trap - EXIT
    if ! python3.14 -B - "$REVIEW_NAME" <<'PY'
import subprocess
import sys
try:
    subprocess.run(['docker', 'rm', '--force', sys.argv[1]], timeout=10,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    remaining = subprocess.run(['docker', 'ps', '-aq', '--filter', 'name=^/' + sys.argv[1] + '$'],
                               check=True, capture_output=True, timeout=10)
    assert not remaining.stdout.strip(), 'test container survived cleanup'
except (subprocess.SubprocessError, AssertionError):
    print('uWSGI test container cleanup failed', file=sys.stderr)
    sys.exit(125)
PY
    then
        if [ "$REVIEW_STATUS" -eq 0 ]; then REVIEW_STATUS=125; fi
    fi
    exit "$REVIEW_STATUS"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Rebuild from this checkout so a standalone run cannot validate stale binaries.
for REVIEW_COMPONENT in process preflight diagnostic; do
    REVIEW_PACKAGE="./cmd/privacy-$REVIEW_COMPONENT"
    if [ "$REVIEW_COMPONENT" = diagnostic ]; then REVIEW_PACKAGE=.; fi
    CGO_ENABLED=0 GOOS=linux GOARCH="$REVIEW_ARCH" go -C "$REVIEW_ROOT/Docker/privacy-diagnostic" build \
        -trimpath -buildvcs=false -o "$REVIEW_RUN/privacy-$REVIEW_COMPONENT" "$REVIEW_PACKAGE"
done
printf 'uWSGI test image: %s\n' "$REVIEW_IMAGE"
go version
shasum -a 256 "$REVIEW_RUN"/privacy-*
REVIEW_COMMAND=(docker run --name "$REVIEW_NAME" --rm --init --pull=never --network none --read-only --cap-drop ALL \
    --log-driver none --memory 512m --memory-swap 512m --pids-limit 128 \
    --security-opt no-new-privileges --user www-data \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m \
    --tmpfs /var/run/uwsgi:rw,nosuid,nodev,noexec,size=1m,uid=82,gid=82,mode=0700 \
    --tmpfs /usr/share/docassemble/config:rw,nosuid,nodev,noexec,size=1m,uid=82,gid=82,mode=0700 \
    --mount "type=bind,src=$REVIEW_ROOT,dst=/review,readonly" \
    --mount "type=bind,src=$REVIEW_RUN/privacy-process,dst=/usr/share/docassemble/webapp/privacy-process,readonly" \
    --mount "type=bind,src=$REVIEW_RUN/privacy-preflight,dst=/usr/share/docassemble/webapp/privacy-preflight,readonly" \
    --mount "type=bind,src=$REVIEW_RUN/privacy-diagnostic,dst=/usr/share/docassemble/webapp/privacy-diagnostic,readonly" \
    --entrypoint /usr/bin/env "$REVIEW_IMAGE" PYTHONDONTWRITEBYTECODE=1 \
    timeout -k 5 45 python3.14 -B /review/tests/privacy_native/check_uwsgi_image.py)
python3.14 -B - "${REVIEW_COMMAND[@]}" <<'PY'
import subprocess
import sys
try:
    result = subprocess.run(sys.argv[1:], timeout=55)
    sys.exit(result.returncode if result.returncode >= 0 else 128 - result.returncode)
except subprocess.TimeoutExpired:
    print('uWSGI test exceeded its outer deadline', file=sys.stderr)
    sys.exit(124)
PY
