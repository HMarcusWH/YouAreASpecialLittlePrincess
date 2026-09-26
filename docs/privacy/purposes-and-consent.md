# Purposes, notices and consent events

[Privacy drafts](README.md) · [purposes.json](../../contracts/consent/v1/purposes.json) · [notices.json](../../contracts/consent/v1/notices.json) · [consent-event schema](../../contracts/consent/v1/schemas/consent-event.schema.json)

Status: draft pending owner review. Legal bases are `PENDING_OWNER_DECISION` for every purpose.

## Purpose registry v1

| Purpose | Subject | Grant scopes | Required for Free? | Notes |
|---|---|---|---|---|
| `service_processing` | writer | specimen | yes: it *is* the analysis | Nothing leaves the application. The only purpose that may affect Free. |
| `image_retention` | writer | subject-wide, specimen | no | Saved visual history. Without it, originals are deleted after analysis. |
| `third_party_ai_processing` | writer | report | no | Per report. Payment or entitlement never implies it. Gated on provider/spend/eval decisions. |
| `ordinary_sharing` | writer | share grant | no | A revocable link/card for an allowlisted projection. Downloaded copies cannot be recalled. |
| `partner_comparison` | writer | comparison | no | **Each author** grants for their own input. Sharing a report is not comparison permission. |
| `reference_contribution` | writer | subject-wide, specimen | no | Candidate reference membership. Gated on `pilot_rights_consent`, `public_reference_validation` and `benchmark_promotion`. |
| `engineering_evaluation` | writer | pilot enrollment, specimen | no | Protected accuracy/robustness and annotation work. Separate from contribution. |
| `support_human_review` | writer | support case | no | Restricted staff may view a private sample for one case. |
| `product_analytics` | account | subject-wide | no | Allowlisted usage events only; no handwriting. |
| `model_training` | writer | — | no | `NOT_OFFERED`. Defined so no other permission can be read as it. |
| `public_example` | writer | — | no | `NOT_OFFERED` in v1; no galleries or public examples. |

Each purpose record also lists data categories, recipients, retention classes, withdrawal propagation, the human gates it depends on, and `not_implied_by` (always including `purchase`).

## Consent events

The permission ledger is append-only. Each `GRANT`, `DENY` or `WITHDRAW` event carries:

- subject, purpose/version, notice/version and scope;
- the actor, what the UI presented as the default, and the capture method;
- the subject's self-declared eligibility at the time the event was captured (`subject_eligibility`);
- `derived_from` (for example an account deletion or support request);
- surface, recorded and effective times, and an evidence pointer.

Evidence such as signed agreements lives in protected storage and is referenced by an opaque ID. Events are never edited. A correction is a new event.

An event is **invalid** and never changes state when any of these hold (validator codes in brackets):

- The purpose is unknown [`UNKNOWN_PURPOSE`]. A grant targets a purpose that is not offered [`PURPOSE_NOT_OFFERED`], or one that is still a draft outside synthetic fixtures [`PURPOSE_NOT_APPROVED`].
- The scope kind is not allowed for the purpose [`SCOPE_NOT_ALLOWED`], or a subject-wide scope names someone else [`SCOPE_SUBJECT_MISMATCH`].
- A grant was collected under a notice that was not in effect when recorded [`OBSOLETE_NOTICE`, `NOTICE_NOT_YET_IN_EFFECT`]. Any event naming a notice that does not cover the purpose is also invalid [`NOTICE_DOES_NOT_COVER_PURPOSE`]. **Denials and withdrawals** are honoured under any notice the subject was ever shown.
- The event is backdated [`BACKDATED_EVENT`], or a withdrawal is scheduled for later instead of taking effect immediately [`DELAYED_WITHDRAWAL`].
- A grant is derived from a purchase or entitlement [`PAYMENT_IS_NOT_CONSENT`] or from any other business event [`GRANT_MUST_BE_DIRECT`].
- A grant was prechecked [`PRECHECKED_GRANT`], was never presented [`CHOICE_NOT_PRESENTED`], or was not captured through an explicit control or signed pilot agreement [`GRANT_NOT_EXPLICIT`].
- The actor lacks authority: another account, staff or system granting for a writer [`NO_AUTHOR_AUTHORITY`]. A withdrawal must come from the subject, from staff acting on a verified support request, or from the system on account deletion, share revocation or purpose retirement [`NO_AUTHORITY`].
- A grant's evidence is still `PENDING` [`EVIDENCE_PENDING`]. Restrictive choices fail closed: a denial or withdrawal takes effect while its evidence is pending.
- A grant for a purpose requiring an adult declaration was captured without `DECLARED_ADULT` [`INELIGIBLE_AT_GRANT`]. A later declaration never revives it; the writer must grant again.

## Evaluating a permission

`evaluate_permission(subject, purpose@version, scope, at)` in [validate_consent_protocol.py](../../tools/validate_consent_protocol.py) is the reference semantics:

1. The purpose is unknown or not offered → `NOT_OFFERED`. It is still a draft → `NOT_APPROVED`, unless the evaluator runs in fixture mode for synthetic scenarios. Draft purposes never permit a real decision.
2. The purpose requires an adult declaration and the writer's current eligibility is not `DECLARED_ADULT` → `INELIGIBLE`. The grant must also have been captured with `DECLARED_ADULT` (see above).
3. The query scope kind is not one the purpose grants → `SCOPE_NOT_GRANTABLE`. A broad grant never authorizes a use the purpose does not offer.
4. Among **valid** events for the same subject and purpose version, keep those effective at `at` whose scope is one of the following: the query scope; subject-wide for the same subject; or a broader scope the caller vouches contains the query, such as a specimen's pilot enrollment.
5. No such event → `NOT_ASKED`. Otherwise the latest event wins: `PERMITTED`, `DENIED` or `WITHDRAWN`. Ties resolve to the more restrictive state.

A **use** (Premium job, benchmark build, share publication) must be `PERMITTED` both when it starts and immediately before it publishes (`BLOCKED_AT_START` / `BLOCKED_AT_PUBLICATION`). A **comparison** needs every author's `partner_comparison` permission for that comparison. The **Free report** is available when `service_processing` is permitted. It is the only purpose allowed to be `required_for_service`, and optional purposes are not consulted at all.

## Versioning and rollback

A material change to what a purpose means creates a new `purpose_version`. Grants for version 1 never authorize version 2 (see the `purpose_version_change_keeps_historical_meaning` scenario), so historical grants keep their meaning. Notice wording changes create a new notice version with a non-overlapping effective window. A notice can only be `ACTIVE` once every purpose it lists is `APPROVED` (`NOTICE_ACTIVE_FOR_UNAPPROVED_PURPOSE`). Approvals and reviews always carry a non-null `decision_ref`. Rolling back stops future collection under the new version; it never rewrites recorded events.

## Relation to other tasks

- T01 maps these schemas into product DTOs and codegen; the enum values and IDs here are the draft source until then.
- T02 persists the ledger with owner-scoped access and implements this evaluator.
- T04/T15/T19/T22 re-check permission at publication time.
- T24 executes deletion.
- The payment ledger (T19) never writes consent events.
