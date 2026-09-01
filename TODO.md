# TODO — jacob/maintained

Current state, not history; delete items when done. See FORK.md for what
the branch already carries.

## Security alerts — remaining tail

The 239→~25 CodeQL cleanup is largely done: py/path-injection fully
fixed (38 sinks with safe_join), tarslip fixed (filter='data'), the
selector-escaper and clear-text/labelauty/exec false positives
dismissed with rationale, and advanced code-scanning set up with
vendored/generated exclusions. What remains, none blocking:

- [ ] **polynomial-redos (~14 left)**: the clean ones are done. The
  rest are URL-path parsers (`react/api.py` `/(start|run)/...`) and
  github-url regexes (`packages/helpers.py`) — each needs a
  behavior-preserving rewrite with a match-equivalence test. Do one at
  a time; do not blind-sed.
- [ ] **small tiers (~10)**: js/double-escaping, incomplete-hostname-regexp,
  url-redirection, stack-trace-exposure, remote-property-injection,
  regex-injection, bad-tag-filter, xss-through-exception. Each is a
  single-site read; several are likely upstream-report candidates
  rather than fork fixes.

## Do next (non-security)

- [ ] **Scheduled upstream sync**: weekly Action to fetch upstream
  master, rebase jacob/maintained, force-push on green CI, open an
  issue on conflict.
- [ ] **Watch upstream PR #983** (bool config): merged means dropping
  commit 24b0275 on the next rebase.
- [ ] **Upstream the clearer-error commit** (7315492): behavior-neutral,
  answers upstream #981; small PR candidate.

## Standing rules

- Atomic commits; every carried fix keeps its fail-first proof in CI.
- Rebase, never merge, onto upstream master; force-push only this
  branch; upstream PR branches stay fix-only.
- Known divergences get a pinning test (see test_bool_dict_divergence).
- CodeQL runs advanced setup with path exclusions; keep vendored and
  generated files out of scope, fix first-party source.
