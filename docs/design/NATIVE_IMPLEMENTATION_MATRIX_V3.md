# Native Dossier v3 implementation matrix

Source reference: [design v3 implementation sync](IMPLEMENTATION_SYNC_V3.md). Statuses below describe **native implementation scope**, not provider/store/release approval.

Status vocabulary:

- **MATCH** — current native implementation already satisfies the v3 intent under repository truth.
- **IMPLEMENTED_V3** — this pass changes presentation/interaction to match v3.
- **SYSTEM_OWNED** — native OS/store UI; the app invokes it but does not draw a fake replacement.
- **PLANNED** — owning product contract/task is not complete; do not fabricate it.
- **ILLUSTRATIVE** — prototype-only content/data, never application truth.
- **NOT_NATIVE_SCOPE** — web/print-specific reference.

| Journey surface | v3 disposition | Native implementation / constraint |
|---|---|---|
| Landing | IMPLEMENTED_V3 | Dossier typography, paper hierarchy and reduced card chrome over existing guest/account states. |
| Capture | IMPLEMENTED_V3 | Native camera/picker behavior unchanged; presentation uses the accepted paper/action hierarchy. |
| Crop/review/permission | IMPLEMENTED_V3 | Existing real notice/crop/retention semantics retained; composition uses Dossier primitives. |
| Processing/recovery | IMPLEMENTED_V3 | Existing durable journal states remain authoritative; progress is presented as an editorial step list. |
| First Reveal | IMPLEMENTED_V3 | Server-provided T08A highlight only; no client selection. Primary highlight becomes the opening statement. |
| Free Dossier | IMPLEMENTED_V3 | Editorial sections/hairlines replace generic report cards; every authorized fact remains visible. |
| Evidence | IMPLEMENTED_V3 | Stored geometry only; source-image plate plus sequential accessible trace inspector. No new measurement. |
| Premium offer/purchase/generation | IMPLEMENTED_V3 | Existing real state machinery gets shared visual primitives; no invented products/prose. |
| Store purchase sheet | SYSTEM_OWNED | StoreKit / Play UI remains OS/store-owned. |
| Premium prose examples | ILLUSTRATIVE | Never copied from prototype; only saved validated overlay is rendered. |
| History | IMPLEMENTED_V3 | Existing owner history preserved; near-square paper rows and editorial metadata. |
| Same-owner comparison | IMPLEMENTED_V3 | Existing T18 DTO/presentation only; no similarity score or client normalization. |
| Other-owner invitations | PLANNED | T22 remains owner of authorization/invitation flow. |
| Share system sheet | SYSTEM_OWNED | `expo-sharing`/platform sheet; prototype chrome is schematic. |
| PDF/share-card output | NOT_NATIVE_SCOPE | Existing T21 renderer remains authority; native only requests/downloads/shares authorized output. |
| Settings/privacy | IMPLEMENTED_V3 | Existing real permission/session/notification behavior; shared paper/group presentation. |
| Feedback | MATCH | Existing T24 five-category flow is already synchronized with v3; shared primitives carry styling. |
| Push provider delivery | PLANNED | Live APNs/FCM qualification remains outside design implementation. |
| Fonts | MATCH | Token intent retained with local platform fallbacks; no remote font fetch or unreviewed font binaries. |
| Illustrative handwriting glyphs | ILLUSTRATIVE | Never substituted for authorized user source image. |
| Prices/provider names/retry timings | ILLUSTRATIVE | Runtime/server/store truth only. |
| Challenge-provider screens | PLANNED | No fake provider behavior is added for visual fidelity. |

## Representative visual/accessibility acceptance

The implementation is expected to compile and render across the existing iOS/Android native targets. Final physical-device review remains pending, but code/review must explicitly cover:

- phone and tablet width behavior;
- light and night paper;
- English and Swedish;
- 200% text without fixed-height truncation;
- 44 pt minimum actions;
- screen-reader labels for evidence/status/action state;
- missing/uncalibrated/revoked states without zero substitution;
- reduced-motion-safe behavior;
- no hidden personalized Premium teaser text;
- no population/rank language without an eligible reference release.

The matrix deliberately avoids an exhaustive screenshot grid. Representative critical-state inspection plus contract/state tests is preferred over hundreds of brittle golden images.
