#!/bin/bash
# Repro for https://github.com/jhpyle/docassemble/issues/981.
# Creates a session on a checkboxes interview, POSTs a plain dict for the
# checkboxes variable via /api/session, and checks whether the server accepted
# it with real DADict semantics (fruit.true_values() renders on the next
# question). Third argument selects the assertion:
#   expect-fail  the set must NOT succeed end-to-end (unpatched control)
#   expect-pass  set returns 200 and the rendered result names the true values
set -euo pipefail

BASE="$1"
KEY="$2"
MODE="$3"
I="docassemble.demo:data/questions/test_issue_981.yml"

NEW_CODE=$(curl -s -o /tmp/new_body.txt -w '%{http_code}' -H "X-API-Key: $KEY" "$BASE/api/session/new?i=$I")
NEW=$(cat /tmp/new_body.txt)
if ! echo "$NEW" | python3 -c 'import json,sys; json.load(sys.stdin)' 2>/dev/null; then
  echo "session/new returned HTTP $NEW_CODE with non-JSON body:"
  head -c 600 /tmp/new_body.txt
  exit 1
fi
SID=$(echo "$NEW" | python3 -c 'import json,sys; print(json.load(sys.stdin)["session"])')
SECRET=$(echo "$NEW" | python3 -c 'import json,sys; print(json.load(sys.stdin)["secret"])')

SET_CODE=$(curl -s -o /tmp/set_body.json -w '%{http_code}' -X POST \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d "{\"i\": \"$I\", \"session\": \"$SID\", \"secret\": \"$SECRET\", \"variables\": {\"fruit\": {\"apple\": true, \"banana\": false, \"cherry\": true}}}" \
  "$BASE/api/session")

RESULT=$(curl -s -H "X-API-Key: $KEY" \
  "$BASE/api/session/question?i=$I&session=$SID&secret=$SECRET" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print((d.get("questionText") or "") + "|" + (d.get("subquestionText") or ""))')

echo "set HTTP $SET_CODE; question: $RESULT"

case "$MODE" in
  expect-fail)
    if [ "$SET_CODE" = "200" ] && echo "$RESULT" | grep -q "apple and cherry"; then
      echo "control FAILED: unpatched server accepted the plain dict - this test cannot detect the defect"
      exit 1
    fi
    echo "control ok: unpatched server rejected the plain dict (HTTP $SET_CODE)"
    ;;
  expect-pass)
    if [ "$SET_CODE" != "200" ]; then
      echo "FAIL: set returned HTTP $SET_CODE, body:"
      cat /tmp/set_body.json
      exit 1
    fi
    if ! echo "$RESULT" | grep -q "apple and cherry"; then
      echo "FAIL: fruit.true_values() did not render; question was: $RESULT"
      exit 1
    fi
    echo "pass: plain dict converted to DADict; true_values rendered"
    ;;
  *)
    echo "unknown mode: $MODE" >&2
    exit 2
    ;;
esac
