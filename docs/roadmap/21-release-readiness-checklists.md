# 21 — Release readiness and explicit human gates

[Index](00-index.md) · [Task graph](tasks.json) · [Tests](16-testing-evals-and-quality-gates.md) · [Final signoff](../release/multi-platform-signoff.md).

## Do not collapse readiness states

Engineering complete, empirically validated, rights approved, provider enabled, store accepted and publicly released are different states. T00/T26 historical DONE markers do not imply a public app. T32/T33 store-ready evidence does not itself authorize rollout; T25 does. A web alpha is a deliberate earlier slice, not a waiver of the full programme.

## Gate matrix

| Gate | Required evidence | Until approved |
|---|---|---|
| Foundation | T00A disposition, exact-head core/docs/lock checks, stable T01 contracts | No claim of closed dependency hardening. |
| Protocol/rights | Original collection prompts, purpose grants, withdrawal/retention policy, source/license decisions | Synthetic fixtures; no recruitment or benchmark ingestion without permission. |
| Calibration | Writer-disjoint annotations, error/coverage/repeatability, declared supported contexts | Experimental labels; withhold claims requiring validation. |
| Reference | Frozen cohort/release, eligible writer counts, uncertainty, multiplicity, withdrawal/rollback | No rarity/percentile badge or fabricated cohort. |
| Traditional content | Reviewed source/wording/eligibility and separate activation decision | T26 structure remains inactive; mechanical content only. |
| Provider/model | Account access, image data controls, model/SDK support, eval rubric/result, spend limits | Mock adapter; no live paid inference. |
| Commerce | Product/SKU/storefront mapping, prices/terms/taxes/refunds, verified grants and completion/recovery tests | Fake/sandbox only; no real charges. |
| Native signing/accounts | Team/package IDs, protected signing, current SDK/build matrix, named account owner | Local/emulator development only within permitted setup. |
| Privacy/security | Data inventory, SDK audit, authorization/deletion, threat-model tests, support access | Restricted private alpha only. |
| Operations | Monitoring owner, recovery/tombstone drill, payment/job reconciliation, cost breakers | No unattended public paid traffic. |
| Apple | T30/T32 evidence and current App Store/TestFlight/product/privacy review status | No claim of App Store availability. |
| Google Play | T31/T33 evidence and applicable account testing/production access/product/policy status | No claim of Play production availability. |
| Public release | All required capabilities/gates, accepted limitations, versioned artifacts and named approver | Staging/beta only. |

## Cross-platform acceptance journey

Test on web desktop/mobile, iPhone/iPad and the approved Android phone/tablet matrix: own-handwriting capture/upload; corrective quality feedback; useful partial Free report; evidence interaction; account/history recovery; native/web product display; pending/cancelled/successful verified purchase; Premium generation/refusal/failure; no extra inference on reopen; same-owner comparison and explicitly authorized partner comparison; redacted sharing; same-fact PDF; push/deep-link reopen; logout/account switch; account/data deletion.

Check the journey with no reference corpus, no active traditional pack, provider outage, duplicate transactions, revoked partner grant and deletion during a job. Unsupported features must be omitted/labelled, not made to look completed. Final marketed scope must match actual capability flags and store screenshots.

## Required evidence bundle

Every release candidate records source commit, artifact/container/IPA/AAB hashes, schema/engine/reference/model/template versions, dependency/build matrix, migration plan, exact test results, real-device list, store sandbox outcomes, privacy notices, owner gates, support runbooks, rollback/halt plan and current policy verification dates. Keep private approval documents outside Git; link safe references. No unchecked checklist becomes approved because an agent filled a field.

Use the platform-specific checklists: [web](../release/web.md), [Apple](../release/apple.md), [Android](../release/android.md). [Multi-platform signoff](../release/multi-platform-signoff.md) is the final owner record and requires actual approvals.
