#!/usr/bin/env bash
# Fail-first page-weight check for fork issue #19.
#
# Usage: pagesize_check.sh <base_url> expect-fail|expect-pass
#
# Measures what a self-represented litigant actually downloads to render one
# public interview page: every <script src> and every stylesheet <link href>
# the page references, fetched and summed. The unpatched release ships
# FontAwesome as a 1.5 MB JavaScript SVG-replacement bundle on every page;
# the branch swaps it for the 88 KB CSS build (icon fonts load on demand,
# only for the styles a page uses), with every icon still available.
#
# expect-fail: the unpatched release must still load fontawesome/js and the
# payload must be >= 2400 KB (proves the check detects the defect).
# expect-pass: fontawesome/js must be gone, fontawesome/css present, and the
# payload must be < 1600 KB (the FA swap; the 983 KB interview bundle is a separate, deferred item).
set -euo pipefail
base="$1"; mode="$2"
page=$(curl -sL "$base/interview?i=docassemble.demo:data/questions/questions.yml")

total=0
while read -r u; do
  [ -z "$u" ] && continue
  case "$u" in http*) full="$u";; /*) full="$base$u";; *) full="$base/$u";; esac
  sz=$(curl -sL -o /dev/null -w '%{size_download}' "$full" || echo 0)
  total=$((total + sz))
done < <(echo "$page" | grep -oE '(src|href)="[^"]+\.(js|css)(\?[^"]*)?"' | sed -E 's/^(src|href)="//; s/"$//')
kb=$((total / 1024))
fa_js=$(echo "$page" | grep -c 'fontawesome/js/all.min.js' || true)
fa_css=$(echo "$page" | grep -c 'fontawesome/css/all.min.css' || true)

echo "payload=${kb}KB fontawesome-js=$fa_js fontawesome-css=$fa_css"

case "$mode" in
  expect-fail)
    if [ "$fa_js" -lt 1 ] || [ "$kb" -lt 2400 ]; then
      echo "CONTROL FAILED: unpatched release does not show the heavy FontAwesome JS payload; the check cannot prove the fix"
      exit 1
    fi
    echo "control ok: unpatched release loads fontawesome/js and weighs ${kb}KB" ;;
  expect-pass)
    if [ "$fa_js" != "0" ] || [ "$fa_css" -lt 1 ] || [ "$kb" -ge 1600 ]; then
      echo "FAIL: page weight fix not fully present"
      exit 1
    fi
    echo "pass: fontawesome/js gone, css build present, page weighs ${kb}KB" ;;
  *) echo "mode must be expect-fail or expect-pass"; exit 2 ;;
esac
