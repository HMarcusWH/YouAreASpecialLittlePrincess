import type { NativeAuthorizationRequest } from "../contracts.ts";

function parseUrl(raw: string, errorCode: string): URL {
  try {
    return new URL(raw);
  } catch {
    throw new Error(errorCode);
  }
}

export function validateNativeAuthorizationRequest(
  request: NativeAuthorizationRequest,
  allowedAuthorizationOrigins: ReadonlySet<string>,
  allowedRedirectSchemes: ReadonlySet<string>,
): { authorization: URL; redirect: URL } {
  const authorization = parseUrl(request.authorizationUrl, "identity_authorization_url_invalid");
  const redirect = parseUrl(request.redirectUrl, "identity_redirect_url_invalid");
  const redirectScheme = redirect.protocol.replace(/:$/, "");

  if (authorization.protocol !== "https:" || !allowedAuthorizationOrigins.has(authorization.origin)) {
    throw new Error("identity_authorization_origin_not_allowed");
  }
  if (!allowedRedirectSchemes.has(redirectScheme)) {
    throw new Error("identity_redirect_scheme_not_allowed");
  }
  if (redirect.username || redirect.password) {
    throw new Error("identity_redirect_credentials_not_allowed");
  }

  return { authorization, redirect };
}

export function validateNativeAuthorizationCallback(
  callbackUrl: string,
  requestedRedirectUrl: string,
  expectedState: string,
): URL {
  const callback = parseUrl(callbackUrl, "identity_callback_url_invalid");
  const redirect = parseUrl(requestedRedirectUrl, "identity_redirect_url_invalid");

  const sameTarget = callback.protocol === redirect.protocol
    && callback.host === redirect.host
    && callback.pathname === redirect.pathname
    && !callback.username
    && !callback.password;
  if (!sameTarget) {
    throw new Error("identity_callback_redirect_mismatch");
  }
  if (callback.searchParams.get("state") !== expectedState) {
    throw new Error("identity_state_mismatch");
  }

  return callback;
}
