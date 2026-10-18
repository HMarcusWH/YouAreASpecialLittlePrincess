# Qualified Segmentation v2 — review and release gates

This PR is an **experimental engine and measurement-validity** change, not a
claim of empirically validated handwriting segmentation or permission to
activate the new processing profile on public services.

## Immutable baseline and profile names

- Source branch: `feat/segmentation-v2-qualified-pipeline` from merged #80 (`dc1b586`).
- Historical `legacy` remains the implicit default. Its old analysis config
  hash and `grid-v1`'s pre-existing hash remain unchanged.
- V2 opt-in: `PRINCESS_ANALYSIS_PROFILE=qualified-v2`, only for local/test
  with `PRINCESS_SEGMENTATION_V2_RESEARCH_OPT_IN=1`.
- Separate API and worker processes also require an identical
  `PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256`; the Railway combined test stack
  pins and passes the hash to both roles. Public guest-only remains legacy.
- V2 uses `quality-policy/2`. Existing feature IDs, units and stage equations
  remain canonical; the versioned processing config records new inputs and
  segmentation acceptance semantics without rewriting old report identities.

## Deterministic pipeline contract

`source pixels → optional qualified document ROI/homography → deskew →
periodic chromatic/gray ruling evidence → observed retained ink →
qualified text-line grouping → scale-aware WordDetector trace and conservative
geometric ink groups → MeasurementContext with qualification →
canonical facts with MISSING/null on unqualified support → immutable evidence
and saved reports → permission-filtered client projections`.

Any stage may refuse or withhold a family. In particular, a numeric zero from
`len(words)` is NOT factual zero when the proposed word groups did not qualify.
Page-border candidates cannot enter accepted LINE regions or baseline evidence.
Missing facts cannot provide content-selection support.

A word *group* is a geometric spacing proxy, not proof of a linguistic word.
Image darkness and stroke thickness remain photographic proxies, not pressure.

## Mandatory fixtures / acceptance

- Rights-safe full-frame gray and blue grid, dark-grid same-tone ambiguity,
  grid-only blanks, tabletop page rectangles, near-edge genuine ink, intersections
  and resized/perspective source-frame round trips. No real user writing in public
  CI, code review or Actions artifacts.
- Measure false authoritative line bands, line/word IoU/F1/count MAE, false-zero
  words, unavailable families, ink retention and baseline evidence consistency.
- Benchmark the **same** immutable images and annotations under `legacy`,
  `grid-v1` and `qualified-v2`. Rejections and partial results must be included
  in denominator/coverage; never quietly drop difficult samples.
- Licensed/consented real originals must be handled separately on a protected
  machine. Match exact stored source hashes, freeze writer-disjoint development
  and holdout manifests, independently review annotation disagreement, and
  pre-register acceptance thresholds + holdout manifest digest **before**
  evaluating the holdout. The offline protocol tool checks leakage and pins,
  not legal rights or scientific validity.
- Verify resource ceilings, CPU, memory and latency at real smartphone
  resolutions and the actual deployed wheel/worker—not only NumPy fixtures.
- Python 3.10–3.12, RLS/intake/report, generated-contract check, web/native
  compatibility and source-image overlay coordinates must pass on the exact head.
- Separate isolated Railway test deployment, pinned `/health/build` source SHA,
  signed APK artifact and *actual handset* test are required to approve public
  activation. Emulator success is not handset qualification.

## Quality, versioning and rollback

- Preserve all **64 implemented** Free feature IDs. If their evidentiary
  dependency fails, use existing engine `MISSING` with explicit
  `missing_reason`, null value and no misleading number/confidence.
- Existing product Quality has a separate `REJECTED` status; v2 does not
  silently add it to engine measurements. Whole-job ambiguity may fail closed
  with the existing `GridQualityError` codes and localized recapture guidance.
- Store the v2 configuration hash and `quality-policy/2` in each
  `AnalysisReference`. Do not reinterpret older `ReportDocument` snapshots.
  T18 comparison rejects unknown or mismatched processing hashes.
- Paper ROI detection is optional, conservative and reversible; when the actual
  paper boundary is not qualified, page-margin measurements remain missing.
- Keep `legacy` production-default at v2 merge. A later reviewed deployment
  and policy change is necessary to activate V2 broadly.
- Keep Issue #92 open until privately reproduced, writer-disjoint empirical
  criteria and installed-handset evidence are recorded. Do not close on green
  synthetic tests alone.

## Source and privacy policy

Deterministic OpenCV/NumPy only; **no learned local model, OCR, network AI,
face/person/writer identity model, or third-party source/code copied**.
Source code licenses do not establish rights to photographs or reference datasets.
No pixels, user specimen identifiers, paths or private diagnostics in public CI.

## Next evaluation-integrity slice — synthetic-only frozen runner

The protected real-data run remains **NOT AUTHORIZED** while T11
`pilot_rights_consent` is pending. This engineering slice does not change
the `legacy` runtime default or the 64 canonical Free outputs.

- Preserve the old v1 protocol checker for historical tests, but
  `score_holdout` no longer permits an unverified caller-supplied aggregate
  to return `accepted: true`.
- For v2 engineering tests, freeze **development, validation and holdout**
  synthetic manifest hashes. Partition by writer, capture, source specimen,
  input digest and specimen ID across all three splits. Missing `lines` and
  `words` annotations are unknown, not explicit empty ground truth.
- Pin the actual local checkout commit, evaluator file bytes, qualification
  implementation bytes and qualified-v2 processing configuration in a
  separately prepared reviewed synthetic policy. This is not signed
  execution attestation or permission to ingest real photographs.
- Run the full synthetic holdout through `run_frozen_synthetic_qualification`
  rather than passing the scorer an aggregate. Per-family annotated/nonempty
  coverage retains refused specimens in its denominator. Empty cases cannot
  inflate nonempty handwriting F1. Unset thresholds fail closed.
- Only the synthetic engineering receipt may say `ENGINEERING_PASS`.
  `public_qualification` remains `NOT_AUTHORIZED`; the redacted exporter
  never includes specimen-level IDs, paths or private digests.
- Run `python -m pytest -q tests/test_segmentation_qualification_integrity.py
  tests/test_qualified_segmentation_protocol.py
  tests/test_segmentation_benchmark_frames.py` and all exact-head CI. No
  empirical T06 completion, holdout opening, real-device signoff, Issue #92
  closure or production activation is permitted by a green synthetic run.

Next independent changes: paired comparison and source-frame annotation
families; separate T11-authorized real evaluation and finally exact-SHA
physical-handset qualification.

### Codex qualification integrity repairs

The synthetic v2 gate requires independently scored nonempty handwriting and explicitly annotated empty line/word conditions, with predeclared minimum empty counts, maxima for false-positive pages and minimum empty coverage. It accepts a validation split only under the explicit synthetic-fixture path and rejects duplicate JSON keys and nonfinite constants. Frozen manifest digests use the exact parsed input bytes.

The frozen policy now pins the actual reviewed CI dependency target on Python 3.10/3.11/3.12 (Linux x86_64), NumPy/OpenCV imported and distribution versions, the reviewed lock/manifest digests and the installed distribution map. Unreviewed environments refuse qualification; separate platform qualification needs its own approved lock. Neither source nor dependency hashes replace legal data authorization, independent photo ground truth or device checks.

### Follow-up integrity closeout: trusted verifier and blank abstentions

The checkout integrity pathspec includes `tools/verify_ci_lock.py` and all reviewed `requirements/` snapshots. The frozen policy binds `lock_verifier_sha256`; the imported verifier must resolve to the reviewed file. This is an engineering consistency fence, not a signed attestation against process compromise.

Both `min_empty_line_coverage` and `min_empty_word_coverage` must be strictly positive, and both `minimum_available_empty_line_n` and `minimum_available_empty_word_n` must be positive predeclared counts. A policy allowing zero blank coverage is invalid, not merely a negative score. The scorer independently verifies the number of eligible and actually available blank observations. Unavailable blank pages remain abstentions and never count as measured negatives.


### Round-four repair: independent policy, trusted execution, provenance

An independently approved policy SHA must be recorded before holdout
evaluation. The evaluator requires this externally supplied digest and
rejects a missing, malformed or mismatched approval before scoring. A
digest calculated by the same actor after seeing holdout results is not
proof of prior approval. An independent approval record and its access
controls are out-of-repo governance obligations, not created by tests.

Use an independently approved **external** python -I -S -B
qualification_bootstrap.py (installed outside the evaluated checkout) with
an independent --approved-digest-file. Do not directly execute the repository
worker as the trusted entrypoint. It imports only
standard-library code during bootstrap, authenticates reviewed wheel archives
before third-party imports and verifies installed files against those archives,
not against installed RECORD metadata. A changed imported
module fails closed rather than producing an engineering pass. Process-local
checks are not cryptographic attestations or a substitute for a trusted host.

Synthetic benchmark rows, results and aggregates carry
data_origin: SYNTHETIC_FIXTURE; rights-gated real-source records carry
REAL_SOURCE_DECLARED without claiming legal clearance. Mixed, missing and
unknown origins cannot be combined into human statistics. Public receipts
are allowlisted, redacted and synthetic-only. The unchanged legacy default,
T11 rights gate, Issue #92, real-photo evaluation and physical-device
qualification remain outstanding.

### Round-five closure: immutable inputs and externally authenticated runtime

Freeze each parsed synthetic manifest together with its exact encoded bytes.
The holdout scorer receives this *same* byte snapshot; a changed pathname or
symlink cannot change which records or image digests are evaluated. Every
specimen is opened using a no-follow directory-relative descriptor, read
within a bounded encoded-file budget, hashed, and decoded only from its
verified buffer. Changing unapproved image bytes therefore fails before
decoding.

Use the isolated worktree launcher with original reviewed wheel archives,
verified against `requirements/ci-pyXYZ.lock` before importing any of those
dependencies. The full Python import graph (including standard-library
shadow modules and transitive wheel dependencies) is checked and source
bytecode caches are excluded by fresh Git staging, `-S` and `-B`.
Installed distribution `RECORD` metadata is never accepted as the source
of expected executable-file hashes. This does not attest an untrusted OS,
interpreter, malicious co-process or separately supplied policy digest.

Round five also updates the existing explicit synthetic provenance test
fixtures and the expected early-verifier rejection message. Preserve
`public_qualification: NOT_AUTHORIZED`, T11 pending, Issue #92 open,
and the `legacy` runtime default. Exact-head CI and independent review
remain release prerequisites.


### Round-six synthetic qualification security closeout

Bind all operator-selected paths before switching to the detached worktree.
The internal worker must verify detached worktree identity and cleanliness
before any project import, and must refuse ordinary checkout invocation.
Source bytecode caches are absent from clean source staging; -B by itself
does not guarantee that existing bytecode could not be read. Direct Python
calls outside the approved execution procedure are engineering-only.

Authenticate the execution-relevant reviewed wheel footprint, including
package resources, reviewed installed metadata other than pip-regenerated
RECORD, supported .data relocations, native extensions and versioned shared
objects. Native ELF dependency loads require authentication even without
a corresponding sys.modules entry. The original reviewed wheel archive
SHA-256 remains the independent reference.

Review evidence should include direct worker rejection before altered code
can run, successful relative-path invocation outside the repository, failure
of forged/deleted caches, modified versioned native libraries and unowned
Cython namespaces, and a clean redacted synthetic receipt. Preserve exact-head
CI on Python 3.10/3.11/3.12 and request fresh Codex review. None of these
checks attest an untrusted operating system/interpreter or authorize real data.


### Round-six independent source revision and nonempty-F1 gates

Verify the separately approved policy's raw digest using standard-library
code before project imports, and require its source_commit_sha to match the
revision that the launcher and detached worker will execute. Merely
authenticating files against a *different*, internally consistent clean Git
HEAD is insufficient. The worker must refuse a clean-but-unapproved alternate
commit before loading any project module.

Frozen nonempty line and word F1 acceptance thresholds must be greater than
zero. A policy allowing zero measured segmentation accuracy is invalid, even
if selective coverage and blank specificity look good. Added negative
tests for both zero floors and a fully available but completely mismatched
nonempty detection. All public authority remains NOT_AUTHORIZED.


### Round-seven: external bootstrap, split library roots and honest blank evidence

The earlier command that directly executed
`evaluation/segmentation/run_qualification.py` is superseded. To prevent
unapproved committed launcher code from running before self-verification, an
**externally provisioned and independently authenticated stdlib-only
bootstrap** must run first. Its source template is
`tools/qualification_bootstrap.py`, but copying it from a mutable checkout
without independently validating its expected digest is **not trusted
execution**. The bootstrap checks exact approved policy bytes and pinned
Git revision and stages that approved object, ignoring an unapproved current
checkout HEAD. The worker runs under `-I -S -B` from the verified stage.
External approval of the bootstrap itself remains an operator-governance
step and cannot be manufactured by a unit test.

Wheel validation selects the archive root using authenticated
`Root-Is-Purelib` metadata and retains both interpreter-derived
`purelib` and `platlib` roots, including split lib/lib64 virtualenvs.
The same approved wheel bytes determine verified relocated files, native
libraries and Python modules. Fixed `Q_POLICY`, `Q_SOURCE`, `Q_SITE`,
`Q_WHEEL`, `Q_IMPORT`, `Q_IDENTITY`, `Q_SCORE`, `Q_RECEIPT` and related codes diagnose synthetic rejections
without exposing protected specimen information.

The qualified-empty outcome used to make the synthetic blank accounting
testable is a deliberately narrow, input-only uniform-light fixture
oracle; it is **not native qualified-v2 blank detection**. The redacted
synthetic receipt always says
`blank_evidence_scope: SYNTHETIC_FIXTURE_ORACLE_ONLY`. No scientific
empirical blank accuracy claim, real participant authorization, Issue #92
closure or production activation follows from an engineering pass.


### Round-eight pre-merge review items

1. Confirm Python 3.10 wheel-bundled NumPy bytecode is handled through
   authenticated Python source/code equivalence where applicable, never a
   blanket \`__pycache__\` exception. Source-less altered bytecode is untrusted.
2. Snapshot both exact approved policy bytes and the matching digest into
   sealed Linux memory descriptors and pass them to the worker; mutate the
   original files together between preflight and child launch and prove the
   original snapshot alone is used.
3. Require strictly positive overall and nonempty availability/coverage
   fractions for lines and words; independent preregistration still controls
   scientifically meaningful targets.
4. Composite BGRA inputs as the reviewed context does before deciding a
   synthetic fixture is uniformly light. Preserve unqualified real/ambiguous
   inputs and the \`SYNTHETIC_FIXTURE_ORACLE_ONLY\` public evidence label.
5. Document a reproducible offline core-only local wheelhouse independent
   from application/runtime installations, and prove all Python 3.10–3.12
   exact-head CI checks and new adversarial regressions.

### PR #95 closeout: image resource admission and decoder-parity boundary

The frozen engineering evaluator now enforces application-compatible, header-
only JPEG/PNG dimensions on the exact hash-verified specimen bytes before
OpenCV allocation. Single-frame images are limited to 24 million pixels, and
both width and height must be between 32 and 12,000 pixels. This **does not**
change the benchmark's 25 MiB encoded-file budget or any segmentation score,
measurement formula, report version or production profile. The exact
post-decode dtype, channel and header-dimension checks remain fail-closed.

Production decodes with Pillow plus EXIF transpose, but the synthetic
benchmark still uses OpenCV IMREAD_UNCHANGED. The current evaluator rejects
EXIF orientation 2–8 JPEGs, instead of silently comparing boxes in a different
frame. Parity tests cover high-contrast, orientation-1 gray/RGB/RGBA PNG and
JPEG fixtures; any real-photo decoder harmonization belongs in a separately
versioned/approved evaluation step with coordinate-lineage verification.
Do not classify a header check as complete decompression safety or hardware
RSS/latency qualification.

Finding #14's direct-call caveat remains a trust-scope restriction, not a
license to accept self-reported execution. -B alone is insufficient;
existing .pyc files can be read. A fresh detached worktree sourced from the
**independently approved** commit must be checked for ignored/untracked code
and all project bytecode before first project import. A direct in-process
ENGINEERING_PASS or manually supplied --_staged flag is **not independent
provenance**. Only a separately authenticated external bootstrap and a
recorded independent prior policy approval can support *synthetic-only*
engineering acceptance. Neither proves host integrity or authorizes real
handwriting. Keep public_qualification: NOT_AUTHORIZED, legacy active,
T11 pending and Issue #92 open.

Closeout after implementation requires the complete **new-head** CI matrix,
a genuine independent code/security review of that SHA and individual
evidence-backed review-thread reconciliation. A Codex usage-limit message is
not a review. Do not close historical threads or merge merely on green CI.

### Authenticated snapshot & bounded matcher — final PR #95 repair

Git checkout and Git status on the caller's source repository are not
acceptable trust primitives: replace refs can redirect Git objects, and
checkout filters/fsmonitor hooks can execute before a post-checkout hash
comparison. The external bootstrap instead verifies exact approved SHA-1
commit/tree/blob objects, imports only those objects into a fresh isolated
store, and materializes all files directly without checkout conversion.
It rejects symlinks, gitlinks, nonstandard modes, content/path collisions,
missing/oversized objects and unreviewed pyc before project imports. The
source repository's refs, config, hooks, worktree list and working files
must remain untouched. Tests use disposable repositories; never install
malicious Git configs or replacement refs into the real project checkout.

All remaining worker and final identity Git calls use a controlled, replacement-
disabled and fsmonitor-disabled subprocess environment. The independently
provisioned bootstrap itself and the trusted OS/Git/Python remain explicit
assumptions; the source tree cannot self-approve by matching its own HEAD.
Preserve sealed policy/digest FDs, exact approved source SHA, pre-import
reviewed dependency authentication and only redacted synthetic receipts.

The benchmark now pins the matcher to iou-maxcard-hk/1 with bounded spatial
candidate generation, iterative maximum-cardinality matching and a shared
manifest-wide deterministic complexity budget. A matching limit refusal is
an error, not zero evidence, an abstention, or a passing benchmark. The
secondary pair-dependent IoU/center metrics must never be interpreted as
bitwise comparable with the old recursive matching implementation without
a matcher-method version check. Re-register an independently approved frozen
policy for the new source SHA before any synthetic holdout run; old digest
approvals cannot be carried forward. This remains NOT_AUTHORIZED for real
human-data or public production promotion.

Review and release gates: exact-new-head Python 3.10/3.11/3.12 CI, app
environments, docs, roadmap, adversarial Git tests and matcher budget tests;
a fresh independent code/security review; evidence-backed reconciliation
of all historical Codex threads. Do not merge on unit-test success alone.
Issue #92 and T11 remain separate product/rights blockers.
