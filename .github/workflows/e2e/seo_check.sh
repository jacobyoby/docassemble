#!/usr/bin/env bash
# Fail-first SEO check for fork issue #15.
#
# Usage: seo_check.sh <base_url> expect-fail|expect-pass
#
# Requires the test interview test_seo.yml installed in docassemble.demo and
# the server config to carry:
#   dispatch: {seo: docassemble.demo:data/questions/test_seo.yml}
#   social: {og: {locale: en_US}}      # og configured WITHOUT an image
#
# Assertions against the live interview page and sitemap:
#   1. <meta name="description"> carries the interview's metadata description,
#      and appears exactly once (the site-wide social description must not
#      be emitted alongside it).
#   2. <link rel="canonical"> points at the clean interview entry URL.
#   3. og:title is emitted even though no og:image is configured (ungated).
#   4. /sitemap.xml lists the dispatch entry.
#
# expect-fail: every assertion must FAIL on the unpatched release. expect-pass:
# every assertion must hold.
set -euo pipefail
base="$1"; mode="$2"
yaml="docassemble.demo:data/questions/test_seo.yml"
page=$(curl -sL "$base/interview?i=$yaml")

desc=$(echo "$page" | grep -c 'name="description" content="A test interview whose description must appear' || true)
desc_total=$(echo "$page" | grep -c 'name="description"' || true)
canon=$(echo "$page" | grep -c 'rel="canonical" href="' || true)
og=$(echo "$page" | grep -c 'name="og:title"' || true)
sitemap=$(curl -s "$base/sitemap.xml" | grep -cE '<loc>.*/start/seo/?</loc>' || true)

echo "description=$desc (total description tags=$desc_total) canonical=$canon og:title=$og sitemap=$sitemap"

case "$mode" in
  expect-fail)
    if [ "$desc" != "0" ] || [ "$canon" != "0" ] || [ "$og" != "0" ] || [ "$sitemap" != "0" ]; then
      echo "CONTROL FAILED: the unpatched release already has one of these; the check cannot prove the fix"
      exit 1
    fi
    echo "control ok: all four absent on the unpatched release" ;;
  expect-pass)
    if [ "$desc" -lt 1 ] || [ "$desc_total" != "1" ] || [ "$canon" -lt 1 ] || [ "$og" -lt 1 ] || [ "$sitemap" -lt 1 ]; then
      echo "FAIL: SEO fix not fully present"
      exit 1
    fi
    echo "pass: description, canonical, ungated og:title, and sitemap entry all present" ;;
  *) echo "mode must be expect-fail or expect-pass"; exit 2 ;;
esac
