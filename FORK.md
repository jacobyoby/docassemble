# jacobyoby/docassemble — fork state

Branch `jacob/maintained` is the working branch. It tracks
`jhpyle/docassemble` master and carries, beyond upstream:

- **Bool config crash fix** (upstream #980, PR #983 pending): `str()` guard
  in `docassemble_base/docassemble/base/parse.py` so a YAML boolean in
  `main page title url opens in other window` cannot break every interview.
- **Plain-dict conversion** (upstream #981; upstream declined in PR #984 —
  object notation is the documented mechanism): `POST /api/session` converts
  a non-empty all-bool plain dict to a gathered `DADict`.
- **Stale hasattr error fix** (upstream #968): `DAObject.__getattr__` no
  longer parks a `pending_error` in thread state for dunder lookups to
  replay; a `hasattr()` probe on an undefined attribute can no longer
  misattribute a later, unrelated error to the probed variable.
- **Babel-backed multi-currency** (upstream #343): `currency(value,
  currency_code='EUR')` formats through `babel.numbers.format_currency` —
  thread-safe, per-currency decimal conventions (JPY gets none), optional
  `locale` keyword for number style. The default path is unchanged.
- **Configurable HTTPS port** (upstream #801): `HTTPSPORT` env var
  parametrizes the Apache `Listen` line and the SSL vhost (via a
  `DAHTTPSLISTENPORT` Define), defaulting to 443 — rootless Podman can
  bind an unprivileged port. Existing installs keep their copied vhost.
- **Branch selector failure surfaced** (upstream #915): expired GitHub
  OAuth credentials no longer downgrade silently to unauthenticated,
  rate-limited API calls; the server says to reconnect GitHub, and the
  package pages show "Unable to fetch branches" instead of stalling.
- **Multiselect autocomplete** (upstream #280): `datatype: multiselect`
  with `input type: autocomplete` renders the plain multiple-select as a
  tag-style autocomplete via vendored Tom Select 2.4.3 (Apache-2.0,
  `static/tom-select/`), lazy-loaded per page. Form encoding and server
  processing are unchanged; without the input type nothing differs.
- **Navigation buttons are links** (upstream #845): a `leave` buttons
  choice with a `url` renders as a real `<a href rel="noopener">` styled
  identically to the button it replaces, with the URL evaluated at screen
  assembly. `exit`/`logout` variants keep their submit buttons — they
  destroy the session server-side, so a link would skip that. A link
  click also skips answer recording; session checkout runs by lock expiry.
- **Encrypted email** (upstream #445 S/MIME, #288 PGP): `send_email`
  gains `smime_encrypt_for=` (recipient PEM certificates) and
  `pgp_encrypt_for=` (armored public keys). Body, HTML, and attachments
  are sealed into one part (`smime.p7m` via the cryptography library, or
  gpg-armored `message.asc`); a missing or unparseable certificate/key
  raises before anything reaches a mail provider — never a plaintext
  fallback. Implementation in `docassemble/base/email_crypto.py`.
- **Clearer API error**: when a plain dict still breaks assembly, the error
  names the variable and links `session_post_objects`.
- **SEO head tags, canonical, sitemap** (#15): `standard_html_start` emits a
  `<meta name="description">`, a `<link rel="canonical">` derived from the URL
  root (suppressible via `canonical: False`), and Open Graph tags for
  ungated pages; a `/sitemap.xml` route lists every public interview.
  CI: `Issue-15 control` (expect-fail on release) →
  `Issue-15 - install head builder and sitemap route` (expect-pass).
- **a11y skip link, 404 landmark, print CSS** (#18): a skip-to-content link
  is injected before the main region, the 404 page gains a `<main>`
  landmark and a home link, and `@media print` rules hide chrome.
  CI: `Issue-18 control` (expect-fail) →
  `Issue-18 - install a11y templates, CSS, and interview page` (expect-pass).
- **FontAwesome CSS build, page weight** (#19): the 1.5 MB FontAwesome JS
  bundle is replaced by a CSS + webfont build (~350 KB), cutting ~1.1 MB
  from every page load.
  CI: `Issue-19 control` (expect-fail, JS bundle present) →
  `Issue-19 - install FontAwesome CSS build` (expect-pass, weight drops).
- **NFC normalisation in pdftk.py** (#21): fill values are normalised to
  NFC before the XFDF write so combining characters (e.g. NFD accents
  from macOS input) render correctly in the filled PDF.
  CI: `NFC control` (expect-fail, combining accent lost) →
  `NFC - install this branch's pdftk.py` (expect-pass).
- **geopy lazy-load** (upstream #932): `geopy` is imported on first use
  instead of at module load, so a broken pydantic chain in a transitive
  dependency cannot prevent the server from starting.
  CI: container boot in the e2e workflow exercises the import path.
- **safe_join path containment** (CodeQL path-injection): every
  Playground, package-read/write, project rename/create, and
  package-setup site now routes through `werkzeug.utils.safe_join` (or
  an equivalent guard), closing path-traversal vectors flagged by
  CodeQL's `security-extended` queries.
  CI: CodeQL advanced scan (`.github/workflows/codeql.yml`).
- **tar-slip fix** (CodeQL): `PyPI package extraction` validates that
  every member path stays inside the target directory before extraction,
  closing a tar-slip (Zip-slip variant) write-wherever.
  CI: CodeQL advanced scan (`.github/workflows/codeql.yml`).
- **ReDoS fix** (CodeQL polynomial-redos): nine polynomial-redos regexes
  across package setup, filename parsing, and hostname validation are
  rewritten with proven-equivalent linear-time alternatives
  (`re.split`, `rstrip`, non-backtracking patterns).
  CI: CodeQL advanced scan (`.github/workflows/codeql.yml`).
- **Open redirects fix** (CodeQL): two redirect sites that accepted a
  user-supplied URL now validate the target against an allow-list of
  safe schemes and same-origin hosts before issuing the `Location`
  header.
  CI: CodeQL advanced scan (`.github/workflows/codeql.yml`).
- **PDF choice options**: editable fills preserve paired export/display
  options and selection indices; a temporary display-label projection lets
  QPDF render labels while the saved PDF retains its canonical export values.
  The focused fail-first gate and bounded CN 11208 verification are described
  in [the repair review](docs/pdf-choice-review.md).

## Test harness (`.github/workflows/`)

`e2e-issue-981.yml` boots the real `jhpyle/docassemble:latest` container on
every push to `jacob/maintained` and runs, in order: a fail-first control for
each fix on the unpatched release, this branch's files installed into the
container, an API suite (`e2e/e2e_suite.py`, stdlib only), and an ALKiln
browser scenario (`e2e/sources/`) driving the checkboxes interview through
headless Chrome. Supporting scripts live in `.github/workflows/e2e/` with
their own doc comments.

Run the API suite against any server:

    python3 .github/workflows/e2e/e2e_suite.py <base_url> <api_key>

The browser tooling (ALKiln, the puppeteer checks) requires Node 24 —
Node 26 breaks cucumber's yargs loader (extensionless CJS parsed as
ESM). CI pins 24 via setup-node and `.nvmrc` records it; on a Mac with
a newer default node, use `/opt/homebrew/opt/node@24/bin/node`.

## Issues

The fork's issue tracker mirrors upstream's open issues (attributed in each
body, upstream links in code spans so copies never ping upstream). Issues
fixed on this branch are closed here even while open upstream.

## Code scanning

CodeQL runs via advanced setup (`.github/workflows/codeql.yml` +
`.github/codeql/codeql-config.yml`), not GitHub's default setup, so it
can take path rules. The config runs `security-extended` on first-party
source and excludes generated JS bundles (duplicates of the scanned
`app/*.js` sources) and vendored libraries (labelauty, tom-select,
bootstrap, jQuery, fontawesome, codemirror) which are upstream's to fix.
Scans run on push/PR to master and jacob/maintained and weekly.

## Staying current

    git fetch upstream
    git rebase upstream/master jacob/maintained
    git push -f origin jacob/maintained
