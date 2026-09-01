# Contributing to this fork

This is a maintained fork of
[jhpyle/docassemble](https://github.com/jhpyle/docassemble). The working
branch is `jacob/maintained`; see [FORK.md](FORK.md) for what diverges and
why.

- **Core features belong upstream.** If a change is universally useful,
  open it against jhpyle/docassemble first (see their CONTRIBUTING). This
  fork carries only fixes upstream has not merged and its own test harness.
- **Pull requests here target `jacob/maintained`**, never `master`, which
  mirrors upstream.
- **Every change to carried fixes needs a fail-first test**: prove the
  unpatched release exhibits the defect, then prove the patched files fix
  it. The harness in `.github/workflows/` shows the pattern and runs on
  every push to the working branch.
- The issue tracker mirrors upstream's open issues; issues fixed on this
  branch are closed here with the fixing commit even while open upstream.
