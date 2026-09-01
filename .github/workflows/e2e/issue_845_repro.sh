#!/bin/bash
# Repro for https://github.com/jhpyle/docassemble/issues/845.
# A 'leave' buttons choice with a url has navigation as its purpose; the
# unpatched release renders it as <button type=submit>, the patched release
# as a real <a href> styled as a button. exit-with-url keeps its session
# side effect and must stay a button in both.
# Usage: issue_845_repro.sh <base_url> <expect-fail|expect-pass>
set -euo pipefail

BASE="$1"
MODE="$2"
I="docassemble.demo:data/questions/test_navbtn.yml"

BODY=$(curl -s "$BASE/interview?i=$I" --max-time 60)
LEAVE_AS_LINK=$(echo "$BODY" | grep -cE '<a href="https://example.com/legalaid"[^>]*class="btn' || true)
EXIT_AS_BUTTON=$(echo "$BODY" | grep -cE '<button[^>]*>Exit here' || true)

case "$MODE" in
  expect-fail)
    if [ "$LEAVE_AS_LINK" != "0" ]; then
      echo "control FAILED: unpatched release already renders leave+url as a link"
      exit 1
    fi
    echo "control ok: unpatched release renders the navigation choice as a submit button"
    ;;
  expect-pass)
    if [ "$LEAVE_AS_LINK" = "0" ]; then
      echo "FAIL: leave+url did not render as a link"
      echo "$BODY" | grep -oE "<(a|button)[^>]{0,120}" | grep -iE "legalaid|Legal" | head -3
      exit 1
    fi
    if [ "$EXIT_AS_BUTTON" = "0" ]; then
      echo "FAIL: exit+url stopped being a button (it has session side effects)"
      exit 1
    fi
    if [ "$(echo "$BODY" | grep -cE '<button[^>]*>Just leave' || true)" = "0" ]; then
      echo "FAIL: leave WITHOUT a url stopped being a button"
      exit 1
    fi
    if echo "$BODY" | grep -qE '<a href="https://example.com/\?q="'; then
      echo "FAIL: quote in the url broke out of the href attribute"
      exit 1
    fi
    if [ "$(echo "$BODY" | grep -cE 'href="https://example.com/\?q=&quot;&gt;' || true)" = "0" ]; then
      echo "FAIL: tricky url was not rendered as an escaped href"
      echo "$BODY" | grep -oE '<a href="https://example.com/[^>]{0,80}' | head -2
      exit 1
    fi
    echo "pass: navigation renders as a styled link; exit and bare leave stay buttons; urls are attribute-escaped"
    ;;
  *)
    echo "unknown mode: $MODE" >&2
    exit 2
    ;;
esac
