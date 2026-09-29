# T10 owner design-acceptance record

**Status: ACCEPTED_WITH_CHANGES**

The product/design owner explicitly accepted Direction A — The Dossier on 2026-09-29. This closes only the T10 `design_acceptance` gate. Recorded limitations and downstream implementation ownership are authoritative in [ACCEPTED_DOSSIER_REFERENCE.md](ACCEPTED_DOSSIER_REFERENCE.md).

## Prototype identity

- Claude Design project/prototype reference: `Inktrospect mobile app design (2).zip`
- Prototype artifact SHA-256: `89b43380609dec56bdb82c284f0f6beb4c097692273ef13a3b23deb143ff7db5`
- Prototype-internal repository sync: `2026-09-28T19:26:00Z`
- Working public brand: **Inktrospect** (repository/package namespaces remain unchanged)
- Design direction selected: **A — The Dossier**
- Repository baseline used for final acceptance reconciliation: `53bcb9743eeb7fa96fc9affb68fc949c30fd25c0`
- Prototype revision reviewed: artifact digest above; accepted with repository-contract corrections

## Owner review checklist

### Complete journey

- [x] Landing: signed out / returning / unfinished guest
- [x] Permission and upload, including separate optional permissions
- [x] Crop/orientation/error states
- [x] Processing lifecycle and refresh recovery
- [x] First reveal / “What stands out”, including no-eligible-highlight and image-not-retained states
- [x] Complete and partial Free report
- [x] No-reference / uncalibrated / image-revoked report states
- [x] Premium offer and explicit AI-image-processing permission
- [x] Purchase pending / Ask to Buy / cancelled / failed / restored / account mismatch
- [x] Premium generation queued / running / success / refusal / failure / not-applicable
- [x] Premium report keeps Free facts unchanged and labels AI synthesis
- [x] T18 pair/history/no-overlap comparison mechanics use the real repository fixtures; T22 invitation and other-owner authorization/release remain clearly planned
- [x] History empty / revisions / deleted capture
- [x] Share preview / disabled / revoked
- [x] A4 / Letter export direction, image omission and failure
- [x] Settings / notification preference / logout / deletion

### Platform review

- [x] Web desktop
- [x] Web at 320 px
- [x] iPhone
- [x] iPad
- [x] Android phone
- [x] Android tablet
- [x] A4 / Letter print direction; full-size/multi-page render qualification remains T21
- [x] Square / story share-card direction; full-size render qualification remains T21

### Accessibility and localization

- [x] Light and dark themes
- [x] Reduced motion
- [x] Web keyboard/focus intent
- [x] Native screen-reader intent
- [x] Charts have text alternatives
- [x] Status changes are announced in the design intent
- [x] 44 px minimum touch targets
- [x] 320 px at 200% text scaling review
- [x] Swedish and English layouts
- [x] “Bokstavsavståndsvariation” overflow review
- [x] “Tredjepartsbehandling av bilden” overflow review

### Evidence and product truth

- [x] Missing is never shown as zero
- [x] Uncalibrated is not presented as statistical confidence
- [x] Evidence classes differ by more than colour
- [x] No fabricated percentile, rarity or uniqueness
- [x] No fake personalized blurred Premium content
- [x] No diagnostic/intelligence/honesty/employability/compatibility language
- [x] Free remains useful and available during paid failures
- [x] Native design does not imply client measurement/credit authority
- [x] Planned features are labelled planned/illustrative rather than implemented, subject to repository-contract corrections

## Repository-contract corrections accepted with the design

- T08A/`individual-report/2` server-owned First Reveal is real product truth; the accepted archive's older `prototype_illustrative_selection` label is not authoritative.
- T18 deterministic pair/history/no-overlap mechanics are real product truth; the accepted archive's “Compare planned T18/T22” annotation is stale. Only T22 invitation/other-owner release remains planned.
- The archive's scaled print/share previews establish design direction; T21 retains final full-size rendering/accessibility inspection.
- The evidence-inspection interaction may use an accessible platform-specific loupe or step inspector downstream.
- Prototype webfont loading is not approval of remote font hosting/licensing; the accepted typography direction is represented by `design-tokens/1.0`.
- Prototype sign-in/provider and system purchase/share sheets remain implementation placeholders owned by their downstream tasks.

## Qualification evidence

Acceptance/token/documentation head `4a786230fcb9d70c1c8f75bba8b02c73ec2aad25` passed:

- CI run `36506833905`: Python 3.10/3.11/3.12, generated-contract/token checks, full pytest, consent/product-contract fault injection, research checks and installed-wheel smoke.
- Roadmap integrity run `36506833900`: task graph/backlog/link tooling, including T10 DONE → T29 derived READY regression.
- Application environments run `36506833890`: backend/PostgreSQL, TypeScript, render/package tests, browser/accessibility fixtures and isolated live Free upload → report → PDF export.

## Owner decision

Decision: **ACCEPTED_WITH_CHANGES**

- decided by role: product/design owner
- decided on: 2026-09-29
- accepted prototype reference: `Inktrospect mobile app design (2).zip`
- accepted artifact SHA-256: `89b43380609dec56bdb82c284f0f6beb4c097692273ef13a3b23deb143ff7db5`
- material changes/limitations: [ACCEPTED_DOSSIER_REFERENCE.md](ACCEPTED_DOSSIER_REFERENCE.md)

The T10 design gate is closed. This does not activate Premium, payments, participant collection, native signing, store publication or public release.
