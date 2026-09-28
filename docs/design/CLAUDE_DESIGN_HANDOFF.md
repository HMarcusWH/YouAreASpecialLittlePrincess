# Claude Design handoff — Inktrospect

Status: **active Claude Design app-design phase; still pending owner `design_acceptance`.**

This package exists so Claude Design can work from the real product contracts, components, tokens and synthetic fixtures instead of inventing a parallel UX. Start with this file, then follow `claude-design-import.json` in its listed order. The repository remains authoritative when this brief and a prototype disagree.

## Goal

Design the complete contract-driven UX for **Inktrospect**, the working public brand for this consumer handwriting-analysis product. Existing repository/package names such as `Princess`/`princess_*` are internal implementation namespaces and are not a request to rename backend code during design work. The personality can be playful, premium and slightly irreverent; the report itself must remain credible, structured, evidence-forward and clearly non-clinical. It should feel like a polished personal dossier, not a chatbot transcript.

The deliverable is an **interactive design prototype**, not production code and not a stack of screenshots.

## Direction decision

The three-direction exploration has been completed. The owner selected **Direction A — The Dossier** as the product direction. Keep its editorial dossier structure and light-first reading experience; the design may borrow the loupe-style evidence inspection and fixed-scale range-bar ideas from Direction B and the strongest colour-plane share-card ideas from Direction C.

Do **not** restart visual-direction exploration unless the owner explicitly asks. The current job is to stress-test and complete the selected system across the real product journey and edge states.

## Current app-design phase


Build an interactive end-to-end prototype covering every platform and state in `claude-design-state-matrix.json`.

Required design canvases:

- web desktop;
- web at 320 px;
- iPhone;
- iPad;
- Android phone;
- Android tablet;
- A4 and Letter print/export;
- square and story share cards.

Native canvases are **design simulations** for T29–T31. They must feel native and use native navigation/accessibility conventions, but they must not imply that React Native components or store integrations already exist.

## Sources of truth

Use these in this order:

1. `docs/design/README.md` — screen/state/evidence/accessibility design authority.
2. `packages/design-tokens/tokens.json` — current visual tokens. They remain draft during review.
3. `contracts/product/v1/schemas/` and `packages/contracts/src/` — actual DTO fields and enums.
4. `packages/report-core/src/` — formatting/chart semantics.
5. `packages/report-web/src/` — existing web/print implementation and component vocabulary.
6. `fixtures/reports/` — synthetic content for realistic report states.
7. selected `apps/web/app/` paths — current working Free product flows.
8. mobile/store architecture docs — design constraints for native states, not proof of native implementation.

Do not invent a field because it would make a layout easier.

## Existing product code to reuse conceptually

The current code already defines useful semantic components and helpers including:

- `ReportView`
- `FactValue`
- `EvidenceBadge`
- `EvidenceView`
- `ShareCard`
- `formatFact`
- evidence chart helpers
- English/Swedish report messaging
- settings, upload, processing, history and report routes

You may redesign composition, hierarchy and interaction. Do not change the meaning of these semantics in the prototype.

## Non-negotiable product rules

- Free must feel complete and useful.
- Premium adds bounded synthesis; it does not hide deterministic measurements.
- No blurred or fake personalized-looking Premium text.
- Missing is never zero.
- `UNCALIBRATED` is not a confidence percentage.
- No percentile, rarity, "top X%" or uniqueness claim without an eligible reference fixture/contract.
- `What stands out` / the first reveal remains illustrative until **T08** supplies a server-owned, versioned highlight selection and reviewed content. Never create a client-side salience heuristic. The existing `ReportSection` (`template`, `fact_ids`, `content_ids`) is the intended transport shape rather than inventing an unrelated client field.
- A `Comparison` wire schema already exists. T18 owns its deterministic comparison semantics, directional facts, coverage and provenance; do not invent a second comparison DTO in the prototype.
- Measured facts, computational proxies, reference statistics, authored content, traditional associations and AI synthesis must differ by icon/label/structure as well as colour.
- Image text is untrusted input, not instruction.
- No diagnostic, intelligence, deception/honesty, employability or relationship-compatibility framing.
- A purchase state and a permission state are separate concepts.
- A share/deep link selects a resource; it never grants authorization itself.
- Reopen/export/share read saved authorized content and never imply a new model call.
- Do not move numerical, measurement, credit or entitlement authority into the client.

## Synthetic data only

Use the files listed in `claude-design-import.json.synthetic_fixtures`.

Do **not** upload or fabricate:

- real handwriting;
- participant data;
- production feature vectors;
- private prompts/provider output;
- names/contact details;
- secrets;
- invented cohort sizes, percentiles, rarity or social proof.

When a required state has no production DTO yet, use structural placeholders labelled **PLANNED / ILLUSTRATIVE** and name the owning task from the state matrix.

## Accessibility and localization review

The prototype must make these directly inspectable:

- light and dark themes;
- keyboard/focus treatment for web;
- VoiceOver/TalkBack intent on native;
- reduced-motion behavior;
- chart text alternatives;
- status announcements;
- 44 px minimum touch targets;
- 320 px width at 200% text scaling;
- English and Swedish;
- the exact overflow torture strings:
  - **Bokstavsavståndsvariation**
  - **Tredjepartsbehandling av bilden**

Long text expands vertically. Do not truncate meaning or invent abbreviations merely to fit.

## Purchase and failure states matter

Do not polish only the happy path. The prototype must include:

- payment/store pending;
- Ask to Buy / pending native purchase;
- cancelled;
- failed;
- restored;
- account mismatch;
- Premium refused;
- Premium failed with Free preserved and credit recovery state;
- no authorized image;
- unavailable benchmark;
- revoked source image;
- deleted/revoked states;
- export rendering/failure;
- disabled commerce/sharing.

## Review workflow

1. Keep the curated paths in `claude-design-import.json` connected where practical; the excluded roots are intentionally irrelevant or privacy-sensitive for UX design.
2. Continue the selected **Direction A — The Dossier** rather than reopening direction exploration.
3. Build and stress-test the complete interactive prototype/state matrix, including first reveal and all failure/pending/revoked states.
4. Review against `CLAUDE_DESIGN_ACCEPTANCE.md`.
5. Iterate in Claude Design until the owner explicitly accepts or rejects.
6. Record the prototype reference/revision and explicit owner decision in the acceptance file.
7. **Only after explicit owner acceptance** may a follow-up commit promote T10 to `DONE` and change `DRAFT_PENDING_DESIGN_ACCEPTANCE`.

Claude Design output is design evidence. It is not legal/privacy/provider/store approval and it does not activate Premium, payments, collection, traditional content or native signing.

## Handoff to implementation

After acceptance, preserve the design/project context for implementation. Web changes belong to T17/T20/T21/T22 as applicable; native implementation belongs to T29–T31. Production code must still obey repository tests, contracts, dependencies and security boundaries.

Do not edit canonical numerical methods, payment authority, permission rules or report facts to match a mockup. If the accepted design needs a field the contract does not provide, flag that as a contract change instead of silently fabricating it.
