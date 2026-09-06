#!/bin/bash
# Disposable populated-volume rehearsal, not a production installation command.
set -euo pipefail
test "$#" -eq 0
if [ "$(uname -s)/$(uname -m)" != Linux/x86_64 ]; then
    printf '%s\n' 'This test requires native Linux amd64; user-mode emulation lacks required tar syscalls.' >&2
    exit 64
fi
case "$(docker info --format '{{.Architecture}}')" in x86_64|amd64) ;; *) exit 64 ;; esac
REVIEW_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REVIEW_BUILD="$REVIEW_ROOT/tests/.privacy-build"
mkdir -p "$REVIEW_BUILD/go-cache" "$REVIEW_BUILD/go-mod" "$REVIEW_BUILD/go-tmp" "$REVIEW_BUILD/tmp"
export GOCACHE="$REVIEW_BUILD/go-cache" GOMODCACHE="$REVIEW_BUILD/go-mod"
export GOTMPDIR="$REVIEW_BUILD/go-tmp" TMPDIR="$REVIEW_BUILD/tmp"
export TEST_TELEMETRY_DIR="$REVIEW_BUILD/telemetry" GOTOOLCHAIN=local GOPROXY=off
export PYTHONDONTWRITEBYTECODE=1
REVIEW_RUN=$(mktemp -d "$REVIEW_BUILD/install-run.XXXXXXXX")
REVIEW_NAME="jos81-$(basename "$REVIEW_RUN")"
REVIEW_CONTAINER=''
REVIEW_VOLUME=''
cleanup() {
    REVIEW_STATUS=$?
    trap - EXIT
    if [ -n "$REVIEW_CONTAINER" ]; then
        if ! timeout -k 5 30 docker rm --force "$REVIEW_CONTAINER" >/dev/null; then REVIEW_STATUS=125; fi
    fi
    if [ -n "$REVIEW_VOLUME" ]; then
        if ! timeout -k 5 15 docker volume rm "$REVIEW_VOLUME" >/dev/null; then REVIEW_STATUS=125; fi
    fi
    exit "$REVIEW_STATUS"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Generate the source privacy delta from the reviewed base; do not duplicate it in a fixture.
git -C "$REVIEW_ROOT" diff 63d22c44b7bd008a521f0bcb8ab442b2143ee557 -- Docker/initialize.sh Docker/cron/docassemble-cron-daily.sh > "$REVIEW_BUILD/overlay-privacy.patch"
cat "$REVIEW_ROOT/Docker/privacy/nginx-realip.patch" >> "$REVIEW_BUILD/overlay-privacy.patch"
test -s "$REVIEW_BUILD/overlay-privacy.patch"
for REVIEW_COMPONENT in diagnostic process preflight monitor; do
    REVIEW_PACKAGE="./cmd/privacy-$REVIEW_COMPONENT"
    if [ "$REVIEW_COMPONENT" = diagnostic ]; then REVIEW_PACKAGE=.; fi
    CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go -C "$REVIEW_ROOT/Docker/privacy-diagnostic" build \
        -trimpath -buildvcs=false -o "$REVIEW_BUILD/privacy-$REVIEW_COMPONENT-linux-amd64" "$REVIEW_PACKAGE"
done
REVIEW_IMAGE='jhpyle/docassemble@sha256:c0b0a707a6cd2149d5777ee83af1ea1de544210e597371eac93e67a1503c395c'
timeout -k 5 600 docker pull --platform linux/amd64 "$REVIEW_IMAGE"
test "$(docker image inspect --format '{{.Architecture}}' "$REVIEW_IMAGE")" = amd64
printf 'Installation test image: %s\n' "$REVIEW_IMAGE"
go version
sha256sum "$REVIEW_BUILD"/privacy-*-linux-amd64
# Names are unique and cleanup acts only on resources created by this invocation.
if docker volume inspect "$REVIEW_NAME" >/dev/null 2>&1; then exit 73; fi
REVIEW_VOLUME=$(docker volume create --label task=JOS-81-install-review "$REVIEW_NAME")
REVIEW_CONTAINER=$(docker create --name "$REVIEW_NAME" --platform linux/amd64 --network none \
    --hostname privacy-install-test --add-host privacy-install-test:127.0.0.1 \
    --add-host privacy-install.test:127.0.0.1 --security-opt no-new-privileges \
    --memory 4g --memory-swap 4g --cpus 4 --pids-limit 1024 \
    --log-driver json-file --log-opt max-size=5m --log-opt max-file=2 \
    --label task=JOS-81-install-review \
    --mount "type=volume,src=$REVIEW_VOLUME,dst=/usr/share/docassemble" \
    --mount "type=bind,src=$REVIEW_ROOT,dst=/review,readonly" \
    -e DAHOSTNAME=privacy-install.test -e USEHTTPS=false -e BEHINDHTTPSLOADBALANCER=true \
    -e POSTURLROOT=/nj/ -e WSGIROOT=/nj -e DAALLOWUPDATES=false -e DAUPDATEONSTART=false \
    -e DAENABLEPLAYGROUND=false -e DAALLOWCONFIGURATIONEDITING=false -e DAALLOWLOGVIEWING=false \
    -e DAROOTOWNED=true -e DADEBUG=false -e PYTHONDONTWRITEBYTECODE=1 "$REVIEW_IMAGE")
docker start "$REVIEW_CONTAINER" >/dev/null
python3.14 -B - "$REVIEW_CONTAINER" <<'PY'
import subprocess
import sys
import time
probe = """from pathlib import Path
import xmlrpc.client
assert Path('/var/run/docassemble/ready').exists()
rpc = xmlrpc.client.ServerProxy('http://localhost:9001/RPC2')
states = {p['name']: p['statename'] for p in rpc.supervisor.getAllProcessInfo()}
assert all(states.get(n) == 'RUNNING' for n in ('nginx', 'uwsgi', 'celery', 'celerysingle', 'websockets'))
"""
deadline = time.monotonic() + 240
while time.monotonic() < deadline:
    result = subprocess.run(['docker', 'exec', sys.argv[1], 'python3.14', '-I', '-B', '-c', probe],
                            capture_output=True, timeout=20)
    if result.returncode == 0:
        break
    time.sleep(2)
else:
    raise SystemExit('stock application did not become ready within 240 seconds')
PY
timeout -k 5 600 docker exec "$REVIEW_CONTAINER" /usr/share/docassemble/local3.14/bin/python \
    -I -B /review/tests/privacy_native/check_install_image.py prepare
python3.14 -B "$REVIEW_ROOT/tests/privacy_native/check_install_lifecycle.py" "$REVIEW_CONTAINER" "$REVIEW_RUN"
timeout -k 5 600 docker exec "$REVIEW_CONTAINER" /usr/share/docassemble/local3.14/bin/python \
    -I -B /review/tests/privacy_native/check_install_image.py resume
python3.14 -B - "$REVIEW_CONTAINER" <<'PY'
import subprocess
import sys
result = subprocess.run(['docker', 'logs', sys.argv[1]], capture_output=True, timeout=15, check=True)
assert b'JOS81_PRIVATE_' not in result.stdout + result.stderr, 'private output in container logs'
print('private queue/cron markers absent from container stdout/stderr logs')
PY
