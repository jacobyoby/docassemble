#!/bin/bash
# Check the compiled Go preflight against real nginx -T in a disposable image.
# The caller supplies an already-present image; this script never pulls one.
set -euo pipefail
if [ "$#" -ne 1 ]; then
    printf '%s\n' 'usage: bash tests/privacy_native/test_nginx_preflight_image.sh IMAGE' >&2
    exit 64
fi
REVIEW_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REVIEW_IMAGE=$(docker image inspect --format '{{.Id}}' "$1")
REVIEW_ARCH=$(docker image inspect --format '{{.Architecture}}' "$REVIEW_IMAGE")
case "$REVIEW_ARCH" in amd64|arm64) ;; *) exit 64 ;; esac
REVIEW_BUILD="$REVIEW_ROOT/tests/.privacy-build"
REVIEW_BINARY="$REVIEW_BUILD/privacy-preflight-linux-$REVIEW_ARCH"
test -x "$REVIEW_BINARY"
REVIEW_TEMP=$(mktemp -d "$REVIEW_BUILD/nginx-preflight.XXXXXX")
trap 'rmdir "$REVIEW_TEMP"' EXIT
for REVIEW_CASE in safe unsafe; do
    REVIEW_CONTAINER=(--rm --init --pull=never --network none --read-only --cap-drop ALL
        --security-opt no-new-privileges --user "$(id -u):$(id -g)"
        --tmpfs /tmp:rw,nosuid,nodev
        --mount "type=bind,src=$REVIEW_BINARY,dst=/review/privacy-preflight,readonly"
        --mount "type=bind,src=$REVIEW_ROOT/tests/privacy_native/fixtures/nginx-preflight.conf,dst=/etc/nginx/nginx.conf,readonly"
        --mount "type=bind,src=$REVIEW_ROOT/tests/privacy_native/fixtures/nginx-preflight-$REVIEW_CASE.conf,dst=/etc/nginx/preflight-override.conf,readonly")
    # Both fixtures must pass native inspection. Otherwise a generic exit 70
    # could hide a syntax/installation failure instead of policy rejection.
    REVIEW_STATUS=0
    docker run "${REVIEW_CONTAINER[@]}" --entrypoint /usr/sbin/nginx "$REVIEW_IMAGE" -T -e stderr \
        > "$REVIEW_TEMP/native-output" 2> "$REVIEW_TEMP/native-error" || REVIEW_STATUS=$?
    if [ "$REVIEW_STATUS" -ne 0 ]; then
        printf 'nginx native %s control failed: exit %s; inspect %s\n' \
            "$REVIEW_CASE" "$REVIEW_STATUS" "$REVIEW_TEMP" >&2
        trap - EXIT
        exit 1
    fi
    rm "$REVIEW_TEMP/native-output" "$REVIEW_TEMP/native-error"
    REVIEW_STATUS=0
    docker run "${REVIEW_CONTAINER[@]}" --entrypoint /review/privacy-preflight "$REVIEW_IMAGE" nginx \
        > "$REVIEW_TEMP/output" 2> "$REVIEW_TEMP/error" || REVIEW_STATUS=$?
    REVIEW_EXPECTED=0
    if [ "$REVIEW_CASE" = unsafe ]; then REVIEW_EXPECTED=70; fi
    if [ "$REVIEW_STATUS" -ne "$REVIEW_EXPECTED" ] || [ -s "$REVIEW_TEMP/output" ] || [ -s "$REVIEW_TEMP/error" ]; then
        printf 'nginx preflight %s failed: exit %s, expected %s; inspect %s\n' \
            "$REVIEW_CASE" "$REVIEW_STATUS" "$REVIEW_EXPECTED" "$REVIEW_TEMP" >&2
        trap - EXIT
        exit 1
    fi
    rm "$REVIEW_TEMP/output" "$REVIEW_TEMP/error"
    printf 'nginx preflight %s: native control passed, exit %s, no output\n' "$REVIEW_CASE" "$REVIEW_STATUS"
done
