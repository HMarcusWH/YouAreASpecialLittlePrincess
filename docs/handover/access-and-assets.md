# Access, assets and custody

This is a **non-secret handover register**, not evidence that recipient access has been granted. The repository account owner is `HMarcusWH`; operational custodians and a private transfer channel must be confirmed with the product/technical owner. Never put keys, tokens, signing files, private writing, participant agreements or database dumps here.

| Resource | Repository reference | Handover action / current limit |
|---|---|---|
| GitHub repository, review and Actions | [Contribution guide](../../CONTRIBUTING.md), `.github/workflows/` | Confirm recipient permissions, review/protection settings and incident contact privately. No administration settings are changed by this PR. |
| Backend host/registry/network/secrets | [Provider decisions](../roadmap/19-provider-decision-register.md), [runtime](../../infra/runtime/README.md) | Production stack not fully selected/qualified. Assign custody before deployment; do not infer a live service from a manifest. |
| Application PostgreSQL and private object/tombstone stores | [Infrastructure](../../infra/README.md), [migrations](../../migrations/README.md) | Distinguish disposable development data from selected production providers. Transfer access through the actual secret manager when chosen. |
| Supabase identity and protected T17 material | [Deferred runbook](../ci/T17_SUPABASE_STAGING_AUTH_OPERATOR_RUNBOOK.md) | Owner retains qualification receipt, issuer/profile, raw Auth capture and disposable-witness evidence outside Git. Obtain scoped authorized access; do not mine Auth tables for credentials. |
| Apple developer/App Store/signing | [Apple release](../release/apple.md) | Confirm team, bundle ownership, protected key custody, product/account setup and signed-device access. No signed/store approval is asserted here. |
| Google developer/Play/signing | [Android release](../release/android.md) | Confirm application and merchant ownership, signing and notification/API access. No production-track approval is asserted here. |
| Model account/data/spend | [Premium connector](../connectors/premium-model.md) | Confirm approved model configuration, processing controls, spend owner and eval evidence before live calls. |
| Mail, push, domains and telemetry | [Connector index](../connectors/README.md) | Verify sender/domain ownership, provider retention, alert routing and named escalation; do not invent a contact or vendor. |
| Reference/pilot participant material | [Pilot tooling](../data/pilot-tooling.md), [privacy](../privacy/README.md) | Protected evidence and permissions remain external. Synthetic tooling is not a participant corpus. |
| Accepted design | [Accepted reference](../design/ACCEPTED_DOSSIER_REFERENCE.md), [v3 implementation sync](../design/IMPLEMENTATION_SYNC_V3.md), [retained v3 artifact](../design/artifacts/2026-10-04-v3/README.md) | The historical accepted v2 artifact still requires an approved owner-controlled location. The exact v3 implementation-sync archive is retained in Git and should be checksum-verified before inspection. |
| Code/data/weights/fonts rights | [Third-party notices](../../THIRD_PARTY_NOTICES.md), [source rights](../privacy/source-rights.md) | Preserve each rights category separately; no new project distribution license is selected by this handover. |

## Accepted design artifact

Filename: `Inktrospect mobile app design (2).zip`.

SHA-256: `89b43380609dec56bdb82c284f0f6beb4c097692273ef13a3b23deb143ff7db5`.

The acceptance record binds this digest. The archive is intentionally not in Git. A conversation attachment is not a durable retrieval location. The outgoing owner must provide an approved location and the receiving maintainer must record a successful hash check. Do not upload font files separately or substitute prototype typography for an approved delivery strategy.

## Latest implementation-sync design artifact

Filename: `Inktrospect mobile app design (3).zip`.

SHA-256: `12253a30614b31b54d9585eec262956a49c06dad10a7070c1b71949d6f334f98`.

Prototype sync: `2026-10-04T13:25:58Z`; repository baseline: `3099bcf1e71a98430c4ca39ae26a39e5eacfde48`.

This is the post-acceptance implementation reference described in [IMPLEMENTATION_SYNC_V3.md](../design/IMPLEMENTATION_SYNC_V3.md), not a replacement for the v2 T10 owner decision. The exact archive is retained at [`../design/artifacts/2026-10-04-v3/Inktrospect-mobile-design-v3.zip`](../design/artifacts/2026-10-04-v3/Inktrospect-mobile-design-v3.zip) for a self-contained developer handoff. Its embedded repository snapshots are reference evidence only; current repository code/contracts win. Verify the SHA-256 before use and extract it to a temporary directory rather than over the checkout.

## Transfer record to complete privately

For each applicable resource record the outgoing/receiving custodians, least-privilege scope, delivery channel, recipient access test, timestamp and outstanding restrictions. Keep only an opaque safe receipt reference here when appropriate. Rotation/revocation belongs to the actual owner-approved account process; adding a developer to GitHub does not transfer all provider rights.

Outstanding at this documentation baseline: recipient identity, historical v2 design retrieval location, account-access confirmation, independent acceptance run, production custodians and any owner decision on project licensing/distribution. These are open handover actions, not missing prose that an agent can fill with invented approvals.
