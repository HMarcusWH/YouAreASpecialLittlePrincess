// A strict RFC 3986 reference parser that does not depend on the runtime's
// URL class. React Native's global URL is a regex approximation: it accepts
// malformed input and reports an empty host and "/" path for non-HTTP schemes,
// so security decisions (upload origins, deep links, auth callbacks, build
// configuration) must not rely on it. Anything unusual is rejected.

export interface ParsedUri {
  /** Lower-case scheme without the colon. */
  readonly scheme: string;
  readonly userinfo: string | null;
  /** Lower-case host; ``null`` when the reference has no authority; "" for an empty authority. */
  readonly host: string | null;
  readonly port: number | null;
  readonly path: string;
  readonly query: string | null;
  readonly fragment: string | null;
}

const REFERENCE = /^([A-Za-z][A-Za-z0-9+.-]*):(?:\/\/([^/?#]*))?([^?#]*)(?:\?([^#]*))?(?:#(.*))?$/;
const AUTHORITY = /^(?:([^@]*)@)?(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]*)(?::(\d{1,5}))?$/;
const DEFAULT_PORTS: Readonly<Record<string, number>> = { http: 80, https: 443 };

export function parseUri(raw: string): ParsedUri | null {
  if (typeof raw !== "string" || raw.length === 0 || raw.length > 4096 || /[\s\u0000-\u001f\u007f\\]/.test(raw)) {
    return null;
  }
  const match = REFERENCE.exec(raw);
  if (!match) return null;
  const [, scheme, authority, path = "", query, fragment] = match;
  let userinfo: string | null = null;
  let host: string | null = null;
  let port: number | null = null;
  if (authority !== undefined) {
    const parts = AUTHORITY.exec(authority);
    if (!parts) return null;
    userinfo = parts[1] ?? null;
    host = (parts[2] ?? "").toLowerCase();
    if (host.startsWith(".") || host.endsWith(".") || host.includes("..")) return null;
    if (parts[3] !== undefined) {
      port = Number(parts[3]);
      if (port > 65535) return null;
    }
  }
  const lowerScheme = scheme!.toLowerCase();
  if (port !== null && DEFAULT_PORTS[lowerScheme] === port) port = null;
  return { scheme: lowerScheme, userinfo, host, port, path, query: query ?? null, fragment: fragment ?? null };
}

/** ``scheme://host[:port]`` for an authority-based reference, else null. */
export function originOf(uri: ParsedUri): string | null {
  if (uri.host === null || uri.host === "") return null;
  return `${uri.scheme}://${uri.host}${uri.port === null ? "" : `:${uri.port}`}`;
}

/** Decoded path segments; null when any segment is not valid percent-encoding. */
export function pathSegments(uri: ParsedUri): string[] | null {
  try {
    return uri.path.split("/").filter((segment) => segment.length > 0).map((segment) => decodeURIComponent(segment));
  } catch {
    return null;
  }
}

/** The first value of a query parameter (application/x-www-form-urlencoded). */
export function queryParam(uri: ParsedUri, name: string): string | null {
  if (uri.query === null) return null;
  for (const pair of uri.query.split("&")) {
    const index = pair.indexOf("=");
    const key = index < 0 ? pair : pair.slice(0, index);
    try {
      if (decodeURIComponent(key.replace(/\+/g, " ")) === name) {
        return index < 0 ? "" : decodeURIComponent(pair.slice(index + 1).replace(/\+/g, " "));
      }
    } catch {
      return null;
    }
  }
  return null;
}

export function isPrivateDevelopmentHost(host: string): boolean {
  return host === "localhost" || host === "127.0.0.1" || host === "[::1]" || host === "10.0.2.2"
    || /^10\.\d+\.\d+\.\d+$/.test(host) || /^192\.168\.\d+\.\d+$/.test(host)
    || /^172\.(1[6-9]|2\d|3[01])\.\d+\.\d+$/.test(host) || host.endsWith(".local");
}
