> Maintainer note: this chapter retains design requirements and dated research/examples. For what runs now use the [handover snapshot](../handover/current-state.md), [implemented architecture](../architecture/overview.md), [current API](../reference/api.md) and [safe commands](../reference/commands.md). Historical model/price/route examples are not approved current configuration.

<!-- roadmap-v2-navigation -->
> **Roadmap v2 navigation and scope:** [index](00-index.md) · [task briefs](06-agent-backlog.md) · [machine graph](tasks.json) · [build sequence](20-end-to-end-build-sequence.md).
> This chapter's technical content is retained. Historical implementation/status examples are superseded by [tasks.json](tasks.json) and the [v2 authority amendments](00-index.md): web, iOS and Android/native payments are main-programme scope; T00, T00A and T26 are DONE; T26 remains reviewed but runtime-inactive. Earlier model aliases/prices/API examples are dated research, not approved configuration; see [current source refresh](22-research-and-source-refresh.md). Required release/owner gates are not completed by this documentation.

# 01 — Data architecture and contracts

Status: mixed implemented/current data architecture plus planned reference/release layers. The product PostgreSQL/RLS plane and reviewed migrations exist; reference-corpus/release work remains downstream. Sources and historical baseline evidence are in [07](07-evidence-register.md).

## 1. Three data planes

**Product plane:** private accounts, uploads, analyses, reports, purchases, sharing permissions and deletion jobs. This plane answers 'whose data is this and what may this user do?'

**Reference plane:** licensed/consented candidate samples, cohort definitions, reproducible benchmark releases, calibration artifacts and quality summaries. This plane answers 'what comparison is defensible for this sample?'

**Content plane:** versioned feature definitions, method capabilities, metric display rules, editorial explanations, traditional graphology associations, archetype rules and localization. This plane answers 'what does this field mean, and which claims may we display?'

These can start in one PostgreSQL database with separate schemas and database roles. They are not three microservices by default. Private object storage holds images and export artifacts; the database holds relationships, permission records and metadata. Keep the 272-feature source JSON in Git as the schema authority, then seed a versioned database projection. [S01, S02, P03]

Do not use 272 nullable columns as the universal data model. Do not make an unvalidated JSON blob the only queryable record either. Use relational foreign keys/constraints for identity and lifecycle, typed scalar projections for statistics, and JSONB for validated variable-shape payloads and immutable reports.

## 2. Logical tables and grain

| Table/group | One row represents | Important keys and fields |
|---|---|---|
| `account`, `session` | An authenticated or short-lived guest owner | UUID, auth-provider subject, expiry; no home-grown password system. |
| `writer` | A pseudonymous declared human author | Separate from uploader/account; author-consent linkage. No handwriting-based identity inference. |
| `consent_event` | One grant/withdrawal for a purpose | Subject, purpose, policy version, scope, recorded time, effective time, actor, evidence reference. |
| `sample`, `capture` | A writing specimen and a particular image of it | Writer, task/prompt version, sample type, surface, instrument, script/language declaration; multiple captures of one specimen are not new writers. |
| `asset` | A private original, derivative or export | Owner, storage key, content hash, media type, dimensions, transform lineage, rights/retention scope, expiry/deletion state. |
| `analysis_run` | An immutable attempt on a capture | Engine/schema/configuration versions, input/processed hashes, status, timing, error code, coordinate transforms, result digest. |
| `measurement` | One sample-level canonical feature in a run | Unique `(run_id, feature_id)`; versioned definition FK; typed value/payload, unit, quality, missing reason, method and confidence metadata. |
| `region`, `measurement_region` | A region and evidence links within one run | Half-open bounds, scope, parent ID, transform frame; composite FKs prevent cross-run links. |
| `observation` | Optional individual line/word/glyph observation | Separate versioned contract with run, feature, region, observation index and units; never replace aggregate keys implicitly. |
| `feature_definition`, `method_definition` | One immutable definition/method version | Canonical ID, type, unit, semantics hash; method dependencies, AI requirement, input mode, validation state. |
| `normalization_release`, `normalized_value` | A transformation release and one transformed metric | Formula, parameter/source versions, valid domain, missingness; distinguish x-height scaling from reference ranking. |
| `dataset_source`, `license_review` | An external or owned dataset release and its rights decision | Exact source/archive checksum, allowed purposes, restrictions, attribution, reviewer, expiry and approval artifact. |
| `corpus_candidate` | A sample proposed for reference use | Consent/rights snapshot, duplicate group, quality eligibility, exclusion reasons, review state. |
| `cohort_definition` | A fixed eligibility specification | Language/script/task/capture/surface rules, feature subset, writer weighting, statistical plan. |
| `benchmark_release`, `benchmark_member` | A published snapshot and its member mapping | Cutoff, analysis/normalization versions, membership hash, writer IDs, eligible feature masks, role/split and status. |
| `benchmark_feature_summary` | Statistics for one feature/cohort/release | N writers, missingness, quantiles/CDF artifact, domain and uncertainty metadata. |
| `reference_vector` | A private deterministic comparison vector | Feature-set/version/mask, source run, cohort/release, family normalization; not an LLM text embedding. |
| `content_source`, `rule_pack`, `rule`, `rule_hit` | Reviewed editorial provenance and evaluated rules | Condition tree, canonical feature IDs, source location, evidence class, applicability, unknown/conflict outcomes. |
| `selector_value_set`, `selector_definition`, `question_definition`, `question_pack`, `soft_field_definition`, `candidate_definition` | One versioned Premium interpretation control record | Stable IDs, allowed pick values, dynamic candidate source, evidence requirements, text bounds, fallbacks, report mappings and localization keys. |
| `report`, `report_revision` | A user report and immutable content snapshot | Kind, owner/grants, analysis/reference/rule versions, locale, approved fact set, Premium overlay reference. |
| `comparison`, `comparison_input` | A pair/history request and ordered sources | Both authorized inputs, comparison method/version, common feature mask, visibility agreement. |
| `premium_job`, `provider_attempt` | A business job and each actual provider request | Idempotency key, prompt/model, evidence digest, token usage, request ID, budget reservation, validated output or failure. |
| `purchase`, `entitlement`, `ledger_entry` | A payment, analysis-specific capability, and immutable accounting event | Provider event/transaction uniqueness, amount/currency, fulfilled/refunded state. |
| `share_grant`, `report_artifact` | Explicit disclosure permission and generated bytes | Allowed fields, token hash, expiry/revocation, snapshot/template hash, asset linkage. |
| `job`, `outbox_event`, `deletion_job`, `audit_event` | Durable operational work and metadata | Lease/version, attempts, dedupe key, minimal actor/object IDs; no raw writing in logs. |

Implement these groups incrementally in the backlog; this is a logical model, not a demand for dozens of empty services on day one. Split tables only where lifecycle, grain or permissions differ.

## 3. Measurement storage contract

Keep the existing aggregate API unchanged initially. [R02]

- `measurement.raw_value` follows its definition's declared type. Scalars receive a typed query projection; vectors/distributions carry a validated shape and version. Reject NaN/Infinity, booleans masquerading as integers, illegal ranges and mismatched units.
- Missing values have no numerical substitute. Preserve `missing_reason`, `quality_flag`, sample count and `confidence_kind`. Do not turn uncalibrated `confidence=null` into zero or 0.95.
- `n_observations` counts this method's observations, not people in a reference corpus. Store reference writer counts elsewhere.
- Confidence is not a personality-validity probability; a stable engineering index is not automatically a calibrated probability either.
- Persist authoritative result JSON and its relational projections in the same transaction. Validate row count, IDs and digest to prevent two diverging sources of truth.
- Database FK is `(schema_version, feature_id)`; method/spec semantics hashes detect incompatible redefinitions. Compare only compatible outputs. New methods may share an ID only when they implement the same estimand.
- Region membership cannot cross runs or tenants. Validate parent containment/cycles and the complete original-image -> crop -> perspective -> resize -> deskew transform chain.

Today's dictionary cannot represent repeated per-line observations under the same feature key. Add `observations` beside aggregates with an explicit API version when required. Until then, histograms and traces need a separate evidence payload; a mean and standard deviation do not reconstruct the real distribution.

## 4. Capability manifest

For each method record `method_id`, `method_version`, `feature_ids`, `input_modes`, `requires_learned_inference`, `requires_external_provider`, `dependencies`, `license_review_id`, `validation_release`, and `supported_cohorts`.

Resolve the transitive dependency graph before execution. Free accepts only methods with no learned/provider dependency. A nominally deterministic derived axis requiring neural glyph identification is not Free-eligible. Sensor methods are not photo methods. Do not infer runtime availability from a database definition's `CORE` status or `free_compute` flag.

Use separate deployment extras and credentials. The Free worker imports the pure engine and approved classical modules; it has no provider key, model weights or provider network access. Guard this with dependency scanning, an import test and provider-egress-denied end-to-end tests.

## 5. Versions and immutability

Every report pins:

`schema_version`, `engine_version`, `method_manifest_hash`, `analysis_config_hash`, `quality_policy_version`, `normalization_version`, `feature_set_version`, `cohort_id`, `benchmark_release_id` (nullable), `rule_pack_version` (nullable), `prompt_version` (nullable), `model_requested/model_returned` (nullable), `content_schema_version`, `template_version`, and `locale`.

Immutability means values do not silently change when software or a reference population changes. It does **not** override erasure, revoked disclosure, license removal or legal retention requirements. Maintain report status separately: an old snapshot can become unavailable or have its historical reference annotation withdrawn without editing its original numerical record invisibly.

Re-analysis creates a new run. Re-benchmarking creates a new report revision with an explicit 'updated reference' label. Compare historical handwriting under the same method/reference version; otherwise show that methodological differences prevent a clean trend.

Cache numerical work by input hash + transform/configuration + engine/schema/method versions. Scope cache lookup by owner and rights; a global content-hash lookup must not reveal whether someone else uploaded the same image. Premium and render caches add their own evidence, entitlement/visibility, locale and template/model versions. Consent is checked at use time, not only when a cache was written.

## 6. Content and rule database

The schema reserves 16 traditional interpretation targets, but that does not populate the actual associations or justify example weights. [P03]

Create the Premium interpretation database described in [08](08-premium-question-selector-database.md) before compiling production prompts. Fixed semantic choices, question wording, dynamic candidate sources and soft-text bounds belong in versioned content data rather than hard-coded prompt strings.

Create a small reviewed content pack before promising traditional readings. Each rule requires: paraphrased association, original school/source, exact page or section, reuse permission as needed, feature conditions, valid input context, quality prerequisites, explicit unsupported-personality evidence label, conflicting-source notes and localized authored text. Use three-valued evaluation: true, false, unknown. Missing data never counts as a negative trait.

Do not synthesize production weights from arbitrary illustrative `+0.6` examples. Start with categorical, transparent rule hits and deterministic geometric style names. An interpretive radar can be introduced only with an explicit, versioned scoring definition; it remains a product/traditional construct, never a psychometric score or personality percentile.

Mechanical axes also need actual formulas, domains, weights and monotonicity tests. Existing formula sketches do not justify replacing missing components with zero, double-counting the same regularity signal, or showing all ten axes immediately.

## 7. Access and performance

App/API roles are not database owners, superusers or `BYPASSRLS` roles. Enable owner-scoped policies and test them with the actual production role; RLS owners have different bypass behavior. Reference member/vector tables are service-only. Sharing resolves an explicit grant and produces an allowlisted projection; it does not expose underlying private rows. [S01]

Index owner/time for history; run/feature for retrieval; release/cohort/feature for reference queries; provider event/idempotency key for deduplication; job state/lease expiry for workers. Keep large assets outside PostgreSQL. Begin with exact comparisons over bounded deterministic vectors; approximate nearest-neighbor infrastructure is unnecessary for v1 and cannot fix a poorly defined similarity metric.

Use migrations with upgrade/rollback tests, backups with restore tests, and retention enforcement across original images, crops, overlays, exports and object-store versions. A thumbnail of private writing is still private writing.
