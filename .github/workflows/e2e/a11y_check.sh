#!/usr/bin/env bash
# Fail-first accessibility check for fork issue #18.
#
# Usage: a11y_check.sh <base_url> expect-fail|expect-pass
#
# Three assertions against the live server:
#   1. The interview question page carries a skip-to-content link targeting
#      #daquestion (WCAG 2.4.1 Bypass Blocks). That page is built in
#      interview/views.py, not base.html, so it is checked separately.
#   2. The 404 page has a <main role="main"> landmark and a link home, so a
#      mistyped form URL does not dead-end the litigant.
#   3. app.min.css ships @media print rules so printed question pages drop
#      the navbar, buttons, and footer.
#
# expect-fail: every assertion must FAIL on the unpatched release (proves the
# check detects the defect it guards). expect-pass: every assertion must hold.
set -euo pipefail
base="$1"; mode="$2"
interview="$base/interview?i=docassemble.demo:data/questions/questions.yml"

skip=$(curl -sL "$interview" | grep -c 'class="visually-hidden-focusable" href="#daquestion"' || true)
notfound=$(curl -s "$base/no-such-page-a11y-check" | grep -cE 'role="main"|Go to the home page' || true)
print=$(curl -s "$base/static/app/app.min.css" | grep -c '@media print' || true)

echo "skip-link=$skip  404-landmark+home=$notfound  print-rules=$print"

case "$mode" in
  expect-fail)
    if [ "$skip" != "0" ] || [ "$notfound" != "0" ] || [ "$print" != "0" ]; then
      echo "CONTROL FAILED: the unpatched release already has one of these; the check cannot prove the fix"
      exit 1
    fi
    echo "control ok: all three absent on the unpatched release" ;;
  expect-pass)
    if [ "$skip" -lt 1 ] || [ "$notfound" -lt 2 ] || [ "$print" -lt 1 ]; then
      echo "FAIL: a11y fix not fully present"
      exit 1
    fi
    echo "pass: skip link, 404 landmark+home link, and print rules all present" ;;
  *) echo "mode must be expect-fail or expect-pass"; exit 2 ;;
esac
