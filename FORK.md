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

## Staying current

    git fetch upstream
    git rebase upstream/master jacob/maintained
    git push -f origin jacob/maintained
