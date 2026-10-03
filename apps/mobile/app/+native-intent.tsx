// Every incoming system URL (custom scheme, Universal Link, App Link) passes
// through the allowlist before routing. Anything else opens the start screen.
// A resolved link only selects a screen; that screen fetches with the current
// credential, so a forged, stale or other-account link shows "unavailable".
import { loadConfig } from "../src/bootstrap/native.ts";
import { AllowlistedDeepLinkRouter, pathFor } from "../src/platform/links.ts";

export function redirectSystemPath({ path }: { path: string; initial: boolean }): string {
  const config = loadConfig();
  if (!config.ok) return "/";
  const router = new AllowlistedDeepLinkRouter(config.config.linkSchemes, config.config.linkHosts);
  // Expo Router hands over either a full URL or an app-relative path.
  if (/^[a-z][a-z0-9+.-]*:/i.test(path)) return pathFor(router.resolve(path));
  const scheme = [...config.config.linkSchemes][0];
  return scheme ? pathFor(router.resolve(`${scheme}://${path.replace(/^\/+/, "")}`)) : "/";
}
