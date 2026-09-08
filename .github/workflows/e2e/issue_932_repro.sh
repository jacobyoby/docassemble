#!/bin/bash
# Repro for https://github.com/jhpyle/docassemble/issues/932.
# Installing the `openai` package can pull a pydantic-core that mismatches
# the installed pydantic, so `import pydantic` raises SystemError. That
# error escapes through geopy -> yarl (which only guards ImportError) and
# kills `import docassemble.webapp.server`, so uWSGI reports "no python
# application found" and every page is HTTP 500.
# The fork fix lazy-loads geopy inside GeoCoder.initialize(), so a broken
# geopy chain can no longer kill startup; the error surfaces only when
# geocoding is actually used.
# This repro shadows geopy with a stub raising the exact 932 SystemError
# (no container dependencies are touched) and imports the real server
# entry point, which is the head of the 932 traceback.
# Usage: issue_932_repro.sh <base_url> <container_name> <expect-fail|expect-pass>
set -euo pipefail

BASE="$1"
CONTAINER="$2"
MODE="$3"

STUB_MSG="The installed pydantic-core version (2.45.0) is incompatible"

docker exec "$CONTAINER" mkdir -p /tmp/broken932/geopy
docker exec "$CONTAINER" python3 -c "
import pathlib
pathlib.Path('/tmp/broken932/geopy/__init__.py').write_text('raise SystemError(\"$STUB_MSG\")')
pathlib.Path('/tmp/broken932/geopy/geocoders.py').write_text('raise SystemError(\"$STUB_MSG\")')
"

IMPORT_TEST="import docassemble.webapp.server; print('server import ok')"

case "$MODE" in
  expect-fail)
    if docker exec -e PYTHONPATH=/tmp/broken932 "$CONTAINER" python3 -c "$IMPORT_TEST" 2>/tmp/repro_932_err.txt; then
      echo "control FAILED: unpatched server imported fine with broken geopy - this test cannot detect the defect"
      exit 1
    fi
    if ! grep -q "SystemError" /tmp/repro_932_err.txt; then
      echo "control FAILED: import broke but not with the issue-932 SystemError"
      cat /tmp/repro_932_err.txt
      exit 1
    fi
    echo "control ok: unpatched server import dies with the issue-932 SystemError"
    ;;
  expect-pass)
    if ! docker exec -e PYTHONPATH=/tmp/broken932 "$CONTAINER" python3 -c "$IMPORT_TEST" 2>/tmp/repro_932_err.txt; then
      echo "FAIL: patched server import still dies with broken geopy"
      cat /tmp/repro_932_err.txt
      exit 1
    fi
    echo "pass: patched server imports with broken geopy"
    if docker exec -e PYTHONPATH=/tmp/broken932 "$CONTAINER" python3 -c "
from docassemble.base.geocode import GoogleV3GeoCoder
try:
    GoogleV3GeoCoder().initialize()
except SystemError:
    print('deferred ok')
else:
    raise AssertionError('broken geopy silently swallowed')
" 2>/tmp/repro_932_defer.txt | grep -q "deferred ok"; then
      echo "pass: geopy failure correctly deferred to first geocode use"
    else
      echo "FAIL: broken geopy did not surface at initialize()"
      cat /tmp/repro_932_defer.txt
      exit 1
    fi
    BASE_CODE=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/health_check?ready=1" --max-time 60)
    if [ "$BASE_CODE" != "200" ]; then
      echo "FAIL: container health check returned HTTP $BASE_CODE"
      exit 1
    fi
    echo "pass: container still serves (HTTP 200)"
    ;;
  *)
    echo "unknown mode: $MODE" >&2
    exit 2
    ;;
esac
docker exec "$CONTAINER" rm -rf /tmp/broken932
