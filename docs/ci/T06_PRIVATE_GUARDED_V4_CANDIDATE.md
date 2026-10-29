# T06 — private guarded-v2 to Free /4 composition candidate

**Status:** Synthetic/private local/test **only**. NOT a reviewed nonresearch measurement policy, rights decision, empirical accuracy finding, real source authorization, production activation, or Issue #92 closure.

This bounded code slice composes three **already independently versioned** authorities without changing their identities:

1. `qualified-v2` with `quality-policy/2` (geometry, word-groups and nullable measurement families);
2. `evidence-support/5` (independent residual-rule audit and conservative 60-feature abstention);
3. The reviewed but inactive Free `individual-report/4` story with exact R1 registry SHA, six chapters and all 64 facts.

The route is available only when **every** existing research/source pin is explicitly set in a private `PRINCESS_ENV=local|test` service. A public guest-only test stack, staging, preview, and production refuse it. No new HTTP parameter or new production toggle is added.

## Guarded test configuration

Set separately on the private API and analysis worker and use the **same approved/test fixture** digest (never copy a digest from a different engine profile):

```text
PRINCESS_ENV=test
PRINCESS_ANALYSIS_PROFILE=qualified-v2
PRINCESS_SEGMENTATION_V2_RESEARCH_OPT_IN=1
PRINCESS_EVIDENCE_SUPPORT_RESEARCH_OPT_IN=1
PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256=<exact digest of qualified-v2 + evidence-support/5>
PRINCESS_REPORT_STORY_V2_ENABLED=1
PRINCESS_EXPECTED_REPORT_TEMPLATE_VERSION=individual-report/4
PRINCESS_EXPECTED_FREE_READING_REGISTRY_SHA256=<exact approved R1 Free registry SHA>
```

Existing policy/permission, component and secret/environment requirements still apply. The API and worker independently resolve the existing profile and compare `analysis_config_sha256`; the story source loader also requires the preexisting verified story digest. Without exact matching inputs startup fails closed. The public Railway guest stack must **never** be repointed to this candidate.

## Expected job and report identity

- Admission pins `report_template=individual-report/4`, `analysis_config=<qualified-v2+v5 digest>`, explicit EN/SV locale, source digest, capture SHA and permission epoch in the queued job.
- The worker claims only exact `/4` jobs with the matching configuration and story-source digest; legacy `/2` and historical research `/3` jobs remain untouched, including after rollback.
- One deterministic engine pass produces real data-supported or `MISSING` facts; `evidence-support/5` may withhold 60 dependent facts and all unsupported LINE/WORD/BASELINE evidence. No image-derived number may be recomputed by the story, clients or export.
- The resulting Free /4 is an immutable saved snapshot, readable after the candidate is disabled. **Premium-v2 requests are still separately blocked** until the reviewed R3 offer, validation/value, image authorization and atomic publication exist. The pending S92-05A fence is [PR #128](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/pull/128).

## Verification and remaining gates

`tests/test_report_reading_config.py` now covers affirmative private source selection and guarded /4 worker claim identity, plus missing/forged digest, disabled companion flag, legacy-profile mismatch and public/staging/production rejection. Existing release/runtime, Postgres claim, analysis and report tests must all pass on the exact PR head.

A unit-test claim does not prove source-image inference accuracy. Before any *real* protected capture, the T11 rights/consent gate must be signed. Before public use, Issue #92 still needs original photo replay (or explicit unavailability), real writer-disjoint annotated error **and** coverage evidence, approval of a **new separately versioned nonresearch release policy**, physical-device proof and named rollout/rollback review. Do not reuse this research combination as an approved production policy merely by changing environment flags.

**Rollback:** disable the story writer or either research flag and restore the legacy writer; immutable queued and saved identities are not mutated. If code is reverted, already stored /4 snapshots retain their read semantics. No migrations or data backfills.
