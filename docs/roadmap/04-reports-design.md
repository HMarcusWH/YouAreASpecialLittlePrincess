# 04 — Reports, comparison UX, and Claude Design

Status: product/renderer contract and design brief, not a completed interface. References resolve in [07](07-evidence-register.md).

## 1. One content model, three presentations

```text
AnalysisRun + reference snapshot + approved content/rules
                         -> ReportDocument
                  + validated Premium overlay
                         -> authorized projection
                  /              |              \
          interactive UX      social card       PDF snapshot
```

`ReportDocument` is the versioned content/fact record. `ReportViewModel` is an authorization-filtered presentation model derived from it. The frontend is not the numerical source of truth; 'the report is the UX' means the full experience is available in-app, not that UI component state owns the scientific data.

Use report kinds `INDIVIDUAL`, `PAIR`, and `HISTORY`; use content entitlements separately. A comparison can be entirely deterministic and Free, with an additional explicitly purchased pair narrative. Do not require two full individual Premium purchases merely to display a deterministic difference.

UI, PDF and cards must reference the same facts, directions, units, labels, limitations and report revision. Shared render components can differ in layout and interactivity. They must not have independent scoring or inference code. Re-exporting uses the saved content and never calls OpenAI.

## 2. ReportDocument contract

Required groups:

- Identity: report/revision IDs, kind, creation time, requested locale, opaque sample/input references and versions.
- Availability: section states and reasons, included feature count, excluded/missing metrics, supported input context.
- Facts: immutable typed facts with canonical IDs, raw values, units, display formatting key, evidence class, method version, source-region links and quality metadata.
- Reference: nullable cohort/release, feature-specific writer N, eligible coverage, rank/uncertainty claim objects and methodology links.
- Sections: stable section IDs, template types, referenced fact IDs, authored content IDs, approved Premium section references and disclosure class.
- Visual evidence: bounded distribution arrays, baseline polylines, spacing brackets, region outlines, coordinate frame/transforms and allowed private asset references.
- Actions: permitted compare, export, share, save/delete and purchase operations derived from server entitlements.
- Notices: measured/proxy/traditional/AI labels, sampling limitations, unavailable confidence and applicable sharing/retention notices.

All actual numbers come from facts. A display string is a localized rendering of its stored value and precision policy. Keep uncertainty and evidence labels attached when content travels to a card or PDF.

The schema task generates TypeScript/Python contract types and fixtures from a single reviewed JSON schema. It does not replace the canonical feature database. Stable render contracts allow Claude Design and backend work to proceed independently.

## 3. Availability is not a Boolean

Keep these concepts separate:

| State | Meaning | UI behavior |
|---|---|---|
| READY | Supported content exists and is authorized | Render the evidence and content. |
| MISSING | Required observations could not be measured | Explain what input is needed; never plot zero. |
| NOT_IMPLEMENTED | Definition exists but extractor is absent | Do not advertise a computed result; omit or clearly identify planned capability. |
| INELIGIBLE | Sample/cohort does not support this claim | Show descriptive alternatives, not an unrelated benchmark. |
| UNCALIBRATED | A method/index lacks empirical calibration | Label appropriately; withhold claims requiring calibration. |
| LOCKED | Additional content can be purchased but has not been generated/unlocked | Show a truthful product description, not fake blurred personalized text. |
| PENDING | Authorized generation/export is underway | Show actual job state, cancellation/recovery behavior. |
| FAILED | Generation/export failed | Preserve Free content; offer the documented retry/refund path. |
| REVOKED | Access or supporting disclosure has been withdrawn | Stop serving the restricted content and derivatives. |

Measurement validity, calibration status, purchase entitlement and asynchronous job state are separate fields internally; the table describes their UX consequences, not an overloaded database enum.

The unlocked client payload must not contain hidden Premium text. Authorization runs before projection, export and asset issuance, not only in a React conditional.

## 4. Individual Free report

Recommended order:

1. **Hero:** a meaningful geometric standout or authored style label, sample suitability and one share action. No uncalibrated claim that the person is statistically unique.
2. **At a glance:** supported mechanical axes, key metrics and honest availability. Use a concise summary rather than a wall of raw values.
3. **Handwriting anatomy:** the user's permitted image with toggles for baseline, slant, spacing and page layout. Tapping a region shows the corresponding metric, unit and method limitation.
4. **Dimensions:** expandable feature-family cards. Show data first, then deterministic explanatory captions.
5. **Reference comparison:** only when eligible. Name the cohort, N and benchmark version. Empty state explains why no rank is available yet.
6. **Optional style reading:** authored playful geometric labels and separately labelled traditional rule hits where reviewed. No implied psychometric validity.
7. **Compare, share, save, export:** useful actions on the current result, followed by a specific Premium explanation of additional content.

The Free experience should stand on its own. Do not deliberately degrade deterministic accuracy or withhold a basic measured feature just to force an API purchase.

## 5. Premium report

Premium extends the same report with a short executive synthesis, a small set of evidence-linked cross-feature explanations, nuanced descriptions of supported contrasts, and approved traditional associations where applicable. It may provide reflective questions, not diagnoses or advice for consequential decisions.

Keep prose bounded and glanceable. Aim for one main statement and one main visual per section, with supporting details expandable. Exact length is a design constraint tested in mobile layouts, not a requirement to fill a fixed number of pages.

The UX distinguishes 'AI-assisted explanation' from a measured result. A user buying Premium sees the specific extra capability, processing recipient and success/failure terms before authorizing generation. The existing Free report remains accessible during processing and on failure.

Premium cannot manufacture a percentile to complete a layout, add an archetype not assigned by the versioned rule system, or invent a tension unsupported by multiple relevant facts. Reopening uses the saved overlay, not a newly generated personality reading.

## 6. Pair and historical reports

Pair report: two authorized sample labels; common-feature/quality coverage; side-by-side handwriting evidence only when both grants permit it; most alike and largest difference by fixed normalized definitions; family comparison bars; a qualified similarity index only if its mapping and evaluation exist; optional paid pair synthesis; share/export preview with both parties' disclosure settings.

Preserve direction and units. 'A has wider spacing than B' is not 'A is more independent than B.' Similarity is not compatibility, common authorship or relationship success. Do not award a winner for mental health, intelligence or personality.

Me-v-Me: explain collection dates versus upload dates; show the same writing task/method when possible; separate capture, instrument and pipeline differences from observed changes. Avoid relative percentage change when the old denominator is zero or near zero. Display an absolute difference or no interpretable trend instead.

Friend comparison should invite the other person to upload/authorize their own writing. A shared report does not implicitly authorize reuse in another comparison, corpus contribution, or model call. Revocation invalidates private shared projections and regenerated exports on our systems.

## 7. Chart and annotation contracts

- **Radar:** fixed, versioned axes and fixed scale mapping, normally no more than six to eight readable dimensions. Missing axes do not become zero; use an explicit incomplete state or bars instead of a misleading polygon. Do not rescale each person to their own maximum.
- **Distribution:** actual observations or bins with count/weight definitions and scope. Do not generate a Gaussian-looking histogram from a mean/std pair. A population plot uses reference aggregates, not exposed private member vectors.
- **Baseline trace:** stored points with frame/units, not an illustrative curve unrelated to the input. Coordinate conversion must survive crop, perspective correction, resizing and deskew.
- **Spacing:** actual accepted gaps and linked line/word regions. Avoid treating overlapping boxes or uncertain segmentation as zero spacing.
- **Reference bar:** percentile of a named eligible metric plus cohort N/version and uncertainty context; a raw 0–100 engineering score must never masquerade as a percentile.
- **Pair bars:** identical scale/reference for both users, missingness visible, selection rule stable under swapping inputs.

Every chart has a text alternative, keyboard-accessible details, a concise method link and a non-color-only legend. Target WCAG 2.2 AA; also respect reduced-motion preferences and provide a non-animated reveal. [S17]

## 8. Share cards and viral loop

Adopt the supplied research's share-card/invite/comparison direction as a product hypothesis, not proof of guaranteed virality. Its useful core is results-first, then Share/Compare/Save. [P01, P02]

Create a small reusable card family: geometric style/standout, mechanics summary, eligible cohort comparison, pair difference, and Me-v-Me change. Formats: square and portrait story, with readable text, brand, context label and a generic invitation or explicit share-grant link.

Default cards exclude names, original writing, private transcriptions, signatures and a partner's identity. Users preview exact disclosed content. Share grants are scoped, unguessable, expiring/revocable, and not indexed. QR codes must not encode raw feature vectors or a private report URL. A public card is a deliberately redacted artifact, not the entire report hidden by CSS.

Do not fabricate social proof, display a rare badge without support, require public sharing to unlock already purchased content, or load a contacts address book by default. Badges should celebrate actual actions or measured descriptors, not pretend everyone is in the top percentile.

Instrument share dialog opened, export completed, link copied, invite accepted and referred analysis completed separately. A browser/native share success callback is not proof that a post was published or that someone saw it. The measurable acquisition loop is a shared/invited link leading to a new completed analysis; track it without collecting private writing in analytics.

## 9. PDF and image export

Export the same authorized report revision. Use shared web report components in a dedicated print mode and a Node/Playwright renderer. `page.pdf()` uses print CSS and supports options such as tagged output; those options are useful but do not by themselves establish accessibility compliance. [S18]

Print mode expands the appropriate details, disables animation, waits for fonts/assets, fixes chart dimensions, provides sensible page breaks and uses vector SVG charts/selectable text where possible. Support A4 and Letter, with a report ID/revision, generation date, methodology and limitations. Keep the reading order, title hierarchy, alternative descriptions and contrast usable. Inspect rendered pages for clipped charts, empty pages, overlapped footers and tiny captions.

No chain of phone screenshots as the full PDF. No model-written PDF-only paragraph. Optional exclusion of handwriting images is visible in the export preview and reflected by a 'source image omitted' note. PDF content matches the user's entitlements, so Free exports contain Free content and Premium exports include the saved Premium overlay.

Cache bytes by report revision + authorized field projection + template/font version + locale + format. Revocation blocks future access/issuance. Explain that a previously downloaded PDF cannot be recalled.

Acceptance tests compare fact values and labels across the UI view model, PDF-extracted text and share-card payload. Snapshot/visual tests cover multiple page sizes, long Swedish labels, negative values, missing metrics, large numbers and withdrawn images. Exporting must succeed with all model/network credentials absent, aside from authorized internal asset retrieval.

## 10. Claude Design handoff

Anthropic's official product material describes codebase/design-file inputs, interactive prototypes and a handoff to Claude Code. Use that workflow for the **report experience**, not a stack of PDF pages. [S16]

Provide Claude Design this document, generated report schemas/types, a real engine-result fixture plus clearly synthetic product-state fixtures, component boundaries, image-coordinate rules, approved typography/assets, capability map, and privacy/evidence labels. Do not upload real participant samples to a design provider without appropriate permission.

Required screens/states: landing; permission/upload; crop/orientation; unsuitable sample and retry; processing; partial Free report; complete Free report; no eligible benchmark; Premium offer/consent; payment pending/failure; generation pending/refused/failed/success; pair invitation and consent; pair coverage failure; history; share preview/revocation; PDF export; settings/deletion.

Deliverables: responsive clickable prototype, design tokens, reusable component inventory, interaction/motion specifications, accessible keyboard/text states, mobile and desktop layouts, export layouts, and a Claude Code handoff mapped to real contract properties. Code agents must still review generated code, dependency/license choices, state handling and security.

The direction is a polished personal dossier with analytical visuals and playful personality—not an unstructured chatbot transcript and not a clinical assessment. A mockup must identify illustrative numbers; it cannot turn unavailable statistics into shipping promises.
