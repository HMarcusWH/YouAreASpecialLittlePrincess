// The real native ports for this build. Imported only by the React tree, so
// tests and the Node journey never load native modules.
import Constants from "expo-constants";
import { Platform } from "react-native";

import { parseRuntimeConfig, type ConfigResult, type RuntimeConfig } from "../config/runtime.ts";
import { AllowlistedDeepLinkRouter } from "../platform/links.ts";
import { ExpoCaptureClient, ExpoImagePreparer } from "../platform/native/capture.ts";
import { ExpoAuthorizedFiles, ExpoDocumentStore, ExpoLocalFiles } from "../platform/native/files.ts";
import { ExpoIapPurchaseClient } from "../platform/native/purchases.ts";
import { ExpoDevicePushClient } from "../platform/native/push.ts";
import { ExpoSecureSessionStore } from "../platform/native/secure-session.ts";
import { ExpoFileShareClient } from "../platform/native/share.ts";
import { createServices, type Services } from "./services.ts";
import { newClientId } from "./ids.ts";

export function loadConfig(): ConfigResult {
  const extra = Constants.expoConfig?.extra as { runtime?: unknown } | undefined;
  return parseRuntimeConfig(extra?.runtime);
}

export function createNativeServices(config: RuntimeConfig): Services {
  const purchases = Platform.OS === "ios" ? new ExpoIapPurchaseClient("apple_app_store")
    : Platform.OS === "android" ? new ExpoIapPurchaseClient("google_play") : null;
  return createServices(config, {
    secureStore: new ExpoSecureSessionStore(),
    documents: new ExpoDocumentStore(),
    files: new ExpoLocalFiles(config.uploadOrigins),
    preparer: new ExpoImagePreparer(),
    capture: new ExpoCaptureClient(),
    downloads: new ExpoAuthorizedFiles(config.apiBaseUrl),
    share: new ExpoFileShareClient(),
    purchases,
    push: new ExpoDevicePushClient(),
    links: new AllowlistedDeepLinkRouter(config.linkSchemes, config.linkHosts),
  }, { fetch: (input, init) => globalThis.fetch(input, init), timers: { setTimeout, clearTimeout: (h) => clearTimeout(h as ReturnType<typeof setTimeout>) },
       newId: newClientId });
}

export function nativePlatform(): "ios" | "android" {
  return Platform.OS === "ios" ? "ios" : "android";
}
