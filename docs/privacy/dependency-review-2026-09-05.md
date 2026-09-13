# NLTK advisory review

GitHub inspection on September 5, 2026 found two open High Dependabot alerts,
[35](https://github.com/jacobyoby/docassemble/security/dependabot/35) and
[36](https://github.com/jacobyoby/docassemble/security/dependabot/36), for one
advisory: [GHSA-8mgp-746c-j5xp](https://github.com/advisories/GHSA-8mgp-746c-j5xp).
Both application manifests pin affected `nltk==3.10.3`. GitHub identifies no
patched release. No dependency version was changed and neither alert was dismissed.

The advisory concerns model-artifact APIs that bypass NLTK's path restrictions
when untrusted workflows control model import/export paths. Affected APIs named
in the review include `TransitionParser.train/parse`, `AveragedPerceptron.save/load`,
`PerceptronTagger.save_to_json` and `save_maxent_params`.

Source inspection found no direct calls to those APIs. `docassemble/base/pattern.py`
uses language helpers and fixed corpus downloads; the webapp machine-learning
module uses `docassemble_pattern` KNN/SVM. This does not establish non-reachability:
`docassemble/base/pattern_server.py` dispatches dynamically through a Unix socket,
and installed extensions, transitive implementations and runtime socket access
have not been audited here. No public endpoint exploit was demonstrated.

Upstream work routes model file operations through `nltk.pathsec.open()` or
guarded helpers. A version bump needs a verified fixed release; if affected
runtime use is established before one exists, evaluate a bounded upstream
backport or a control preventing untrusted model paths from reaching those APIs.
Do not remove the working language features or claim the package is safe based
only on a search with no direct matches.

The two Dependabot alerts remain the authoritative tracking records. This review
does not close the separate [privacy installation work](https://github.com/jacobyoby/docassemble/issues/22).
