# Source rights register

[Privacy drafts](README.md) · [source_rights.json](../../contracts/consent/v1/source_rights.json) · [Corpus chapter §2](../roadmap/02-corpus-benchmarks.md) · [Evidence register](../roadmap/07-evidence-register.md)

Status: every source is `PENDING_REVIEW`. No external dataset is cleared for any use.

## Three separate rights

A source record keeps **code**, **data** and **model-weight** rights apart, each with its own status and observed terms. A permissive code licence, public-domain software wording or a public download URL clears nothing about the data or any weights. The validator enforces this:

- A use may be `CLEARED` only when the **data** right is `CLEARED` [`USE_CLEARED_WITHOUT_DATA_RIGHTS`].
- While data rights are `NOT_CLEARED`, every use stays `NOT_CLEARED` [`USE_OPEN_ON_UNCLEARED_DATA`].
- Any clearance requires a recorded review with a decision reference [`CLEARED_WITHOUT_REVIEW`]. For an external dataset, the review must also pin the exact archive SHA-256 [`REVIEW_WITHOUT_ARCHIVE_HASH`].
- A review records `expires_on` (null only when the terms have no end), after `reviewed_on` [`REVIEW_WINDOW_INVALID`]. A release is refused when the clearance has expired by its cutoff or publication [`SOURCE_NOT_CLEARED`].
- A review binds what it cleared: `review.content_sha256` is the SHA-256 of the source's canonical JSON without `review_status` and `review`. Clearing another use, changing a right or its terms, or dropping a restriction afterwards is `REVIEW_CONTENT_MISMATCH`, and no release can rely on the old review.

Uses are tracked separately: engineering testing, benchmark statistics, display, redistribution and model training.

The collection protocol names its source (`source_id: owned_pilot_collection_v1`), and it must be an owned collection [`UNKNOWN_SOURCE`]. A human release from that collection counts nothing until its data rights and the release's use are cleared by a recorded review [`SOURCE_NOT_CLEARED`]: `engineering_testing` for an `engineering_evaluation` release and `benchmark_statistics` for a `reference_contribution` release. Participant consent is necessary but never sufficient.

## Current entries

| Source | Data rights (observed) | Uses | Why |
|---|---|---|---|
| `owned_pilot_collection_v1` | pending | testing and statistics pending; display, redistribution and training not cleared | Rights come from per-participant permissions under an approved agreement; nothing collected yet. |
| `iam_handwriting_database` | not cleared | all not cleared | Publisher terms (inspected 2026-09-25) specify non-commercial research use. |
| `cvl_database` | not cleared | all not cleared | Publisher states non-commercial restrictions. |
| `nist_special_database_19` | pending | all pending | Software wording is described separately from the data licence. |
| `dhsd_v1` | pending | all pending | CC BY 4.0 statement plus an OpenStreetMap/ODbL provenance caveat; both layers need review. |

The observed terms are copied from the dated publisher inspection recorded in the roadmap. They must be re-verified against the exact archive before any review decision.
