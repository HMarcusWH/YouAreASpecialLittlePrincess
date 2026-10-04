# Inktrospect mobile design v3 — immutable implementation reference

This directory retains the exact post-acceptance v3 design handoff used to reconcile the native Dossier implementation in PR #75.

## Artifact identity

| Field | Value |
|---|---|
| Repository file | `Inktrospect-mobile-design-v3.zip` |
| Source filename | `Inktrospect mobile app design (3).zip` |
| SHA-256 | `12253a30614b31b54d9585eec262956a49c06dad10a7070c1b71949d6f334f98` |
| Size | 377,913 bytes |
| Archive members | 47 |
| Prototype sync timestamp | `2026-10-04T13:25:58Z` |
| Declared repository baseline | `3099bcf1e71a98430c4ca39ae26a39e5eacfde48` |
| Relationship | post-acceptance implementation reference for Direction A — The Dossier |

Historical T10 acceptance remains bound to the v2 artifact recorded in `../../ACCEPTED_DOSSIER_REFERENCE.md`. Retaining v3 here does not reopen or replace that owner decision.

## How to inspect it

1. Verify the archive before use:
   ```bash
   sha256sum -c SHA256SUMS
   ```
2. Extract it to a temporary directory, **not over this repository checkout**.
3. Open `Inktrospect App.dc.html` directly in a browser to inspect the interactive app reference.
4. Open `Inktrospect Print and Share.dc.html` directly in a browser to inspect the print/share reference.
5. Inspect the bundled `_ds/` design-system CSS/JS/tokens, native frame helpers, synthetic report/comparison fixtures and state examples as implementation evidence.
6. Compare every proposed change against the current repository before porting it.

## Authority boundary

Use this precedence when the artifact and live checkout differ:

1. current repository contracts, permissions, saved-report truth and tests;
2. accepted semantic tokens and T10 acceptance records;
3. this v3 archive for composition, hierarchy and interaction intent;
4. prototype-only illustrative values last, and never as application truth.

Do **not** copy the archive's embedded repository snapshots back into the checkout wholesale. In particular, the audited archive contains a stale `packages/report-web/src/messages.ts`, a prototype-only `content/native-copy.json`, and a README copy-gap note for `reason.already_unlocked` that current report-core copy has already resolved.

## Provenance and safety

The retained archive was audited before implementation. It contains 47 members including prototype HTML/JavaScript, generated design-system material, repository snapshots, one illustrative PNG, native/web frame helpers and documentation. No font binaries, credentials, JWTs, signing material, participant writing, private report payloads or obvious personal identifiers were found.

The archive is intentionally committed as one immutable ZIP rather than as a second extracted source tree. If the design changes later, add a separately identified artifact and reconciliation record instead of mutating this file in place.
