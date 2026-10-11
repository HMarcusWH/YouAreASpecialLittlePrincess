import type { ConfigContext, ExpoConfig } from "expo/config";

// Build variants are explicit and environment-bound (N17). Values come from the
// build environment, never from the app at runtime, and are validated again by
// src/config/runtime.ts before any network call:
//   INKTROSPECT_APP_VARIANT   development | staging | store   (default development)
//   INKTROSPECT_API_BASE      device-reachable API origin, e.g. http://192.168.1.20:8000 (dev) or https://api…
//   INKTROSPECT_BACKEND_ENV   local | test | preview | staging | production (defaults per variant)
//   INKTROSPECT_UPLOAD_ORIGINS  extra comma-separated upload origins (presigned storage), optional
//   INKTROSPECT_LINK_HOSTS    comma-separated verified link domains (Universal Links / App Links), optional
// No signing material, provider secret or credential is ever placed here.
type Variant = "development" | "staging" | "store";

// The app name stays "Inktrospect" in every variant: CNG derives the Xcode workspace/scheme from it and the
// native CI builds Inktrospect.xcworkspace. Variants differ by identifier, scheme and backend.
const VARIANTS: Record<Variant, { id: string; scheme: string; backend: string }> = {
  development: { id: "se.inktrospect.development", scheme: "inktrospect-dev", backend: "local" },
  staging: { id: "se.inktrospect.staging", scheme: "inktrospect-staging", backend: "staging" },
  store: { id: "se.inktrospect", scheme: "inktrospect", backend: "production" },
};

function list(value: string | undefined): string[] {
  return (value ?? "").split(",").map((item) => item.trim()).filter(Boolean);
}

export default ({ config }: ConfigContext): ExpoConfig => {
  const requested = process.env.INKTROSPECT_APP_VARIANT ?? "development";
  if (!(requested in VARIANTS)) throw new Error(`INKTROSPECT_APP_VARIANT must be one of ${Object.keys(VARIANTS).join(", ")}`);
  const variant = requested as Variant;
  const profile = VARIANTS[variant];
  const backendEnvironment = process.env.INKTROSPECT_BACKEND_ENV ?? profile.backend;
  const linkHosts = list(process.env.INKTROSPECT_LINK_HOSTS);
  // Development identity exists only in development builds against a local/test API.
  // An HTTPS guest-only demo must never display development account/token helpers.
  const remoteGuestOnly = process.env.INKTROSPECT_REMOTE_GUEST_ONLY === "1";
  if (remoteGuestOnly && (variant !== "development" || backendEnvironment !== "test" ||
      !process.env.INKTROSPECT_API_BASE?.startsWith("https://"))) {
    throw new Error("INKTROSPECT_REMOTE_GUEST_ONLY requires development/test over HTTPS");
  }
  const devIdentity = !remoteGuestOnly && variant === "development" &&
    (backendEnvironment === "local" || backendEnvironment === "test");

  return {
    ...config,
    name: "Inktrospect",
    slug: "inktrospect",
    version: "0.1.0",
    scheme: profile.scheme,
    orientation: "default",
    userInterfaceStyle: "automatic",
    experiments: { typedRoutes: true },
    ios: {
      supportsTablet: true,
      bundleIdentifier: profile.id,
      ...(linkHosts.length > 0 ? { associatedDomains: linkHosts.map((host) => `applinks:${host}`) } : {}),
      infoPlist: {
        // Release builds keep ATS strict; development may reach a LAN API.
        ...(variant === "development" ? { NSAppTransportSecurity: { NSAllowsLocalNetworking: true } } : {}),
        ITSAppUsesNonExemptEncryption: false,
      },
    },
    android: {
      package: profile.id,
      // The system Photo Picker needs no media permission, so the Android 13+ media permissions and the
      // microphone are blocked. The picker library's legacy storage pair (maxSdkVersion 32) stays: its
      // camera capture requires WRITE_EXTERNAL_STORAGE on Android 7-9 (minSdk 24). Neither is requested
      // for picking.
      blockedPermissions: [
        "android.permission.RECORD_AUDIO",
        "android.permission.READ_MEDIA_IMAGES",
        "android.permission.READ_MEDIA_VIDEO",
        "android.permission.READ_MEDIA_AUDIO",
        "android.permission.READ_MEDIA_VISUAL_USER_SELECTED",
      ],
      ...(linkHosts.length > 0 ? {
        intentFilters: [{
          action: "VIEW",
          autoVerify: true,
          data: linkHosts.map((host) => ({ scheme: "https", host, pathPrefix: "/reports" })),
          category: ["BROWSABLE", "DEFAULT"],
        }],
      } : {}),
    },
    plugins: [
      "expo-router",
      "expo-dev-client",
      ["expo-secure-store", { configureAndroidBackup: true }],
      ["expo-image-picker", {
        photosPermission: false,
        cameraPermission: "Take a photo of your handwriting to analyse it.",
        microphonePermission: false,
      }],
      "expo-notifications",
      "expo-sharing",
      "expo-splash-screen",
      "expo-status-bar",
      "expo-web-browser",
      "expo-iap",
      ["expo-build-properties", {
        ios: { deploymentTarget: "16.4" },
        // Android 9+ refuses cleartext by default. Only development binaries (including the non-debuggable
        // release-variant developer handoff APK) may reach a local/LAN HTTP API; staging/store stay HTTPS-only.
        android: { minSdkVersion: 24, compileSdkVersion: 36, targetSdkVersion: 36,
                   usesCleartextTraffic: variant === "development" },
      }],
    ],
    extra: {
      runtime: {
        variant,
        backendEnvironment,
        apiBaseUrl: process.env.INKTROSPECT_API_BASE ?? "",
        uploadOrigins: list(process.env.INKTROSPECT_UPLOAD_ORIGINS),
        devIdentity,
        linkSchemes: [profile.scheme],
        linkHosts,
      },
      t29: {
        environment: variant,
        authority: "server",
        note: "No signing, provider, purchase or measurement authority is configured in the app.",
      },
    },
  };
};
