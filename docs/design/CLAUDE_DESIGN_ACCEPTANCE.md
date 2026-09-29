# T10 owner design-acceptance record

**Status: PENDING_OWNER_REVIEW**

This file is the review checklist for the Claude Design prototype. Its presence does **not** mean the design is accepted. An agent must not mark T10 `DONE`, change the design-token status, or fill in an owner decision without an explicit owner instruction.

## Prototype identity

- Claude Design project/prototype reference: **PENDING**
- Working public brand: **Inktrospect** (repository/package namespaces remain unchanged)
- Design direction selected: **A — The Dossier**
- Repository baseline used for handoff: `8163770f19cbbf3b5cf60fb77d0d52003dc2cfaf`
- Prototype revision reviewed: **PENDING**

## Owner review checklist

### Complete journey

- [ ] Landing: signed out / returning / unfinished guest
- [ ] Permission and upload, including separate optional permissions
- [ ] Crop/orientation/error states
- [ ] Processing lifecycle and refresh recovery
- [ ] First reveal / “What stands out”, including no-eligible-highlight and image-not-retained states
- [ ] Complete and partial Free report
- [ ] No-reference / uncalibrated / image-revoked report states
- [ ] Premium offer and explicit AI-image-processing permission
- [ ] Purchase pending / Ask to Buy / cancelled / failed / restored / account mismatch
- [ ] Premium generation queued / running / success / refusal / failure / not-applicable
- [ ] Premium report keeps Free facts unchanged and labels AI synthesis
- [ ] T18 pair/history/no-overlap comparison mechanics are shown from the real fixtures, while T22 invitation and other-owner authorization/release states remain clearly marked planned
- [ ] History empty / revisions / deleted capture
- [ ] Share preview / disabled / revoked
- [ ] A4 / Letter export preview, image omission and failure
- [ ] Settings / notification preference / logout / deletion

### Platform review

- [ ] Web desktop
- [ ] Web at 320 px
- [ ] iPhone
- [ ] iPad
- [ ] Android phone
- [ ] Android tablet
- [ ] A4 / Letter print
- [ ] Square / story share cards

### Accessibility and localization

- [ ] Light and dark themes
- [ ] Reduced motion
- [ ] Web keyboard/focus order
- [ ] Native screen-reader intent
- [ ] Charts have text alternatives
- [ ] Status changes are announced
- [ ] 44 px minimum touch targets
- [ ] 320 px at 200% text scaling has no clipped meaning
- [ ] Swedish and English layouts are acceptable
- [ ] “Bokstavsavståndsvariation” fits without invented abbreviation
- [ ] “Tredjepartsbehandling av bilden” fits without invented abbreviation

### Evidence and product truth

- [ ] Missing is never shown as zero
- [ ] Uncalibrated is not presented as statistical confidence
- [ ] Evidence classes differ by more than colour
- [ ] No fabricated percentile, rarity or uniqueness
- [ ] No fake personalized blurred Premium content
- [ ] No diagnostic/intelligence/honesty/employability/compatibility language
- [ ] Free remains useful and available during paid failures
- [ ] Native design does not imply client measurement/credit authority
- [ ] Planned features are labelled planned/illustrative rather than implemented

## Acceptance-candidate repository state

- Repository reconciliation baseline: `8163770f19cbbf3b5cf60fb77d0d52003dc2cfaf` (merged PR #29 / T18 deterministic comparison).
- T08A First Reveal mechanics and the v2 report fixture are implemented product truth.
- T18 pair/history/no-overlap comparison mechanics and fixtures are implemented product truth.
- T17 still owns production Dossier rendering/activation; T22 still owns invitation and other-owner comparison release.
- Design tokens remain `DRAFT_PENDING_DESIGN_ACCEPTANCE` until the owner explicitly accepts one concrete prototype reference/revision.

## Owner decision

Decision: **PENDING**

When the owner explicitly decides, record:

- decision: ACCEPTED / REJECTED / ACCEPTED_WITH_CHANGES
- decided by role: product/design owner
- decided on: date
- accepted prototype reference/revision
- material changes or limitations

A future gate-closing commit may promote T10 only when this section reflects the owner's explicit decision and the accepted prototype covers the task acceptance criteria.
