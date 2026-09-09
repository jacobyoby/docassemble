# Security Audit Triage

**Source audit:** `SECURITY_AUDIT.md` from `docassemble-fix` (2026-08-31)
**Triage date:** 2026-09-08
**Triage method:** Cross-referenced all 54 findings against fork commit history and upstream design documentation

---

## Summary

| Severity | Total | Fixed | Upstream design | Open |
|----------|-------|-------|-----------------|------|
| Critical | 12    | 1     | 5               | 6    |
| High     | 18    | 2     | 0               | 16   |
| Medium   | 18    | 1     | 1               | 16   |
| Low      | 8     | 0     | 0               | 8    |
| **All**  | **56** | **4** | **6**           | **46** |

---

## Status Legend

- **Fixed** — Patched in this fork. Commit hash noted.
- **Upstream design** — Documented upstream API feature or architectural decision the fork intentionally keeps.
- **Open** — Still present in the fork. GitHub issue created (or to be created).

---

## CRITICAL Findings

| ID | Title | Status | Evidence |
|----|-------|--------|----------|
| C-1 | `literal_variables` exec with raw HTTP POST values | **Upstream design** | Documented API feature; `literal_variables` is part of the interview variable-setting API. Adjacent `variables` path correctly uses `repr()`. |
| C-2 | Hardcoded default Flask secret key | **Open** | `DEFAULT_SECRET_KEY = '38ihfi...'` in `config.py:32`, `app_initialize.py:20`, `socketserver.py:56`. No fork commit addresses this. |
| C-3 | Hardcoded default database password | **Open** | `db_password = 'abc123'` in `fix_postgresql_tables.py:50`. No fork commit addresses this. |
| C-4 | Pickle deserialization of DB/Redis data | **Open** | `pickle.loads()` in `fixpickle.py:11,13`, `encryption.py:57-58,99-101`. No fork commit replaces pickle. |
| C-5 | Unvalidated `tar.extractall()` on PyPI downloads | **Fixed** | Commit [`5c547ca8e`](https://github.com/jacobyoby/docassemble/commit/5c547ca8e) — "Fix tar-slip in PyPI package extraction" |
| C-6 | `eval()` with empty globals but builtins accessible | **Upstream design** | Core interview expression engine requires `eval()` with access to Python builtins. Same architectural class as C-7. |
| C-7 | YAML `code:` blocks compiled and exec'd without sandboxing | **Upstream design** | YAML interview authors are trusted; code execution is the core value proposition of the platform. |
| C-8 | `__import__()` with YAML-controlled module name | **Upstream design** | `objects:` declarations in YAML require arbitrary module import. Documented API for custom object types. |
| C-9 | Dynamic import via exec from YAML module names | **Upstream design** | YAML `modules:` directive requires `exec('import ' + module_name)`. Documented API for interview modules. |
| C-10 | Predictable PRNG for phone verification codes | **Open** | `random.randint(1000, 9999)` in `socketserver.py:670`. Should use `secrets` module. |
| C-11 | SQL injection in demo `MyIndex.report()` | **Open** | String concatenation in `docassemble_demo/docassemble/demo/index.py:50`. Demo code but still deployed. |
| C-12 | File serving routes without authentication (IDOR) | **Open** | All 14 routes in `files/views.py` lack `@login_required`. Uploaded legal docs accessible by guessing file numbers. |

---

## HIGH Findings

| ID | Title | Status | Evidence |
|----|-------|--------|----------|
| H-1 | 22 exec() and 13 eval() in interview views | **Open** | `illegal_variable_name()` uses AST but allows `x.__class__` attribute chains and `__import__()`. Gaps in the guard. |
| H-2 | XSS via `X-Forwarded-For` header in `Markup()` | **Open** | `api/views.py:153` — attacker-controlled header value rendered unescaped. |
| H-3 | XSS via `request.path` in `flash()` with `\|safe` | **Open** | `users/views.py:1016,1022` → `base.html:162` (`{{ message\|safe }}`). |
| H-4 | XSS via GitHub API data in `Markup()` | **Open** | `develop/views.py:2619-2655` — malicious GitHub username injects HTML/JS. |
| H-5 | Weak path traversal filter in `package_static` | **Fixed** | Replaced by `safe_join` in commits [`572c3daba`](https://github.com/jacobyoby/docassemble/commit/572c3daba), [`3335f938b`](https://github.com/jacobyoby/docassemble/commit/3335f938b), [`ccaacfce1`](https://github.com/jacobyoby/docassemble/commit/ccaacfce1), [`10b986fa0`](https://github.com/jacobyoby/docassemble/commit/10b986fa0), [`403f08c3f`](https://github.com/jacobyoby/docassemble/commit/403f08c3f) |
| H-6 | Weak path traversal filter in playground routes | **Fixed** | Same `safe_join` commits as H-5 — [`572c3daba`](https://github.com/jacobyoby/docassemble/commit/572c3daba), [`3335f938b`](https://github.com/jacobyoby/docassemble/commit/3335f938b), [`ccaacfce1`](https://github.com/jacobyoby/docassemble/commit/ccaacfce1), [`10b986fa0`](https://github.com/jacobyoby/docassemble/commit/10b986fa0) |
| H-7 | ZIP extraction without path validation (2 instances) | **Open** | `develop/api.py:189-222`, `develop/views.py:2680+`. Tar-slip fix (C-5) did not cover ZIP extraction. |
| H-8 | AES-CBC without authentication | **Open** | `encryption.py` — no HMAC/AEAD. Padding oracle and ciphertext manipulation possible. |
| H-9 | 46 CSRF-exempt routes | **Open** | `main/api.py`, `monitor/views.py`, `react/api.py`, `users/api.py`, `interview/api.py`. |
| H-10 | All interview API routes CSRF-exempt + CORS wildcard | **Open** | `interview/api.py` — any website can make authenticated API calls if API key leaks. |
| H-11 | Office Add-in routes without authentication | **Open** | `develop/views.py:1600-1620` — unauthenticated access to playground functionality. |
| H-12 | Fax webhook callbacks — no signature validation | **Open** | `fax/views.py` — attackers can inject fake fax status data. |
| H-13 | `/resume` route CSRF-exempt, no auth | **Open** | `main/views.py:153-163` — CSRF can force users to resume arbitrary interview sessions. |
| H-14 | `subprocess.run(shell=True)` with env var concatenation | **Open** | `listlog.py:33` — OS command injection if env vars are attacker-influenced. |
| H-15 | MD5 used for hashing | **Open** | `helpers.py:3216` — cryptographically broken. |
| H-16 | SSH host key verification disabled | **Open** | `develop/views.py:2205,4615` — `ssh -o StrictHostKeyChecking=no` enables MITM attacks. |
| H-17 | SocketIO SSL verification disabled | **Open** | `socketserver.py:57` — WebSocket connections accept invalid certificates. |
| H-18 | Predictable PRNG for key generation | **Open** | `generate_key.py:28` — generated keys are predictable and brute-forceable. |

---

## MEDIUM Findings

| ID | Title | Status | Evidence |
|----|-------|--------|----------|
| M-1 | XSS via `\|safe` on form labels (6 locations) | **Open** | `form_macros.html` — unescaped label rendering. |
| M-2 | XSS via unescaped pkgname in PyPI URL href | **Open** | `develop/views.py:2851`. |
| M-3 | XSS via `GLOBAL_CSS`/`GLOBAL_JS` config with `\|safe` | **Open** | `base.html:75,195`. |
| M-4 | XSS via pip install output in `Markup()` | **Open** | `helpers.py:1478`. |
| M-5 | Wildcard CORS on admin endpoint | **Open** | `admin/views.py:178`. |
| M-6 | CORS origins default to wildcard | **Open** | `socketserver.py:43-44`. |
| M-7 | `DEBUG=True` hardcoded | **Open** | `parse.py:129`, `testrun.py:4`. |
| M-8 | `SESSION_COOKIE_SECURE` defaults to False | **Open** | `setup.py:102`. |
| M-9 | `/headers` endpoint info disclosure, no auth | **Open** | `users/views.py:1121`. |
| M-10 | Phone verification code in URL | **Open** | `phonelogin/views.py` — codes leaked via referrer headers and browser history. |
| M-11 | Broad privileged file access for advocate/trainer | **Open** | `files/common.py:11`. |
| M-12 | TTS endpoint no authentication | **Open** | `tts/views.py`. |
| M-13 | User-controlled filename in file serving API | **Open** | `files/api.py:40-43`. |
| M-14 | Unvalidated `sys.argv[1]` as file path | **Open** | `process_email.py:28`. |
| M-15 | Playground file delete/write without realpath check | **Fixed** | Same `safe_join` commits as H-5/H-6 — [`3335f938b`](https://github.com/jacobyoby/docassemble/commit/3335f938b) |
| M-16 | SQL injection in demo `read_snapshot.py` | **Open** | `demo/read_snapshot.py:10`. |
| M-17 | `exec()` with `from ... import *` for YAML modules | **Upstream design** | Same architectural class as C-9 — YAML `modules:` directive. |
| M-18 | `eval()` of table expressions with user_dict access | **Open** | `util.py:8221-8302`. |

---

## LOW Findings (8 total)

The original audit identified 8 low-severity findings that were not individually enumerated in the detailed report. These are documented in the source `SECURITY_AUDIT.md` and tracked as a group. None are fixed in the fork.

---

## Fix Commit Index

| Commit | Findings addressed | Description |
|--------|-------------------|-------------|
| `5c547ca8e` | C-5 | Fix tar-slip in PyPI package extraction |
| `572c3daba` | H-5, H-6, M-15 | Contain playground/log file paths with werkzeug safe_join |
| `3335f938b` | H-5, H-6, M-15 | Contain remaining Playground file paths with safe_join |
| `ccaacfce1` | H-5, H-6 | Contain project rename/create and package dirs with safe_join |
| `10b986fa0` | H-5, H-6 | Contain package-read/write and commit-file paths with safe_join |
| `403f08c3f` | H-5, H-6 | Fix return type from safe_join helper guards |
| `f73bb81ab` | (extra) | Fix remaining ReDoS, hostname regexes, and two open redirects |

---

## Open Finding Prioritization

Top priorities from the open findings, ordered by exploitability and impact:

1. **C-10** — Predictable PRNG for phone verification codes (trivially exploitable, auth bypass)
2. **C-2** — Hardcoded Flask secret key (session forgery on all unconfigured installs)
3. **C-3** — Hardcoded DB password (database access on unconfigured installs)
4. **C-12** — File serving without authentication (PII/SSN data exposure)
5. **C-4** — Pickle deserialization (RCE on DB/Redis compromise)
6. **C-11** — SQL injection in demo code (data exfiltration)
7. **H-7** — ZIP extraction without path validation (arbitrary file write)
8. **H-2, H-3, H-4** — XSS vectors (session hijacking)
9. **H-18** — Predictable PRNG for key generation
10. **H-8** — AES-CBC without authentication (ciphertext manipulation)
