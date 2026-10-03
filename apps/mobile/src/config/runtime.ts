// Build-time runtime configuration, validated before anything talks to a
// server. A store build must point at HTTPS, must not carry development
// identity helpers and must name a non-development backend; a development
// build must name a device-reachable API (a phone cannot reach the build
// machine's loopback address unless it is a simulator/emulator alias).
import { isPrivateDevelopmentHost as isPrivateHost, originOf, parseUri } from "@princess/api-client";

export type AppVariant = "development" | "staging" | "store";
export type BackendEnvironment = "local" | "test" | "preview" | "staging" | "production";

export interface RuntimeConfig {
  readonly variant: AppVariant;
  readonly backendEnvironment: BackendEnvironment;
  readonly apiBaseUrl: string;
  /** Origins the client may PUT upload bytes to (server-issued URLs elsewhere are refused). */
  readonly uploadOrigins: ReadonlySet<string>;
  /** Development sign-in through the fake identity provider; local/test development builds only. */
  readonly devIdentity: boolean;
  /** Deep-link schemes this build answers to. */
  readonly linkSchemes: ReadonlySet<string>;
  readonly linkHosts: ReadonlySet<string>;
}

export type ConfigResult = { readonly ok: true; readonly config: RuntimeConfig }
  | { readonly ok: false; readonly code: string };

const VARIANTS = new Set<AppVariant>(["development", "staging", "store"]);
const BACKENDS = new Set<BackendEnvironment>(["local", "test", "preview", "staging", "production"]);

function origin(raw: string): { readonly origin: string; readonly base: string; readonly secure: boolean;
                                  readonly host: string } | null {
  const uri = parseUri(raw);
  if (uri === null || (uri.scheme !== "https" && uri.scheme !== "http") || uri.userinfo !== null
      || uri.query !== null || uri.fragment !== null) return null;
  const root = originOf(uri);
  if (root === null) return null;
  return { origin: root, base: `${root}${uri.path.replace(/\/+$/, "")}`, secure: uri.scheme === "https", host: uri.host! };
}

/** Parse ``expoConfig.extra.runtime`` (set by app.config.ts from build environment variables). */
export function parseRuntimeConfig(raw: unknown): ConfigResult {
  const value = (typeof raw === "object" && raw !== null ? raw : {}) as Record<string, unknown>;
  const variant = value.variant as AppVariant;
  if (!VARIANTS.has(variant)) return { ok: false, code: "config_variant_invalid" };
  const backend = value.backendEnvironment as BackendEnvironment;
  if (!BACKENDS.has(backend)) return { ok: false, code: "config_backend_invalid" };
  if (typeof value.apiBaseUrl !== "string" || value.apiBaseUrl.length === 0) {
    return { ok: false, code: "config_api_base_missing" };
  }
  const api = origin(value.apiBaseUrl);
  if (api === null) return { ok: false, code: "config_api_base_invalid" };
  const secure = api.secure;
  if (variant !== "development" && !secure) return { ok: false, code: "config_api_base_not_https" };
  if (variant === "development" && !secure && !isPrivateHost(api.host)) {
    return { ok: false, code: "config_api_base_not_https" };
  }
  if (variant === "store" && backend !== "production") return { ok: false, code: "config_store_backend_invalid" };
  if (variant === "staging" && backend !== "staging") return { ok: false, code: "config_staging_backend_invalid" };
  if (variant === "development" && (backend === "staging" || backend === "production")) {
    return { ok: false, code: "config_development_backend_invalid" };
  }

  const uploadOrigins = new Set<string>([api.origin]);
  const extra = Array.isArray(value.uploadOrigins) ? value.uploadOrigins : [];
  for (const candidate of extra) {
    const url = typeof candidate === "string" ? origin(candidate) : null;
    if (url === null || (!url.secure && (variant !== "development" || !isPrivateHost(url.host)))) {
      return { ok: false, code: "config_upload_origin_invalid" };
    }
    uploadOrigins.add(url.origin);
  }

  const devIdentity = value.devIdentity === true;
  if (devIdentity && (variant !== "development" || (backend !== "local" && backend !== "test"))) {
    // A release or staging binary never contains a path to mint development credentials.
    return { ok: false, code: "config_dev_identity_not_allowed" };
  }
  const schemes = Array.isArray(value.linkSchemes) ? value.linkSchemes.filter((s): s is string =>
    typeof s === "string" && /^[a-z][a-z0-9+.-]{1,40}$/.test(s)) : [];
  const hosts = Array.isArray(value.linkHosts) ? value.linkHosts.filter((h): h is string =>
    typeof h === "string" && /^[a-z0-9.-]{3,253}$/.test(h)) : [];
  return {
    ok: true,
    config: {
      variant, backendEnvironment: backend, apiBaseUrl: api.base, uploadOrigins,
      devIdentity, linkSchemes: new Set(schemes), linkHosts: new Set(hosts),
    },
  };
}

/** The push registration environment name the API expects for this build. */
export function pushEnvironment(config: RuntimeConfig): string {
  return config.backendEnvironment;
}
