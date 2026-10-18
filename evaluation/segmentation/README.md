# Ground-truth line and word benchmark (qualified evaluator v2)

This is a **local, offline evaluation harness**, not a production Free measurement method or calibrated classifier.

Run from repository root in the locked Python environment:

`PYTHONPATH=src python -m evaluation.segmentation.benchmark --manifest /approved/manifest.json --image-root /approved/images --shadow-projection --shadow-words`

## Manifest and annotation geometry

Use a **schema_version 2** JSON manifest with explicit `"annotation_frame": "original_image"` for phone photos annotated in their original, decoded image coordinate frame, or `"analysis_canvas"` for deliberately preprocessed annotations. The runner maps all four corners of each original rectangle through the actual per-image `original_to_analysis` transform, clips to the canvas, and creates a half-open bounding rectangle. Boxes are `[x, y, width, height]` with positive dimensions. Mapping a rotated rectangle to an axis-aligned box adds known rasterization error.

Legacy schema_version 1 manifests still mean `analysis_canvas` unless explicitly labeled. For production-quality evidence, migrate to v2, don't guess coordinates.

Manifest has `split` (synthetic/development/validation/holdout), and `specimens` objects with `specimen_id`, `writer_group`, `capture_group`, `image_path` (root-relative), exact encoded-file `sha256`, `paper` (blank/lined/grid/form/unknown), and optional `lines` and `words` annotations. Omitted `lines` or `words` means **not annotated** (unknown), whereas an explicit `[]` means an **annotated empty** family. Real records require a reviewed `rights_decision_id` but that string does not independently authorize access.

## Evaluation

Existing line and word detectors are scored separately from optional TLC-inspired line and whitespace-grouped word *shadow* candidates. Scores include one-to-one IoU (0.50 threshold), macro precision/recall/F1, count MAE, matched IoU, center error, false-zero word cases, rejections, and paper/split breakdowns. The versioned engineering summary explicitly separates nonempty-handwriting F1, annotated family coverage, nonempty family coverage, and correctly empty cases. Rejected and partial specimens stay in the eligible denominator. Missing annotations and unrun shadow methods are reported as null, not scored as zero. Candidate-limit truncation refuses a misleading partial score. Synthetic fixtures are **engineering regression evidence only**.

Max 256 specimens per run, 25MB per encoded file, 24 megapixels decoded and 4096 annotations per family per image. Images/digests are verified locally; the JSON output contains no pixels or region coordinates. These checks are guardrails, **not** a data-access control system. Keep source images, private specimen identifiers and full manifests outside public Git/CI.

Before claiming real accuracy: obtain consent and explicit per-use rights, freeze writer-disjoint development/holdout partitions, agree on annotation criteria, audit annotator disagreement, pre-register targets, and evaluate once on held-out samples. The `--allow-authorized-real` switch is a secondary guard, not proof of clearance. When it is used, the command line prints only a fixed **PROTECTED_RESULTS_WITHHELD** notice by default, never specimen IDs, paths, per-image traces or a manifest digest. Programmatic callers must retain such details in protected storage.

Never promote shadow candidates to authoritative `PAGE_LINE_COUNT` or `PAGE_WORD_COUNT` from synthetic results alone.

## Qualified v2 protocol and partial results

The default research CLI remains `grid-v1`. The separate `--profile
qualified-v2` explicitly evaluates the guarded v2 candidate offline and does
**not** turn it on in Free production. Its output includes the line/word
qualification state. A `PARTIAL` specimen counts toward denominator/coverage;
unqualified word groups have `words: null`, not a fabricated zero score.

`predeclared_holdout_gate` is retained for historical **v1 synthetic protocol** tests; `score_holdout` will **never** accept an arbitrary supplied aggregate as empirical qualification. The v2 API `predeclared_holdout_gate_v2(dev, validation, holdout, policy)` checks all three synthetic splits (including specimen/source grouping) against frozen SHA-256, current source checkout, evaluator bytes and the processing configuration. Thresholds must be explicit and finite. `run_frozen_synthetic_qualification` invokes the actual benchmark on **every** holdout fixture and computes its own selective-coverage and nonempty-handwriting gates. It returns `ENGINEERING_PASS` or `ENGINEERING_FAIL`, but always `public_qualification: NOT_AUTHORIZED`.

The v2 runner intentionally accepts **only** manifests explicitly designated synthetic; a label does not prove rights, and no human corpus is allowed in this PR. The normal benchmark runner's internal `synthetic_split` flag exists solely to exercise these synthetic development/validation/holdout partitions; it grants no real-data access or publication. `public_safe_receipt` drops protected identifiers and digests and suppresses counts in small groups. The v2 policy must be prepared outside the candidate source commit (because source-SHA self-pinning inside that same commit is circular), reviewed before any held-out execution, and never tuned to the holdout results. Source identity checks are engineering integrity checks, **not signed or hardware attestations**. Check the pending T11 consent gate and [release gates](../../docs/runbooks/segmentation-v2-qualification.md) before discussing real evaluation or activation.

Frozen JSON manifests and policies reject duplicate member names at any nesting depth and nonstandard nonfinite constants; encoded-file SHA-256 covers the same manifest bytes decoded for a run. The synthetic validation split runs through the existing benchmark under the explicit `synthetic_split=True` test-only path; it does not grant real-data access.

Qualification separately gates explicit-empty line/word evidence: minimum annotated-empty counts, false-positive page maxima and empty-family coverage; abstentions are not hallucinations but remain in the eligible denominator. The `paper: blank` field denotes **unruled paper**, not missing handwriting. A v2 policy missing blank-specific gates must fail closed.

The synthetic v2 policy also binds the effective numerical runtime: the selected Python-target-specific reviewed manifest/lock SHA-256, installed-distribution digest, running Python patch version, platform/architecture, and imported NumPy/OpenCV module and distribution versions. The gate refuses an unlocked or unsupported environment; a separate protected platform requires a separately reviewed lock. This reuses the existing standard-library tools/verify_ci_lock.py utilities and is not a signed attestation or a real-data rights approval.

The frozen identity also binds the source digest of `tools/verify_ci_lock.py` and verifies the imported module originates from that exact file. Git cleanliness checks cover the verifier plus the reviewed `requirements/` snapshots, as well as the engine and evaluation code. Blank-page coverage thresholds must be **strictly positive** and the reviewed policy must require a positive **absolute number of available** empty line/word observations; rejecting every blank page cannot qualify even if the nonempty subset scores perfectly.


## Round-four evaluation integrity (synthetic only)

The frozen v2 gate requires an independent, prior approved policy digest.
Programmatic calls to predeclared_holdout_gate_v2 and
run_frozen_synthetic_qualification must pass the keyword-only argument
expected_policy_sha256. It is checked against exact policy-file bytes before
any holdout manifest evaluation or image processing. A freshly calculated
self-hash does not establish independent preregistration. Keep the actual
prior approval, reviewer identity, timestamp and audit trail in separately
controlled storage. Synthetic unit tests simulate the prior approval with a
distinct approved-digest fixture.

For synthetic qualification, **never execute an unchecked launcher from the
checkout being evaluated**. `tools/qualification_bootstrap.py` is a
distribution *template*, not automatically trusted merely because it is in
Git. An independent reviewer/operator must inspect and install the bootstrap
**outside the evaluated checkout** and verify its hash against a separately
approved record *before executing it*. In CI, test code copies it outside
the checkout to test the protocol only; that fixture is not human approval.

Once the independently approved bootstrap has been provisioned at
`/trusted/qualification_bootstrap.py`, invoke:

    python -I -S -B /trusted/qualification_bootstrap.py \
      --repository /checked-out/YouAreASpecialLittlePrincess \
      --development /protected/development.json \
      --validation /protected/validation.json \
      --holdout /protected/holdout.json \
      --policy /protected/frozen-policy.json \
      --approved-digest-file /independent/prior-review.sha256 \
      --image-root /protected/fixtures \
      --wheelhouse /approved/authenticated-wheelhouse

The external bootstrap uses only stdlib code to validate the prior-approved
policy digest and source commit, then checks out that exact Git object into
a fresh detached worktree. It verifies the launcher bytes **before** Python
executes them and runs the internal worker under `-I -S -B`. A direct
invocation of `evaluation/segmentation/run_qualification.py` from the
evaluated checkout is expressly not the trusted entrypoint. Its internal
`--_staged` mode checks the approved revision before any project imports,
but cannot retroactively establish trust in an unapproved script that
someone explicitly executed.

Wheel preflight authenticates `Root-Is-Purelib` from the hash-reviewed wheel
metadata, differentiates `purelib` and `platlib` (including Linux lib64),
checks relocated files and versioned native libraries, and refuses mutated
installed files. No installed RECORD metadata is used as a trust anchor.
Failure diagnostics contain only fixed `Q_*` stage codes; private paths,
specimen records and image bytes are never printed.
These process-local checks are not a sandbox, signature or hardware attestation.

Every benchmark result row, top-level result and summarize aggregation carries
data_origin: SYNTHETIC_FIXTURE or REAL_SOURCE_DECLARED. The latter describes
source provenance and does not independently establish rights. Mixed, missing
and unknown origins cannot be aggregated. Frozen synthetic qualification
requires the synthetic marker for each row, and any successful receipt
still has public_qualification: NOT_AUTHORIZED.

### Trusted execution boundary (round five)

The synthetic-only external bootstrap requires `python -I -S -B`.
After independent bootstrap installation, it authenticates approved launcher
bytes from the policy-pinned Git commit and creates a *fresh detached Git
worktree* from that approved revision; it never inherits untracked checkout files or
`__pycache__`. The worker imports only standard-library modules first,
authenticates **the original wheels from the Python-target-specific reviewed
lock** and checks installed executable bytes before admitting site-packages.
It then loads the reviewed project and verifies all loaded modules (including
stdlib and transitive packages) against the interpreter, approved source roots
or the independent wheel manifest. It audits again after benchmark execution.
The reviewed wheelhouse can be supplied with `--wheelhouse`; CI's
`$RUNNER_TEMP/ci-wheelhouse` is used if available. Missing or altered wheels
fail closed; mutating an installed `RECORD` does not confer approval.

The holdout runner consumes the exact validated encoded manifest bytes, never
reopening its pathname after approval. Image files are opened relative to a
reviewed directory descriptor, without following symlinks, capped, hashed
against the frozen record and only then decoded from that immutable byte buffer.

These controls are process-local and rely on a trustworthy OS, Git checkout
and interpreter. They are **not** a signature, external policy approval,
container-level sandbox or authorization to process human data.


### Round-six closeout: worker authority, paths, and native wheel evidence

The operator's manifest, policy, independent approval, image-root and
wheelhouse paths are resolved against the original invocation directory
before creating the isolated detached worktree. The worker receives absolute
paths. The internal worker option is not a permission grant: it refuses an
ordinary checkout, a non-detached worktree, a dirty stage and inherited
project bytecode before importing project evaluator code.

Clean staging under python -I -S -B establishes the pre-import project
bytecode boundary. Cache checks derive the expected source cache path rather
than trusting module.__cached__; deleting a cache after executing hostile
code in an arbitrary process cannot prove clean execution. Direct
programmatic engineering results are not signed or independently attested.

Dependency preflight authenticates wheel-provided installed artifacts,
including versioned .so.5/.so.5.0.0 libraries that do not appear in
sys.modules. Wheel .data relocations are mapped to installed destinations.
Expected file digests always come from original reviewed wheel archives.
Cython virtual-module exemptions are narrowed to known version-form runtime
aliases in the separately verified execution environment; no arbitrary
cython namespace is approved.

The trust model assumes an uncompromised host, interpreter and Git object
store, plus independent prior policy approval. Public-safe JSON is redacted
evidence of a synthetic engineering evaluation, not signed attestation.
No change to public_qualification: NOT_AUTHORIZED, T11, Issue #92 or the
legacy production default.


### Approved revision binding and minimum meaningful nonempty accuracy

A clean Git HEAD is not sufficient evidence of an approved executable. The
standard-library-only bootstrap authenticates exact frozen policy bytes
against the independently supplied expected SHA-256, strictly parses the
policy, and checks the HEAD revision against that policy's source_commit_sha
BEFORE adding any project path or importing evaluator code. The internal
detached-worktree worker independently repeats this check. Thus a clean,
committed alternate checkout cannot self-approve merely by being clean.
Operator-created policy hashes do not establish independent prior approval.

Both min_line_nonempty_macro_f1 and min_word_nonempty_macro_f1 now require
strictly positive predeclared thresholds. Zero F1 with otherwise plausible
coverage and nonempty detections never produces ENGINEERING_PASS.


### Synthetic blank-page evidence limitation

The `qualified_empty` status in the offline benchmark is produced only by
a deliberately uniform-light **synthetic fixture oracle**. It is image-only
and does not consult annotations, but it is **not evidence that the production
qualified-v2 detector itself can classify blank handwriting pages**. The
engineering and public-safe receipts explicitly carry
`blank_evidence_scope: SYNTHETIC_FIXTURE_ORACLE_ONLY`. These synthetic
available-empty observations test denominator accounting, not empirical
real-photo blank specificity. Real-world qualified-empty evidence and
preregistered scientific accuracy requirements require separate rights-gated
evaluation. A positive structural F1 threshold such as 0.01 is not a
real-world quality target.


### Round-eight: policy handoff and acceptance guardrails

For the official trusted Linux bootstrap, the exact policy bytes and the
separately supplied, independently approved digest are placed in two sealed
anonymous memory descriptors before spawning the worker. The child receives
\`/proc/self/fd/...\` references through \`pass_fds\`; it must never reopen
mutable original policy and approval pathnames. A simultaneous replacement
of both original files cannot change the policy scored by that run. Sealing
requires Linux \`memfd_create\`/\`F_ADD_SEALS\` and fails closed where missing.

All overall and nonempty line/word coverage floors must be strictly positive.
An arbitrarily small positive floor is only a syntactic anti-vacuity control,
not empirical validation; the independent reviewer must preregister useful
threshold values and inspect actual available denominators.

Only within explicitly synthetic fixture evaluation, uniformly light BGRA
images are composited onto white exactly as \`prepare_context\` does before
the blank oracle checks their lightness. Alpha zero is not dark handwriting.
Ambiguous/ruled/non-fixture captures cannot gain synthetic blank authority.

For standalone Linux developer qualification, preserve the hash-locked
wheelhouse using the reviewed recipe in
[local setup](../../docs/development/local-setup.md). Do not claim installed
package metadata alone is a reproducible, authenticated runtime.
