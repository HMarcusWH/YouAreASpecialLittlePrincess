# Apple / App Store release evidence checklist

[Index](../roadmap/00-index.md) · [Apple specification](../roadmap/12-apple-platform-and-app-store.md) · [T32](../roadmap/06-agent-backlog.md#t32) · [Final signoff](multi-platform-signoff.md).

Status: PENDING. Do not mark store/account/signing evidence complete through code generation. T32 prepares readiness and actual review/testing evidence; T25 authorizes public rollout.

- [ ] Approved seller/developer team, App Store Connect app, bundle IDs, banking/tax agreements and product catalog; safe private evidence references only.
- [ ] Protected signing/App Store Connect/APNs credentials, exact Xcode/SDK/native dependency build matrix and tested configuration profiles.
- [ ] Signed candidate artifact digest/build/version, current store submission requirements and actual iPhone/iPad device matrix.
- [ ] Full capture/HEIC/orientation, limited/denied photo/camera permission, VoiceOver/dynamic text, share/PDF and lifecycle recovery evidence.
- [ ] Correct login/private-relay/account linking, Universal Links/AASA, APNs token/environment behavior, risk-signal fallback and secure cache/logout behavior.
- [ ] StoreKit products/prices, pending/cancelled/unverified purchases, server proof validation, one durable credit grant, finish-after-grant crash recovery and refunds.
- [ ] Account-ledger recovery of consumable balances/saved reports; restore does not mint consumed credits again; approved cross-platform spending policy.
- [ ] In-app account deletion, actual SDK/privacy manifest/required-reason review, App Privacy answers and accurate AI-image-processing/retention notice.
- [ ] StoreKit/local sandbox and TestFlight results separated from production; named testers/evidence without fabricated participation.
- [ ] Accurate screenshots/localization/age rating, privacy/support URLs, accessible feedback/report-content path, reviewer account/instructions and reachable backend.
- [ ] Recorded app and IAP review status, rejection/remediation if any, staged release/halt/rollback plan and monitoring owner.

Every approval records date, scope and evidence. A successful EAS/Xcode upload is not App Store acceptance, and acceptance is not an unattended instruction to release publicly. Store policies must be refreshed for the release candidate.
