# ADR-005 — Expo/React Native with real platform capabilities

[Index](README.md) · [Mobile specification](../roadmap/11-mobile-architecture.md) · [Apple](../roadmap/12-apple-platform-and-app-store.md) · [Android](../roadmap/13-android-and-google-play.md).

Status: T29_FOUNDATION_PINNED; provider-independent compatibility selected, signed-device/provider activation still gated.

Use **Expo 57.0.25 / React Native 0.86.3 / Expo Router 57.0.23** for native screens and navigation. Share DTOs, API client, safe report formatting/chart specifications and design tokens with web. Render native accessibility/layout primitives; do not package the web report in a webview and call it feature parity.

Alternatives: separate Swift/Kotlin apps (maximal platform control but duplicate UI/state work), Flutter (less TypeScript sharing), webview wrapper (does not satisfy desired native capture/billing/privacy experience). Native escape hatches remain allowed behind tested platform ports, with explicit prebuild/config-plugin or committed-native ownership.

T29 selected CNG/prebuild plus reviewed config plugins and exact-pinned native dependencies. Android CNG + debug compilation with the real IAP/capture/session module graph is qualified; the permanent native workflow also qualifies an iOS simulator build. T29 must still obtain real signed-device/IAP evidence before DONE. IAP requires development/store builds, not Expo Go alone. EAS is a candidate service; signing/private-data handling requires owner approval and a documented local build alternative. Never promise OTA changes can replace a native rebuild/store review.
