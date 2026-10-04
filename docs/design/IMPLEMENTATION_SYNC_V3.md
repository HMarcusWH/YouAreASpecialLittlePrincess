# Inktrospect design v3 — post-acceptance implementation sync

Status: **IMPLEMENTATION_REFERENCE**, not a new design-acceptance decision.

The historical T10 owner decision remains bound to `Inktrospect mobile app design (2).zip` and its recorded digest. This document records the later design-to-code synchronization used to finish the native client without rewriting that history.

## Artifact identity

| Field | Value |
|---|---|
| Artifact | `Inktrospect mobile app design (3).zip` |
| SHA-256 | `12253a30614b31b54d9585eec262956a49c06dad10a7070c1b71949d6f334f98` |
| Size | 377,913 bytes |
| Prototype sync timestamp | `2026-10-04T13:25:58Z` |
| Declared repository | `HMarcusWH/YouAreASpecialLittlePrincess` |
| Repository baseline | `3099bcf1e71a98430c4ca39ae26a39e5eacfde48` |
| Relationship | post-acceptance implementation sync for Direction A — The Dossier |

The exact immutable archive is retained in this repository at [`artifacts/2026-10-04-v3/Inktrospect-mobile-design-v3.zip`](artifacts/2026-10-04-v3/Inktrospect-mobile-design-v3.zip), with verification and inspection instructions in the adjacent [artifact README](artifacts/2026-10-04-v3/README.md). It is handoff evidence and an inspectable UX/composition reference, not a second source tree. Verify the recorded digest, extract it only to a temporary directory, and compare its embedded snapshots against current repository source; never unzip it over the working tree.

## Safety and provenance audit

The supplied archive was enumerated before implementation. It contains 47 members: prototype HTML, design-system CSS/JS/JSON, repository snapshots, one illustrative PNG, native/web frame helpers and documentation. No font binaries, credentials, JWTs, signing material, participant writing, private report payloads or obvious personal identifiers were found.

The archive is **reference evidence, not source authority**. Current repository code/contracts win whenever a snapshot differs.

A source-snapshot comparison against the declared baseline found:

- 25 embedded repository snapshots that were checked matched the declared baseline byte-for-byte;
- the embedded `packages/report-web/src/messages.ts` is stale relative to the current repository consolidation into `@princess/report-core` and must not be copied back;
- `content/native-copy.json` is prototype-only and is not a repository authority; native app copy remains `apps/mobile/src/i18n/copy.ts`;
- the archive README still lists `reason.already_unlocked` as a remaining copy gap even though the current `@princess/report-core` message catalogue already contains EN/SV values.

These mismatches are preserved here specifically to prevent a future “unzip over the repository” migration.

## What v3 refines

The v3 prototype does not reopen visual direction. It keeps the accepted Dossier system and reconciles it with the post-T10 product:

- current native landing/capture/review/work/settings/account/feedback flows;
- `individual-report/2` server-owned First Reveal plus legacy v1 behavior;
- T18 same-owner comparison fixtures and no-overlap/equal/history states;
- full-size print/share reference;
- light/night, EN/SV, phone/tablet and large-text review states;
- native evidence inspection target, including a touch loupe in the prototype and an accessible sequential inspector fallback.

System-owned StoreKit/Google Play/share sheets, prices/provider identities, Premium prose, T22 invitations, challenge-provider UI and illustrative specimen lettering remain schematic/planned. They are not production inputs.

## Implementation rule

Production implementation follows this precedence:

1. current repository contracts, permissions, saved report truth and tests;
2. accepted semantic tokens and T10 acceptance records;
3. this v3 prototype for composition, hierarchy and interaction intent;
4. prototype-only illustrative values last, and never as application truth.

No client-side measurement, salience selection, entitlement, permission or population claim may be introduced to match a mockup.

## Native evidence-inspection decision

The v3 touch design demonstrates a ~380 ms hold-and-drag loupe. The original accepted T10 limitation explicitly permits a platform-appropriate loupe **or** accessible step inspector. For this implementation pass the native app uses the deterministic sequential inspector over stored evidence geometry, with Previous/Next controls and the selected stored trace highlighted. This avoids adding a gesture dependency or risking scroll interception without physical-device qualification. A future physical-device review may add the loupe without changing evidence authority.

## Typography

The prototype references Newsreader and IBM Plex Mono through design tooling, but ships no font binaries. Native continues to use reviewed platform serif/monospace fallbacks in this pass. Font packaging is a separate rights/delivery decision and does not block the engineering APK. Cedarville Cursive remains illustrative-only and is never used as user evidence.

## Verification boundary

This record does not prove native UI/device/store behavior. The implementation PR must keep TypeScript/unit/native compile workflows green. After merge, the `main` native workflow retains the Android development APK from the durable merge commit; PR builds remain merge-candidate qualification. Physical-device visual/accessibility review remains T30/T31 qualification.
