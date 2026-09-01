#!/bin/bash
# Repro for https://github.com/jhpyle/docassemble/issues/968.
# A hasattr() probe on an undefined DAObject attribute leaves a stale
# pending_error in thread state; a later dunder access replays it, so the
# engine seeks the hasattr-probed variable instead of reporting the real
# error. Usage: issue_968_repro.sh <base_url> <container_name> <expect-fail|expect-pass>
set -euo pipefail

BASE="$1"
CONTAINER="$2"
MODE="$3"
I="docassemble.demo:data/questions/test_issue_968.yml"

BODY=$(curl -s "$BASE/interview?i=$I" --max-time 60)

case "$MODE" in
  expect-fail)
    if ! echo "$BODY" | grep -q "test_obj.nonexistent"; then
      echo "control FAILED: unpatched server did not misattribute the error to the hasattr-probed variable"
      echo "$BODY" | grep -oE "reference to a variable '[^']*'" | head -2
      exit 1
    fi
    echo "control ok: unpatched server sought the stale hasattr-probed variable"
    ;;
  expect-pass)
    if echo "$BODY" | grep -q "test_obj.nonexistent"; then
      echo "FAIL: patched server still misattributes the error to the hasattr-probed variable"
      exit 1
    fi
    if ! docker exec "$CONTAINER" tail -20 /usr/share/docassemble/log/docassemble.log \
        | grep -q "has no attribute '__custom__'"; then
      echo "FAIL: patched server did not report the real __custom__ error"
      docker exec "$CONTAINER" tail -5 /usr/share/docassemble/log/docassemble.log
      exit 1
    fi
    echo "pass: error names the real attribute, not the hasattr-probed one"
    ;;
  *)
    echo "unknown mode: $MODE" >&2
    exit 2
    ;;
esac
