import assert from "node:assert/strict";
import test from "node:test";

import appConfig from "../app.config.ts";
import { parseRuntimeConfig } from "../src/config/runtime.ts";

function build(env: Record<string, string>) {
  const saved = { ...process.env };
  for (const key of Object.keys(process.env)) if (key.startsWith("INKTROSPECT_")) delete process.env[key];
  Object.assign(process.env, env);
  try {
    return appConfig({ config: {} } as never);
  } finally {
    for (const key of Object.keys(process.env)) if (key.startsWith("INKTROSPECT_")) delete process.env[key];
    Object.assign(process.env, saved);
  }
}

test("a store build targets production over HTTPS with no development identity", () => {
  const config = build({ INKTROSPECT_APP_VARIANT: "store", INKTROSPECT_API_BASE: "https://api.inktrospect.se",
                         INKTROSPECT_LINK_HOSTS: "inktrospect.se" });
  const runtime = parseRuntimeConfig((config.extra as { runtime: unknown }).runtime);
  assert.ok(runtime.ok, JSON.stringify(runtime));
  assert.equal(runtime.config.devIdentity, false);
  assert.equal(config.ios?.bundleIdentifier, "se.inktrospect");
  assert.deepEqual(config.ios?.associatedDomains, ["applinks:inktrospect.se"]);
  assert.equal((config.ios?.infoPlist as Record<string, unknown>).NSAppTransportSecurity, undefined);
  assert.equal(config.android?.intentFilters?.[0]?.autoVerify, true);
  const http = build({ INKTROSPECT_APP_VARIANT: "store", INKTROSPECT_API_BASE: "http://api.inktrospect.se" });
  assert.deepEqual(parseRuntimeConfig((http.extra as { runtime: unknown }).runtime),
                   { ok: false, code: "config_api_base_not_https" });
});

test("development builds reach a LAN API and only they carry the development identity path", () => {
  const config = build({ INKTROSPECT_API_BASE: "http://192.168.1.20:8000" });
  const runtime = parseRuntimeConfig((config.extra as { runtime: unknown }).runtime);
  assert.ok(runtime.ok && runtime.config.devIdentity);
  assert.equal(config.scheme, "inktrospect-dev");
  assert.equal(config.name, "Inktrospect", "CNG derives the Xcode workspace name the native CI builds from this");
  const staging = build({ INKTROSPECT_APP_VARIANT: "staging", INKTROSPECT_API_BASE: "https://staging-api.inktrospect.se" });
  const stagingRuntime = parseRuntimeConfig((staging.extra as { runtime: unknown }).runtime);
  assert.ok(stagingRuntime.ok && !stagingRuntime.config.devIdentity);
  assert.throws(() => build({ INKTROSPECT_APP_VARIANT: "beta" }), /INKTROSPECT_APP_VARIANT/);
});

test("broad media and microphone permissions are blocked; the picker needs none", () => {
  const config = build({ INKTROSPECT_API_BASE: "http://127.0.0.1:8000" });
  for (const permission of ["android.permission.RECORD_AUDIO", "android.permission.READ_MEDIA_IMAGES",
                            "android.permission.READ_MEDIA_VIDEO"]) {
    assert.ok(config.android?.blockedPermissions?.includes(permission), permission);
  }
  // Camera capture on Android 7-9 needs the picker library's capped storage permission.
  assert.ok(!config.android?.blockedPermissions?.includes("android.permission.WRITE_EXTERNAL_STORAGE"));
  const picker = (config.plugins ?? []).find((p) => Array.isArray(p) && p[0] === "expo-image-picker") as [string, Record<string, unknown>];
  assert.equal(picker[1].microphonePermission, false);
  assert.equal(picker[1].photosPermission, false);
});

function buildProperties(config: ReturnType<typeof build>) {
  const entry = (config.plugins ?? []).find((p) => Array.isArray(p) && p[0] === "expo-build-properties") as
    [string, { android: Record<string, unknown>; ios: Record<string, unknown> }];
  return entry[1];
}

test("the development handoff build parses with local cleartext and development identity", () => {
  const config = build({ INKTROSPECT_APP_VARIANT: "development", INKTROSPECT_BACKEND_ENV: "local",
                         INKTROSPECT_API_BASE: "http://127.0.0.1:8000" });
  const runtime = parseRuntimeConfig((config.extra as { runtime: unknown }).runtime);
  assert.ok(runtime.ok, JSON.stringify(runtime));
  assert.equal(runtime.config.variant, "development");
  assert.equal(runtime.config.backendEnvironment, "local");
  assert.equal(runtime.config.apiBaseUrl, "http://127.0.0.1:8000");
  assert.equal(runtime.config.devIdentity, true);
  assert.equal(config.android?.package, "se.inktrospect.development");
  assert.equal(config.version, "0.1.0");
  const android = buildProperties(config).android;
  // A non-debuggable release-variant APK gets no debug-manifest cleartext override; it must come from here.
  assert.equal(android.usesCleartextTraffic, true);
  assert.deepEqual([android.minSdkVersion, android.compileSdkVersion, android.targetSdkVersion], [24, 36, 36]);
  const lan = parseRuntimeConfig((build({ INKTROSPECT_API_BASE: "http://192.168.1.20:8000" }).extra as
    { runtime: unknown }).runtime);
  assert.ok(lan.ok && lan.config.devIdentity);
});

test("staging and store builds keep Android cleartext off, require HTTPS and refuse development identity", () => {
  for (const [variant, id, backend, api] of [
    ["staging", "se.inktrospect.staging", "staging", "https://staging-api.inktrospect.se"],
    ["store", "se.inktrospect", "production", "https://api.inktrospect.se"],
  ] as const) {
    const config = build({ INKTROSPECT_APP_VARIANT: variant, INKTROSPECT_API_BASE: api });
    assert.equal(buildProperties(config).android.usesCleartextTraffic, false, variant);
    assert.equal(config.android?.package, id);
    assert.equal(config.ios?.bundleIdentifier, id);
    const runtime = (config.extra as { runtime: Record<string, unknown> }).runtime;
    assert.equal(runtime.devIdentity, false, variant);
    assert.equal(runtime.backendEnvironment, backend);
    const parsed = parseRuntimeConfig(runtime);
    assert.ok(parsed.ok && !parsed.config.devIdentity, variant);
    // A tampered binary that claims development identity is refused before any network call.
    assert.deepEqual(parseRuntimeConfig({ ...runtime, devIdentity: true }),
                     { ok: false, code: "config_dev_identity_not_allowed" });
    // Cleartext to a loopback/LAN API is refused for these variants, even with build-time cleartext off.
    for (const insecure of ["http://127.0.0.1:8000", "http://192.168.1.20:8000", api.replace("https:", "http:")]) {
      const http = build({ INKTROSPECT_APP_VARIANT: variant, INKTROSPECT_API_BASE: insecure });
      assert.deepEqual(parseRuntimeConfig((http.extra as { runtime: unknown }).runtime),
                       { ok: false, code: "config_api_base_not_https" }, `${variant} ${insecure}`);
    }
  }
});

test("remote synthetic guest APK is HTTPS-only and has no development login", () => {
  const config = build({
    INKTROSPECT_APP_VARIANT: "development",
    INKTROSPECT_BACKEND_ENV: "test",
    INKTROSPECT_API_BASE: "https://db-migrations-test.up.railway.app",
    INKTROSPECT_REMOTE_GUEST_ONLY: "1",
  });
  const runtime = parseRuntimeConfig((config.extra as { runtime: unknown }).runtime);
  assert.ok(runtime.ok, JSON.stringify(runtime));
  assert.equal(runtime.config.devIdentity, false);
  assert.equal(runtime.config.backendEnvironment, "test");
  assert.equal(runtime.config.apiBaseUrl, "https://db-migrations-test.up.railway.app");
  for (const [variant, backend, url] of [
    ["development", "test", "http://127.0.0.1:8000"],
    ["staging", "staging", "https://db-migrations-test.up.railway.app"],
    ["development", "local", "https://db-migrations-test.up.railway.app"],
  ]) {
    assert.throws(() => build({
      INKTROSPECT_APP_VARIANT: variant,
      INKTROSPECT_BACKEND_ENV: backend,
      INKTROSPECT_API_BASE: url,
      INKTROSPECT_REMOTE_GUEST_ONLY: "1",
    }), /INKTROSPECT_REMOTE_GUEST_ONLY/);
  }
});
