// Validation of external-user-agent authorization requests and callbacks.
// Uses the shared strict parser, not the runtime URL class: React Native's URL
// reports an empty host and "/" path for custom schemes, which would make any
// callback on the app scheme look like the requested redirect.
import { originOf, parseUri, queryParam, type ParsedUri } from "@princess/api-client";

import type { NativeAuthorizationRequest } from "../contracts.ts";

function parse(raw: string, errorCode: string): ParsedUri {
  const uri = parseUri(raw);
  if (uri === null) throw new Error(errorCode);
  return uri;
}

export function validateNativeAuthorizationRequest(
  request: NativeAuthorizationRequest,
  allowedAuthorizationOrigins: ReadonlySet<string>,
  allowedRedirectSchemes: ReadonlySet<string>,
): { authorization: ParsedUri; redirect: ParsedUri } {
  const authorization = parse(request.authorizationUrl, "identity_authorization_url_invalid");
  const redirect = parse(request.redirectUrl, "identity_redirect_url_invalid");
  const origin = originOf(authorization);

  if (authorization.scheme !== "https" || authorization.userinfo !== null || origin === null
      || !allowedAuthorizationOrigins.has(origin)) {
    throw new Error("identity_authorization_origin_not_allowed");
  }
  if (!allowedRedirectSchemes.has(redirect.scheme)) {
    throw new Error("identity_redirect_scheme_not_allowed");
  }
  if (redirect.userinfo !== null) {
    throw new Error("identity_redirect_credentials_not_allowed");
  }

  return { authorization, redirect };
}

export function validateNativeAuthorizationCallback(
  callbackUrl: string,
  requestedRedirectUrl: string,
  expectedState: string,
): ParsedUri {
  const callback = parse(callbackUrl, "identity_callback_url_invalid");
  const redirect = parse(requestedRedirectUrl, "identity_redirect_url_invalid");

  const sameTarget = callback.scheme === redirect.scheme
    && callback.host === redirect.host
    && callback.port === redirect.port
    && callback.path === redirect.path
    && callback.userinfo === null;
  if (!sameTarget) {
    throw new Error("identity_callback_redirect_mismatch");
  }
  if (queryParam(callback, "state") !== expectedState) {
    throw new Error("identity_state_mismatch");
  }

  return callback;
}
