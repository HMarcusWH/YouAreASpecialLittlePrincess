import type { ConfigContext, ExpoConfig } from "expo/config";

export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: "Inktrospect",
  slug: "inktrospect",
  version: "0.1.0",
  scheme: "inktrospect-dev",
  orientation: "default",
  userInterfaceStyle: "automatic",
  experiments: { typedRoutes: true },
  ios: {
    supportsTablet: true,
    bundleIdentifier: "se.inktrospect.development",
  },
  android: {
    package: "se.inktrospect.development",
  },
  plugins: [
    "expo-router",
    "expo-dev-client",
    ["expo-secure-store", { configureAndroidBackup: true }],
    ["expo-image-picker", {
      photosPermission: "Choose a handwriting image to analyze.",
      cameraPermission: "Take a handwriting photo to analyze.",
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
    t29: {
      environment: "development",
      authority: "server",
      note: "Non-production scaffold; no signing, provider, purchase or measurement authority.",
    },
  },
});
