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

const VARIANTS: Record<Variant, { id: string; scheme: string; name: string; backend: string }> = {
  development: { id: "se.inktrospect.development", scheme: "inktrospect-dev", name: "Inktrospect Dev", backend: "local" },
  staging: { id: "se.inktrospect.staging", scheme: "inktrospect-staging", name: "Inktrospect Staging", backend: "staging" },
  store: { id: "se.inktrospect", scheme: "inktrospect", name: "Inktrospect", backend: "production" },
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
  const devIdentity = variant === "development" && (backendEnvironment === "local" || backendEnvironment === "test");

  return {
    ...config,
    name: profile.name,
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
      // The system Photo Picker needs no media permission; nothing broader is requested.
      blockedPermissions: [
        "android.permission.RECORD_AUDIO",
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.WRITE_EXTERNAL_STORAGE",
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
        android: { minSdkVersion: 24, compileSdkVersion: 36, targetSdkVersion: 36 },
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
