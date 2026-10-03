// Incoming link resolution. Custom-scheme links and verified-domain HTTPS
// links (Universal Links / App Links) select a resource; the destination
// screen still fetches it with the current credential, so a link never
// authorizes anything and a forged or stale link opens an unavailable state.
import { parseUri, pathSegments } from "@princess/api-client";

import type { DeepLinkRouter, NativeRoute } from "./contracts.ts";

export class AllowlistedDeepLinkRouter implements DeepLinkRouter {
  private readonly allowedSchemes: ReadonlySet<string>;
  private readonly allowedHosts: ReadonlySet<string>;

  constructor(allowedSchemes: ReadonlySet<string>, allowedHosts: ReadonlySet<string> = new Set()) {
    this.allowedSchemes = allowedSchemes;
    this.allowedHosts = allowedHosts;
  }

  resolve(raw: string): NativeRoute | null {
    // Not the runtime URL class: React Native's accepts malformed input and loses custom-scheme hosts.
    const uri = parseUri(raw);
    if (uri === null || uri.userinfo !== null || uri.host === null) return null;
    const segments = pathSegments(uri);
    if (segments === null) return null;
    let parts: string[];
    if (uri.scheme === "https") {
      if (!this.allowedHosts.has(uri.host) || uri.port !== null) return null;
      parts = segments;
    } else if (this.allowedSchemes.has(uri.scheme) && uri.port === null) {
      parts = [uri.host, ...segments].filter(Boolean);
    } else {
      return null;
    }
    const [head, id, ...rest] = parts;
    if (rest.length > 0) return null;
    if (head === "reports" && id !== undefined && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(id)) {
      return { kind: "REPORT", reportId: id };
    }
    if ((head === "history" || head === "reports") && id === undefined) return { kind: "HISTORY" };
    if (head === "settings" && id === undefined) return { kind: "SETTINGS" };
    return null;
  }
}

/** Expo Router path for a resolved route ("/" for anything not allowlisted). */
export function pathFor(route: NativeRoute | null): string {
  if (route === null) return "/";
  if (route.kind === "REPORT") return `/reports/${encodeURIComponent(route.reportId)}`;
  if (route.kind === "HISTORY") return "/reports";
  return "/settings";
}
