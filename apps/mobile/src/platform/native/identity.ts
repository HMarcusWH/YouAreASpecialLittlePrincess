import * as WebBrowser from "expo-web-browser";

import type {
  NativeAuthorizationRequest, NativeAuthorizationResult, NativeIdentityTransport,
} from "../contracts.ts";

export class ExpoExternalUserAgentIdentityTransport implements NativeIdentityTransport {
  private readonly allowedAuthorizationOrigins: ReadonlySet<string>;
  private readonly allowedRedirectSchemes: ReadonlySet<string>;

  constructor(
    allowedAuthorizationOrigins: ReadonlySet<string>,
    allowedRedirectSchemes: ReadonlySet<string>,
  ) {
    this.allowedAuthorizationOrigins = allowedAuthorizationOrigins;
    this.allowedRedirectSchemes = allowedRedirectSchemes;
  }

  async authorize(request: NativeAuthorizationRequest): Promise<NativeAuthorizationResult> {
    const authorization = new URL(request.authorizationUrl);
    const redirect = new URL(request.redirectUrl);
    const redirectScheme = redirect.protocol.replace(/:$/, "");

    if (authorization.protocol !== "https:" || !this.allowedAuthorizationOrigins.has(authorization.origin)) {
      throw new Error("identity_authorization_origin_not_allowed");
    }
    if (!this.allowedRedirectSchemes.has(redirectScheme)) {
      throw new Error("identity_redirect_scheme_not_allowed");
    }

    const result = await WebBrowser.openAuthSessionAsync(request.authorizationUrl, request.redirectUrl);
    if (result.type !== "success" || !("url" in result) || !result.url) {
      if (result.type === "cancel") return { status: "CANCELLED", callbackUrl: null };
      if (result.type === "dismiss") return { status: "DISMISSED", callbackUrl: null };
      return { status: "FAILED", callbackUrl: null };
    }

    const callback = new URL(result.url);
    if (callback.protocol.replace(/:$/, "") !== redirectScheme) {
      throw new Error("identity_callback_scheme_mismatch");
    }
    if (callback.searchParams.get("state") !== request.expectedState) {
      throw new Error("identity_state_mismatch");
    }
    return { status: "SUCCESS", callbackUrl: result.url };
  }
}
