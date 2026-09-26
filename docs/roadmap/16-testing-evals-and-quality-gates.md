# 16 — Tests, evaluation and evidence required to advance

[Index](00-index.md) · [Tasks](06-agent-backlog.md) · [Security](17-security-privacy-and-abuse.md) · [Release](21-release-readiness-checklists.md).

## Evidence discipline

Every result identifies commit, environment, resolved dependencies, fixture/corpus release, command, exit code and artifact. A proposed command is not a test result. Synthetic geometry proves a numerical/interface property, not population validity. A sandbox purchase proves integration behavior, not real commercial approval. A signed app binary is not store approval.

The repository's existing Python CI is retained. This roadmap adds a documentation validator/workflow; it does not implement product suites by naming them. The baseline PR recorded 158 pytest passes per Python minor before merge. New PRs must execute their exact head and report current counts rather than copying that number.

## Existing checks

Use the complete current `.github/workflows/ci.yml`: hash-authenticated dependency installation, project/build dependency policy, closed locked `Requires-Dist` graph, sandboxed backend-reported build requirements, exact installed environment, `pip check`, feature/Premium compiler drift, all graphology validators, compile, Ruff, pytest, research checks, offline wheel build and installed-wheel smoke. T00A closes the four post-merge findings without relaxing these checks.

Documentation commands introduced here:

```bash
python docs/roadmap/plan_tools.py --check
python docs/roadmap/plan_tools.py --ready
python -m unittest discover -s docs/roadmap -p 'test_plan_tools.py'
```

`--write` is a maintenance command, not validation. It regenerates the human backlog from the machine plan. CI uses `--check` so stale generated text fails rather than being silently overwritten.

## Planned suite contract

The following suites are `TO_IMPLEMENT` in the owning tasks. Each task must add the exact runnable command to its README/CI and update its task record when the suite exists.

| Suite | Owner | Required coverage |
|---|---|---|
| Product schema/codegen | T01 | Positive/negative DTO fixtures; closed enums; finite numbers; round-trip Python/TS; schema/OpenAPI drift; version compatibility. |
| Free isolation | T01/T28 | No learned/provider dependency closure; no provider key; provider-egress denied; numerical output unchanged; installed-wheel execution. |
| PostgreSQL/ownership | T02 | Actual non-owner runtime role; RLS/tenant boundaries; composite region/run FKs; guest migration; concurrent transactions. SQLite is not the authority for PostgreSQL behavior. |
| Intake/jobs | T04 | Decode bombs, format spoofing, limits, immutable asset binding, duplicate submission, stale leases, crash windows and deletion fencing. |
| Evidence geometry | T05 | Aggregate-observation consistency; transform round trips; region references; actual bins; deterministic ordering; missing reasons. |
| Real calibration | T06/T11 | Writer-disjoint ground truth, repeat captures, coverage/error by context, annotator disagreement, predeclared tolerances. |
| Reference/statistics | T12–T14 | Tie/constant/missing cases, leave-writer-out, multiplicity, cohort selection, contributor withdrawal, reproducible releases. |
| Report/projection | T09 | No hidden paid fields; grant-specific assets; immutable revisions; reading/export never calls model. |
| Connector conformance | T27/owners | Typed errors, timeouts, retries, environment mismatch, signatures, replay, unsupported capabilities and fake/live parity. |
| Premium/evals | T15/T16 | Invalid enums/support, refusal/truncation, image prompt injection, no-reference, hallucinated number, forbidden claim, unknown outcome and budget cap. |
| Commerce | T19 | Provider verification, pending handling, native completion, one grant, reservation races, refunds, recovery, cross-account token reuse. |
| Web/render | T17/T20/T21 | Playwright journeys, accessibility, canonical fact parity, PDF text/visual inspection, long Swedish labels, no-network rendering. |
| Native | T29–T31 | JS unit tests plus native integration/device flows: process death, permissions, secure storage, links, pushes, purchases, restore, tablet and accessibility. |
| Release/recovery | T23/T24/T32/T33 | Full journeys, real sandbox/store artifacts, migration compatibility, restore/tombstones, observability and staged rollout rehearsal. |

## Mandatory adversarial fixture families

Name fixtures by behavior, not flattering content: `blank`, `low_contrast`, `rotated`, `cropped_page`, `heic_orientation`, `unsupported_script`, `partial_evidence`, `no_reference`, `constant_reference`, `zero_denominator`, `cross_owner`, `revoked_grant`, `stale_method`, `purchase_pending`, `purchase_replay`, `refund_after_spend`, `provider_timeout_ambiguous`, `image_prompt_injection`, `deleted_during_job`, `late_response_previous_account`.

Fixtures are synthetic or have explicit engineering-use permission. Do not check private participant handwriting into Git. Test image-coordinate overlays with known synthetic shapes; test real accuracy on a protected writer-disjoint corpus. Test the same report facts across web, native, PDF and share payloads, including evidence labels and rounding.

## Acceptance levels

Unit tests validate pure functions/state transitions. Integration tests validate actual PostgreSQL locks/roles, storage profiles and provider signatures. Contract tests compare generated clients/adapters. E2E tests exercise the user journey with controlled fakes/sandboxes. Empirical evals assess measurement/model claims. Store/device acceptance exercises actual signed binaries and platform payment/permission behavior. All are needed for their relevant release gate; none substitutes for the others.

Predeclare target numerical error, coverage, latency, failure/refund rate and critical/non-critical model rubric before measuring a held-out release. These targets are owner/reviewer decisions; this roadmap invents no passing score, recruitment count or provider price. Critical disclosure/billing/factuality failures block activation regardless of an average score.

## CI expansion without weakening T00

Partition core, API, Premium, render and native dependencies. Add lock closure/artifact checks for new ecosystems. Keep paid calls absent from default CI. Use opt-in protected provider/store sandbox jobs with budget and retained redacted evidence. Native emulator smoke may run per change; real-device/store lifecycle evidence is still required before T30/T31/T32/T33 close.

Record historical evidence append-only and the currently tested head separately. A late review finding creates a linked follow-up task or reopens the affected task; a code green badge is not a waiver. Do not automatically regenerate locks or accept snapshots on a failing PR.
