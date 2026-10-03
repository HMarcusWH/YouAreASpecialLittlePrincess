// Incoming link resolution. Custom-scheme links and verified-domain HTTPS
// links (Universal Links / App Links) select a resource; the destination
// screen still fetches it with the current credential, so a link never
// authorizes anything and a forged or stale link opens an unavailable state.
import type { DeepLinkRouter, NativeRoute } from "./contracts.ts";

export class AllowlistedDeepLinkRouter implements DeepLinkRouter {
  private readonly allowedSchemes: ReadonlySet<string>;
  private readonly allowedHosts: ReadonlySet<string>;

  constructor(allowedSchemes: ReadonlySet<string>, allowedHosts: ReadonlySet<string> = new Set()) {
    this.allowedSchemes = allowedSchemes;
    this.allowedHosts = allowedHosts;
  }

  resolve(raw: string): NativeRoute | null {
    let url: URL;
    try { url = new URL(raw); } catch { return null; }
    if (url.username || url.password) return null;
    const scheme = url.protocol.replace(/:$/, "");
    let parts: string[];
    if (scheme === "https") {
      if (!this.allowedHosts.has(url.hostname) || url.port) return null;
      parts = url.pathname.split("/").filter(Boolean);
    } else if (this.allowedSchemes.has(scheme)) {
      parts = [url.hostname, ...url.pathname.split("/").filter(Boolean)].filter(Boolean);
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
