# ADR-005 — Expo/React Native with real platform capabilities

[Index](README.md) · [Mobile specification](../roadmap/11-mobile-architecture.md) · [Apple](../roadmap/12-apple-platform-and-app-store.md) · [Android](../roadmap/13-android-and-google-play.md).

Status: IMPLEMENTATION_DEFAULT; exact SDK/native purchase bridge and build-service decision gated by T29 compatibility evidence.

Use Expo/React Native/Expo Router for native screens and navigation. Share DTOs, API client, safe report formatting/chart specifications and design tokens with web. Render native accessibility/layout primitives; do not package the web report in a webview and call it feature parity.

Alternatives: separate Swift/Kotlin apps (maximal platform control but duplicate UI/state work), Flutter (less TypeScript sharing), webview wrapper (does not satisfy desired native capture/billing/privacy experience). Native escape hatches remain allowed behind tested platform ports, with explicit prebuild/config-plugin or committed-native ownership.

T29 must verify secure storage, camera/photo picker/HEIC handling, deep links, APNs/FCM, native purchases, tablet layouts and release builds under pinned versions. IAP requires development/store builds, not Expo Go alone. EAS is a candidate service; signing/private-data handling requires owner approval and a documented local build alternative. Never promise OTA changes can replace a native rebuild/store review.
