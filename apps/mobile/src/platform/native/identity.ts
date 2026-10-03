import * as WebBrowser from "expo-web-browser";

import type {
  NativeAuthorizationRequest, NativeAuthorizationResult, NativeIdentityTransport,
} from "../contracts.ts";
import {
  validateNativeAuthorizationCallback,
  validateNativeAuthorizationRequest,
} from "./identity-policy.ts";

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
    validateNativeAuthorizationRequest(
      request,
      this.allowedAuthorizationOrigins,
      this.allowedRedirectSchemes,
    );

    const result = await WebBrowser.openAuthSessionAsync(request.authorizationUrl, request.redirectUrl);
    if (result.type !== "success" || !("url" in result) || !result.url) {
      if (result.type === "cancel") return { status: "CANCELLED", callbackUrl: null };
      if (result.type === "dismiss") return { status: "DISMISSED", callbackUrl: null };
      return { status: "FAILED", callbackUrl: null };
    }

    validateNativeAuthorizationCallback(result.url, request.redirectUrl, request.expectedState);
    return { status: "SUCCESS", callbackUrl: result.url };
  }
}
