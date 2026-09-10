# PDF choice-field repair: verification and release boundary

## Defect and scope

The editable pikepdf fill path converted every `/Opt` entry to a Python
string. A valid choice option can be a PDF string or a two-element
`[export value, display label]` array. Stringifying the latter writes
internal `pikepdf.Array(...)` text into the generated PDF and destroys the
option structure. A stale `/I` can select the wrong option after a fill.

The fix matches submitted **export values** and preserves existing option
objects. Unmatched input retains the existing free-text behavior by appending
only the submitted string; display-label input is not silently translated into
an export code. Missing option arrays are supported. Existing selection
indices are updated to agree with the filled value.

QPDF's appearance generator also needs display labels rather than export
codes. Only touched paired-option fields receive a temporary display-only
projection during appearance generation. A `finally` block restores canonical
options and export values before the PDF is saved, including on generation
errors. Shared-widget parents and direct-object identities are handled.

The explicit PDFtk, flattened/PDF-A, checkbox, signature and text-field paths
are not redesigned. This does not establish new multiselect support or fix
the existing appearance generator's font, alignment or Unicode limitations.

References: [pikepdf choice options and appearances](https://pikepdf.readthedocs.io/en/latest/api/form.html#pikepdf.form.ChoiceFieldOption)
and [QPDF-backed field limitations](https://pikepdf.readthedocs.io/en/latest/api/models.html#pikepdf.AcroFormField.choices).

## Real-template verification, 2026-09-09

Local verification used Docassemble 1.10.7, pikepdf 10.11.0 and QPDF 12.3.2.
The candidate module was loaded from an isolated temporary path. The installed
server module was not replaced, and the server was not restarted.

For official NJ CN 11208, blank selection and all 21 counties passed:

1. All 40 mapped field values were read back from the canonical field tree.
2. All 22 original county option pairs were preserved; only an unmatched
   empty string added a new scalar option. Selection indices matched.
3. Both county widgets inherited the correct value and had non-empty
   appearances with the intended label, without `pikepdf.Array` text.
4. Text extracted from pages 5 and 8 contained each selected county exactly
   once. The eight-page document retained 48 fields and 71 widgets.

Poppler renders of blank output pages 5-8 and Burlington output pages 5 and 8
were inspected. The original defect was visibly absent, with no county-label
clipping. All eight static page content streams matched the official source.
No real personal data, signatures or court filings were used.

The official source PDF was never edited. Its SHA-256 before and after:

`9c3d508270b6870e8732dc4a97a2aff34f4918b2ed10f1c1fb4cecbb28a90caf`

## Reproducible synthetic gate

`.github/workflows/e2e/pdf_choice_check.py` generates its own small fixtures;
it does not download, modify or commit official court PDFs. The focused
workflow runs a pinned Docassemble 1.10.7 control before loading this branch's
candidate module. A control passes only when it detects the specific original
option-corruption defect, not an arbitrary exception.

The installed Python environment must have Docassemble, pikepdf and Poppler.
The CLI accepts `expect-fail` for the unpatched runtime and `expect-pass
--module /path/to/candidate/pdftk.py` for the candidate. The candidate is imported
by path without installing or overwriting the server module.

Both modes passed in the existing local runtime and a fresh container with
network access disabled and the checkout mounted read-only. Swapping the
modes fails as intended: the patched candidate cannot satisfy the corruption
control, and the unpatched runtime cannot pass the regression suite. The
intentional appearance-exception case logs an error while verifying canonical
state restoration; this is a test probe, not a successful appearance claim.

An independent negative-control probe filled only an unrelated text field:
untouched paired-choice appearance streams were byte-identical between the
baseline and candidate. A separate object-shape probe confirmed that direct
choice widgets can retain `(0, 0)` object identities after save/reopen, making
the fallback projection key relevant. These probes are additional local
evidence, not claims that the synthetic suite covers every valid PDF shape.

Both changed Python files compile. The new harness passes Ruff. The runtime
file still has 21 pre-existing Ruff findings; comparison against the fetched
base found no added findings. Full-file runtime lint is not claimed clean,
and unrelated lint cleanup is not included in this repair.

## Release boundary

This is a separate runtime PR, not an interview-UI deployment. No merge,
production deployment, production restart, PDF-template update or filing is
authorized by these test results. The paired Forma Pauperis UI PRs #42/#43
remain separate drafts. Full assistive-technology, physical-device, actual
browser zoom, operational timeout and broader process checks remain open;
these PDF checks are not WCAG/ADA certification.
