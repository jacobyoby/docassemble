#!/bin/bash
# Repro for https://github.com/jhpyle/docassemble/issues/980.
# With `main page title url opens in other window` set to a YAML boolean in
# the configuration, the unpatched release crashes every interview load with
# AttributeError: 'bool' object has no attribute 'strip' (parse.py read_from).
# Usage: issue_980_repro.sh <base_url> <container_name> <expect-fail|expect-pass>
set -euo pipefail

BASE="$1"
CONTAINER="$2"
MODE="$3"
I="docassemble.demo:data/questions/test_issue_981.yml"

CODE=$(curl -s -o /tmp/interview_body.txt -w '%{http_code}' \
  "$BASE/interview?i=$I" --max-time 60)
echo "interview load with boolean config: HTTP $CODE"

case "$MODE" in
  expect-fail)
    if [ "$CODE" = "200" ]; then
      echo "control FAILED: unpatched server survived the boolean config - this test cannot detect the defect"
      exit 1
    fi
    if ! docker exec "$CONTAINER" tail -20 /usr/share/docassemble/log/docassemble.log \
        | grep -q "'bool' object has no attribute 'strip'"; then
      echo "control FAILED: interview broke but not with the issue-980 AttributeError"
      docker exec "$CONTAINER" tail -5 /usr/share/docassemble/log/docassemble.log
      exit 1
    fi
    echo "control ok: unpatched server crashed with the issue-980 AttributeError"
    ;;
  expect-pass)
    if [ "$CODE" != "200" ]; then
      echo "FAIL: patched server still returns HTTP $CODE with boolean config"
      docker exec "$CONTAINER" tail -5 /usr/share/docassemble/log/docassemble.log
      exit 1
    fi
    echo "pass: patched server serves interviews with the boolean config value"
    ;;
  *)
    echo "unknown mode: $MODE" >&2
    exit 2
    ;;
esac
