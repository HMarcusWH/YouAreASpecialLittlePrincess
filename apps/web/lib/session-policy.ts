// Pure policy for the web's opaque provider/application credential cookie.
// Provider verification stays in FastAPI's IdentityProvider adapter; this
// module owns browser transport attributes only.
export const SESSION_COOKIE = "princess_session";
export const SESSION_MAX_AGE_S = 60 * 60 * 24 * 30;

export type WebEnvironment = "local" | "test" | "preview" | "staging" | "production";

const WEB_ENVIRONMENTS = new Set<WebEnvironment>([
  "local", "test", "preview", "staging", "production",
]);

export function webEnvironment(raw: string | undefined): WebEnvironment {
  const value = raw ?? "local";
  if (!WEB_ENVIRONMENTS.has(value as WebEnvironment)) throw new Error("invalid_web_environment");
  return value as WebEnvironment;
}

export function devCredentialIssuanceEnabled(environment: WebEnvironment): boolean {
  return environment === "local" || environment === "test";
}

function cookieSecurity(environment: WebEnvironment) {
  return {
    httpOnly: true as const,
    sameSite: "lax" as const,
    path: "/" as const,
    secure: environment !== "local" && environment !== "test",
  };
}

export function credentialCookie(credential: string, environment: WebEnvironment) {
  if (!credential) throw new Error("empty_session_credential");
  return {
    name: SESSION_COOKIE,
    value: credential,
    ...cookieSecurity(environment),
    maxAge: SESSION_MAX_AGE_S,
  };
}

export function clearedCredentialCookie(environment: WebEnvironment) {
  return {
    name: SESSION_COOKIE,
    value: "",
    ...cookieSecurity(environment),
    maxAge: 0,
  };
}
