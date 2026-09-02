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

## Feature requests

Tracked as GitHub issues on the fork, label `enhancement`.

- [#16](https://github.com/jacobyoby/docassemble/issues/16) — closed: the
  Tom Select multiselect-autocomplete already does this.
- [#17](https://github.com/jacobyoby/docassemble/issues/17) Cloudron
  packaging for self-hosting (upstream #917). Not verifiable without a
  Cloudron instance; left open.
- **Interview bundle split** — `bundle.min.js` (983 KB: jQuery, Bootstrap,
  validate, fileinput, labelauty, socket.io, app.js) is now the whole
  remaining weight of a public interview page after the FontAwesome swap
  (#19). Splitting it is a large refactor with every widget depending on
  it; measure with pagesize_check.sh before/after. Half a day+.

## Ship the fork to forms.jacobrakai.org

forms runs **stock** docassemble 1.10.7 + the NJForms pip package, not
this fork (verified on the live interview head). A package cannot patch
core, so nothing on this branch reaches production until the container
is built from the fork image.

- [#20](https://github.com/jacobyoby/docassemble/issues/20) Fork-built image: GHCR build on green CI, recover the
  live `docker run` args, dev first, then recreate the prod container on
  the same `da_live` volume with the stock container kept for rollback.
  ~3 hrs; steps 3–5 are production changes and wait for a go.

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
