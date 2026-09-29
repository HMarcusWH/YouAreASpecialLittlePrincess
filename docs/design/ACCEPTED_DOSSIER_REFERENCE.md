# Accepted Inktrospect Dossier design reference

**T10 owner decision:** `ACCEPTED_WITH_CHANGES`  
**Decided by:** product/design owner  
**Decided on:** 2026-09-29

## Bound prototype artifact

- Artifact: `Inktrospect mobile app design (2).zip`
- SHA-256: `89b43380609dec56bdb82c284f0f6beb4c097692273ef13a3b23deb143ff7db5`
- Prototype-internal repository sync: `2026-09-28T19:26:00Z`
- Final acceptance reconciliation baseline: `53bcb9743eeb7fa96fc9affb68fc949c30fd25c0`
- Public product brand: **Inktrospect**
- Selected direction: **Direction A — The Dossier**

The prototype archive itself is not committed. This record binds the accepted design decision to an exact artifact digest. Repository contracts, fixtures and this document are authoritative where the older prototype annotations disagree with the current codebase.

## What is accepted

The owner accepts the Dossier visual/product system as the implementation reference for T17, T21 and T29–T31:

- light-first editorial paper surfaces with a night-paper dark mode;
- warm paper / dark ink / red-pencil accent hierarchy;
- Newsreader-style editorial text and IBM Plex Mono-style numeric/caption typography as design intent;
- evidence/state roles that remain labelled and icon-supported rather than colour-only;
- dossier-style First Reveal, report, evidence, history, comparison, share/export and settings compositions;
- responsive web plus iPhone/iPad/Android phone/tablet design simulations;
- reduced motion, 200% text review, English/Swedish overflow review and 44 px touch-target intent;
- square/story colour-plane share direction and A4/Letter editorial print direction.

The canonical accepted semantic tokens are `packages/design-tokens/tokens.json` `design-tokens/1.0`. Generated CSS/TypeScript/Swift/Kotlin values come only from that source.

## Accepted changes and limitations

1. **Repository contract truth supersedes stale prototype annotations.** The accepted archive predates the merged T18/T10 reconciliation. Its README still names `prototype_illustrative_selection` and describes Compare as planned T18/T22. Current repository truth is: legacy `individual-report/1` has no highlight; `individual-report/2` carries the server-owned T08A highlight/no-eligible result; T18 deterministic pair/history/no-overlap mechanics are implemented; T22 still owns invitation and other-owner authorization/release.
2. **Print/share acceptance is directional, not final render evidence.** The archive shows scaled A4/Letter and square/story previews. T21 still owns full-size/multi-page render inspection, clipping, reading order, accessibility and export parity.
3. **Evidence touch interaction may evolve.** The archive uses step controls rather than the proposed press-and-hold loupe. T17/T29 may implement the accepted evidence-inspection intent with a platform-appropriate accessible interaction; no client may invent evidence or measurement semantics.
4. **Desktop editorial width is accepted.** A narrow editorial report column on wide web is not a defect by itself; T17 may use extra width for navigation/evidence context without changing content authority.
5. **Font delivery is not approved by the prototype import mechanism.** The prototype uses Google Fonts as substitutes. Acceptance names the typography direction, not remote font hosting, licensing or packaging. T17/T29 must choose a reviewed delivery/fallback strategy.
6. **Synthetic specimen lettering is illustrative only.** Cedarville Cursive in the prototype is not user handwriting and must not replace an authorized source image in production.
7. **Identity remains a separate implementation decision.** Prototype sign-in is a placeholder; ADR-002/provider work remains T17/T24 scope.
8. **Commercial/provider/system sheets remain schematic.** T19/T20/T24/T30/T31 own real provider behavior, policy and platform UI integration.

## Repository qualification

The accepted-token/documentation implementation was qualified at `4a786230fcb9d70c1c8f75bba8b02c73ec2aad25` with CI `36506833905`, Roadmap integrity `36506833900` and Application environments `36506833890` all passing. The browser qualification includes dark-mode consumption of the canonical token source rather than a hard-coded pre-Dossier color.

## Downstream ownership

- **T17:** production web Dossier integration, `individual-report/2` activation, production identity/cross-device recovery.
- **T21:** accepted Dossier print/share styling and actual full-size rendered-page/card inspection; add T18/T20 parity only from owning-task content.
- **T22:** sharing/invitations and other-owner comparison authorization/release.
- **T29:** native scaffold/platform seams consuming the accepted semantic tokens, not web DOM.
- **T30/T31:** complete native journeys and platform-specific interaction/billing.
- **T06/T08/T12–T14:** calibration/reference work required before population-relative claims.

This acceptance closes only the T10 `design_acceptance` gate. It does not approve participant rights, processor terms, live model use, prices, charges, native signing, store review or public release.
