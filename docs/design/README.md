# Design handoff — Inktrospect contract-driven report experience (T10)

Status: **DRAFT, pending the `design_acceptance` owner gate.** The working public brand is **Inktrospect** and the selected Claude Design direction is **A — The Dossier**; repository/package namespaces such as `Princess`/`princess_*` remain internal for now. This file and `packages/design-tokens/` give T17 (web), T21 (PDF/cards) and T29–T31 (native) stable names to build against. Every value, layout and label here remains unaccepted until owner review. None of it is a shipping promise about a statistic or feature.

Sources: [report design](../roadmap/04-reports-design.md), [web client](../roadmap/10-web-client-and-api-integration.md), [mobile](../roadmap/11-mobile-architecture.md), [commerce](../roadmap/14-payments-entitlements-and-commerce.md) and the generated contracts in `contracts/product/v1/`.

Claude Design review package: [handoff brief](CLAUDE_DESIGN_HANDOFF.md) · [owner acceptance record](CLAUDE_DESIGN_ACCEPTANCE.md) · [`claude-design-import.json`](claude-design-import.json) · [`claude-design-state-matrix.json`](claude-design-state-matrix.json). The handoff prepares the design session only; it does not satisfy `design_acceptance` by itself.

## 1. Rules that shape every screen

1. **Everything is designed from the contract.** Screens render a `ReportViewModel` (facts, sections, notices, actions, authorized assets) or an API status DTO. A layout must never need a field the contract does not have.
2. **Availability is not a boolean.** Each fact and section carries one of `READY`, `UNCALIBRATED`, `MISSING`, `NOT_IMPLEMENTED`, `INELIGIBLE`, `LOCKED`, `PENDING`, `FAILED` or `REVOKED` (§4). A missing value is never drawn as zero.
3. **Evidence classes stay visibly distinct.** `MEASURED`, `COMPUTATIONAL_PROXY`, `REFERENCE_STATISTIC`, `AUTHORED_CONTENT`, `TRADITIONAL_ASSOCIATION` and `AI_SYNTHESIS` each get a colour role, an icon and a text label. Colour is never the only signal.
4. **No fake Premium.** Locked content is a truthful product description. There is no blurred, personalized-looking placeholder text, no invented percentile or rarity badge, and no social proof.
5. **Free stands on its own.** Every measured Free fact is shown. Premium adds synthesis; it does not unlock hidden measurements.
6. **Private by default.** Designs use only the synthetic fixtures in `fixtures/reports/`. Real handwriting or participant data never goes to a design provider.

## 2. Screens and journeys

Each screen lists the states the design must cover, beyond the happy path.

| Screen | Driven by | Required states |
|---|---|---|
| Landing | static | signed out, returning account, guest with an unfinished analysis |
| Permission and upload | `POST /v1/me/permissions`, `POST /v1/uploads` | consent choices unselected; service processing required; image retention and AI processing offered separately; challenge required after the free quota; quota exceeded (`upload_quota_exceeded`, retry-after) |
| Crop, orientation, preview | client only, then `…/complete` | EXIF rotation applied; unsupported format (HEIC before conversion, GIF, WebP); too large or too small; pixel bomb rejected; completion in progress; bytes changed (`upload_completed_with_different_bytes`) |
| Processing | `GET /v1/analyses/{run_id}` | `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED` (with safe error code), `CANCELLED`, `owner_transferred`; resume after refresh without resubmitting |
| First reveal / What stands out | T08A `individual-report/2` server-owned highlight sections (`fact_ids` + reviewed `content_ids`) | backend selection available; no eligible highlight; source image retained/not retained; final Dossier client integration is T17; never select on the client |
| Free report | `ReportViewModel` projection `FREE`/`OWNER` | complete; partial (some families `MISSING`); uncalibrated proxies; no eligible benchmark (`notice.reference_unavailable`); image revoked (`view.owner-image-revoked.json`); original not retained |
| Premium offer and consent | `GET /v1/catalog`, `GET /v1/me/credits` | offer with processing recipient and success/failure terms; no credit; credit from another platform (not spendable by default); sales disabled (`commerce_disabled`) |
| Purchase | web checkout or native store | pending payment; Ask to Buy / pending store purchase; cancelled; failed; restored; claim `account_mismatch` |
| Premium generation | `POST /v1/reports/{id}/premium`, `GET /v1/premium-jobs/{id}` | queued; running; succeeded (revision with an overlay); refused; failed with the credit released; not applicable (no authorized image) |
| Premium report | projection `PREMIUM`/`OWNER` with overlay | AI-labelled synthesis next to the unchanged Free facts; omitted questions explained; refund after spend (decision pending the owner) |
| Pair invitation and comparison | T18/T22 (planned) | invitation sent, accepted and declined; insufficient common coverage; revoked |
| History | T17 | empty; several revisions; a deleted capture |
| Share preview and revocation | projection `SHARE` (`view.share.json`) | exact disclosed fields preview; sharing disabled; link revoked |
| Export preview | projection `EXPORT` (`view.export-no-image.json`) | A4 and Letter; "source image omitted"; rendering; failed |
| Settings | `/v1/me/*` | permissions per purpose with withdraw; logout everywhere; delete account (requested, then completed) |

## 3. Component inventory mapped to contract properties

| Component | Reads | Notes |
|---|---|---|
| `FactValue` | `Fact.value`, `unit`, `precision`, `formatting_key`, `availability` via `@princess/report-core` `formatFact` | Tabular numerals (`font-family-numeric`). An `UNAVAILABLE` state renders the availability reason, never "0". |
| `EvidenceBadge` | `Fact.evidence_class`, `Notice.class` | Colour role `evidence-*` plus icon plus label; tooltip links to the method (`method_id`, `method_version`). |
| `QualityHint` | `Fact.quality` (`state`, `n_observations`, `confidence_kind`, `missing_reason`) | `confidence_kind: UNCALIBRATED` is always shown as "not calibrated", never as a percentage. |
| `ReportSection` | `ReportSection.template`, `availability`, `fact_ids` | `individual-report/1` remains the current client default; `individual-report/2` adds T08A highlight sections and is activated by T17 when clients render reviewed content IDs. A `LOCKED` section shows the product description only. |
| `HighlightReveal` | a server-selected highlight `ReportSection` using `template`, `fact_ids` and `content_ids` | Design primitive for “What stands out”. T08A now supplies the server-selected content/support IDs; T17 clients must render them but must never choose the salient fact themselves. |
| `NoticeBar` | `ReportViewModel.notices[]` | Covers measured, proxy, reference (unavailable), traditional (not included), AI and privacy notices. |
| `ActionBar` | `ReportViewModel.actions[]` (`kind`, `enabled`, `reason`) | A disabled action shows its reason key (for example `commerce_disabled`, `sharing_disabled`, `comparison_not_available`). |
| `HandwritingCanvas` | `authorized_asset_ids`, `EvidenceBundle` regions and frames | Draws overlays only in the evidence coordinate frames. Absent when the image is not authorized. |
| `DistributionChart`, `BaselineTrace`, `SpacingChart` | `EvidenceBundle.observations` | Actual observations only (never a curve reconstructed from mean and SD). Each has a text alternative table. |
| `JobStatus` | analysis/Premium job status DTOs | Polls with backoff; keyboard- and screen-reader-announced state changes. |
| `CreditBalance` | `GET /v1/me/credits?platform=` | Shows available and reserved per platform; never computed on the client. |
| `ConsentChoice` | T03 purposes/notices | One decision per purpose; sends `request_id` so retries are idempotent. |

## 4. State encoding

| Availability | Visual | Text (key) | Behaviour |
|---|---|---|---|
| `READY` | value + evidence badge | — | normal |
| `UNCALIBRATED` | value + "not calibrated" hint (`state-attention`) | `availability.UNCALIBRATED` | no rank or claim that needs calibration |
| `MISSING` | hatched "no data" mark | `availability.MISSING` + missing reason | explain the input needed; never plot |
| `NOT_IMPLEMENTED` | omitted | — | do not advertise |
| `INELIGIBLE` | neutral note | `availability.INELIGIBLE` | show descriptive alternatives, no unrelated benchmark |
| `LOCKED` | lock icon (`state-locked`) | product description | no personalized placeholder |
| `PENDING` | progress (`state-info`) | job state | cancel or recover |
| `FAILED` | alert (`state-danger`) | safe error code | retry or refund path; Free stays intact |
| `REVOKED` | removed + notice | `availability.REVOKED` | stop rendering the content and its derivatives |

## 5. Platform differences

- **Web** (T17, Next.js): DOM semantics and a print stylesheet (T21, via `tokens.css` `print` values). Colour mode uses `prefers-color-scheme`, and `data-theme` can override it. Focus rings use `--color-focus`. The layout is responsive at the `breakpoint` tokens.
- **Native** (T29–T31): the same semantic data with native accessibility (VoiceOver/TalkBack, Dynamic Type/font scale) and native navigation. `PrincessTokens.swift` and `.kt` carry the same values. Store purchase flows (pending, Ask to Buy, restore, finish after the server grant) follow the platform's own UI; wallet buttons are not digital billing.
- **Print and cards** (T21): the same saved projection. Details are expanded, animation is off, fonts are embedded, and the report ID, revision, date, methodology and limitations are included.

## 6. Accessibility

Targets WCAG 2.2 AA.

- Every declared colour pair is checked by `tests/test_design_tokens.py`: text at 4.5:1 or more, UI boundaries and focus at 3:1 or more, in both themes.
- Touch targets are at least `target-min-touch` (44 px).
- All motion goes to 0 ms under reduced motion, and reveals are instant rather than skipped.
- Every chart has a text alternative, keyboard-reachable details and a legend that doesn't rely on colour.
- Status changes (processing, generation) are announced politely.

## 7. Localization and overflow

English and Swedish ship first. Designs must hold long Swedish compounds (for example "Bokstavsavståndsvariation" or "Tredjepartsbehandling av bilden") without clipping or invented abbreviations. They must also survive 200% text scaling at 320 px width. Fact IDs and units are never localized; only display strings are. Number formatting follows the locale (`Intl.NumberFormat`: decimal comma in Swedish, minus sign, no negative zero).

## 8. Prohibited patterns

- Blurred or teaser text that looks personalized for locked Premium.
- Percentiles, ranks, "rare", "top X%" or cohort labels without an eligible benchmark claim.
- Radar charts that rescale each person to their own maximum, or plot missing axes as zero.
- Diagnostic, intelligence, honesty, employability or compatibility language anywhere.
- Required public sharing, contact-book access or social proof to unlock purchased content.

## 9. Handoff checklist for a design tool

Provide: this file, `contracts/product/v1/schemas/`, `fixtures/reports/` (synthetic), `packages/design-tokens/tokens.json`, the evidence-class and availability tables above, and `docs/roadmap/04-reports-design.md`. Mark every illustrative number in mockups. Generated code from a design tool is reviewed like any other change: dependencies, licences, state handling and security.

## 9.1 Inktrospect design-session contract findings

The selected **A — The Dossier** exploration exposed several useful contract boundaries. They are recorded here so the prototype can stay ambitious without silently inventing backend truth.

- **First reveal / salience:** there is not yet a production field that selects “What stands out”. **T08A now owns and implements the deterministic/versioned highlight policy and reviewed localized content; report assembly carries it through the existing `ReportSection` structure** (`template`, supporting `fact_ids`, reviewed `content_ids`). Claude Design may now use the T08A content/support contract as real backend behavior; web/native rendering remains T17 work and clients must not rank facts themselves.
- **Comparison:** `contracts/product/v1/schemas/comparison.schema.json` already exists. It is a deliberately skeletal T01 wire contract, not the completed T18 product. T18 extends/implements directional facts, common-feature coverage, per-input provenance, fixed family scales and invariant Me-vs-Me/pair semantics. Do not create a parallel Comparison DTO to satisfy a mockup.
- **Feature labels:** the canonical feature database already contains English canonical names. T08A publishes reviewed EN/SV presentation/localization content in `contracts/product/v1/presentation-content.v1.json`; current web fallback replacement remains T17 work. Canonical English names are not a complete Swedish/UI copy catalogue.
- **Fixed visual scales:** a slant fan may use the inherent geometric `-90°…+90°` canvas, while the current slant extractor only accepts observations within `-60°…+60°`; the design must make that distinction clear. Proposed arbitrary ranges such as a `0–20× x-height` margin bar have no current authority: T08A may approve only intrinsic/predeclared non-population domains, while empirical/population-relative mappings remain T06/T08 work.
- **Dates:** database/report `created_at` values describe system events (ingestion/analysis/report creation), not necessarily when handwriting was written or an imported photo was originally taken. History/Me-vs-Me must preserve those meanings and add separately labelled provenance if a true writing/photo date is introduced; never relabel ingestion time as capture time.
- **Disabled-action copy:** committed report fixtures use `premium_not_yet_available` and `already_unlocked`; these must always resolve to reviewed localized user copy rather than leaking raw reason keys.

## 10. Acceptance (owner gate `design_acceptance`)

The owner accepts clickable responsive and native designs covering §2, with the accessibility states in §6 and the overflow cases in §7. Until then the token status stays `DRAFT_PENDING_DESIGN_ACCEPTANCE`, and this task cannot be marked `DONE`.
