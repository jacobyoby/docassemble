# TODO — jacob/maintained

Current state, not history; delete items when done. See FORK.md for what
the branch already carries.

## Test coverage gaps

The e2e suite covers interviews, the API, checkboxes, currency, email
crypto, and the boolean-config case. It does **not** exercise the
Playground package/project operations, which is where most of the
safe_join hardening lives. A bug in that area (a helper returning a Flask
tuple instead of an action dict) got through CI for exactly that reason.

- [ ] **Package-pull traversal e2e**: fail-first test calling
  `do_playground_pull` with a `../`-bearing package name; must return
  `{'action': 'error', ...}` on the branch (crashed before 403f08c).
  ~20 min.
- [ ] **Project rename/create e2e**: exercise `rename_project` and
  `create_project` through the Playground UI or API, including a
  traversal name that must be silently skipped. ~30 min.
- [ ] **Open-redirect e2e**: POST an invite with `next=https://evil.example`
  and assert the redirect lands on a local path (make_safe_url). ~15 min.
- [ ] **Log-download path e2e**: request a log file with a `../` name and
  assert 404 (logs/views.py safe_join). ~10 min.

## Fork maintenance

- [ ] **Scheduled upstream sync**: weekly Action to fetch upstream
  master, rebase jacob/maintained, force-push on green CI, open an
  issue on conflict.
- [ ] **Watch upstream PR #983** (bool config): merged means dropping
  commit 24b0275 on the next rebase.
- [ ] **Upstream the clearer-error commit** (7315492): behavior-neutral,
  answers upstream #981; small PR candidate.
- [ ] **Upstream the tar-slip fix** (`filter='data'` in
  do_playground_pull): one-line, security-relevant, no fork-specific
  behavior; strong PR candidate.

## Standing rules

- Atomic commits; every carried fix keeps its fail-first proof in CI.
- Rebase, never merge, onto upstream master; force-push only this
  branch; upstream PR branches stay fix-only.
- Known divergences get a pinning test (see test_bool_dict_divergence).
- CodeQL runs advanced setup with path exclusions; keep vendored and
  generated files out of scope, fix first-party source. 0 open as of
  403f08c; new alerts get fixed or dismissed with a written reason.
- A safe_join None-guard must return the enclosing function's own
  error type: a 404 tuple only inside a decorated route, an action
  dict in dict-returning helpers, a bare return in side-effect helpers.
