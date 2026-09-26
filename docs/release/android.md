# Android / Google Play release evidence checklist

[Index](../roadmap/00-index.md) · [Android specification](../roadmap/13-android-and-google-play.md) · [T33](../roadmap/06-agent-backlog.md#t33) · [Final signoff](multi-platform-signoff.md).

Status: PENDING. T33 prepares actual Play/device/billing evidence; T25 authorizes staged production publication.

- [ ] Approved developer account/entity and production-access eligibility; record which account-specific testing requirements apply and actual completion evidence.
- [ ] Application ID/variants, Play App Signing/upload-key custody, Developer API roles, product IDs and authenticated RTDN/Pub/Sub configuration.
- [ ] Signed AAB digest, versionCode/versionName and exact JDK/Gradle/SDK/native module matrix; verify current target API, billing-library and native compatibility requirements.
- [ ] Real phone/tablet capture, picker/permission denial, rotation/process death, TalkBack/text scaling, file sharing and secure-session behavior.
- [ ] Verified App Links/release certificate association, FCM token rotation/account binding and Play Integrity/fallback tests.
- [ ] Play Billing localized product details, pending/cancelled/success purchase states, server token verification and account/product binding.
- [ ] One grant per token, durable grant-before-consume, completion retry/reconciliation, refund/voided-purchase handling and account-backed credit recovery.
- [ ] RTDN replay/reordering/missed events and Pub/Sub authentication tests; no native secret and no grant on client callback alone.
- [ ] Internal/closed/other required track evidence, actual tester participation and prelaunch/crash/ANR outcomes; do not infer approval from elapsed time alone.
- [ ] Current Data Safety/app-access/AI-content/deletion requirements checked, in-app and public deletion paths working, privacy/support URLs and feedback mechanism available.
- [ ] Accurate listing/screenshots/localization/content rating, approved price/refund/storefront terms, reviewer access and reachable backend.
- [ ] Play review status, staged rollout/halt strategy, compatible API support window and monitoring/support owner.

Missing external policy retrieval or account details remains a release blocker for the affected item, not an invitation to reuse a remembered tester count or SDK deadline. Store acceptance and public rollout are separately recorded.
