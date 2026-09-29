import type {
  AbuseAttestationClient, CaptureClient, DeepLinkRouter, FileShareClient, LocalCapture, NativePurchaseClient,
  NativeAuthorizationRequest, NativeAuthorizationResult, NativeIdentityTransport, NativeRoute, PermissionState,
  PushRegistration, PurchaseObservation, SecureSessionStore, StoreProduct,
} from "./contracts.ts";

export class FakeSecureSessionStore implements SecureSessionStore {
  value: string | null = null;
  async read() { return this.value; }
  async write(credential: string) { this.value = credential; }
  async clear() { this.value = null; }
}

export class FakeCaptureClient implements CaptureClient {
  camera: PermissionState = "GRANTED";
  library: PermissionState = "GRANTED";
  next: LocalCapture | null = null;
  async cameraPermission() { return this.camera; }
  async libraryPermission() { return this.library; }
  async takePhoto() { return this.camera === "GRANTED" ? this.next : null; }
  async pickPhoto() { return this.library === "GRANTED" || this.library === "LIMITED" ? this.next : null; }
}

export class FakeNativePurchaseClient implements NativePurchaseClient {
  products = new Map<string, StoreProduct>();
  observations: PurchaseObservation[] = [];
  finished: string[] = [];
  nextState: PurchaseObservation["state"] = "STARTED";
  private readonly issuedProofs = new Set<string>();
  private readonly serverGrantedProofs = new Set<string>();

  async listProducts(productIds: readonly string[]) {
    return productIds.flatMap((id) => {
      const product = this.products.get(id);
      return product ? [product] : [];
    });
  }

  async beginPurchase(productId: string) {
    const proof = this.nextState === "PROOF_READY" ? "proof:" + productId : null;
    if (proof) this.issuedProofs.add(proof);
    const observation = { productId, state: this.nextState, proof } satisfies PurchaseObservation;
    this.observations.push(observation);
    return observation;
  }

  async recoverPendingTransactions() {
    return this.observations.filter((item) =>
      (item.state === "PENDING" || item.state === "PROOF_READY")
      && (item.proof === null || !this.finished.includes(item.proof)));
  }

  recordServerGrant(proof: string) {
    if (!this.issuedProofs.has(proof)) throw new Error("unknown_purchase_proof");
    this.serverGrantedProofs.add(proof);
  }

  async finishAfterServerGrant(proof: string) {
    if (!this.issuedProofs.has(proof)) throw new Error("unknown_purchase_proof");
    if (!this.serverGrantedProofs.has(proof)) throw new Error("server_grant_required");
    if (!this.finished.includes(proof)) this.finished.push(proof);
  }
}

export class AllowlistedDeepLinkRouter implements DeepLinkRouter {
  private readonly allowedSchemes: ReadonlySet<string>;

  constructor(allowedSchemes: ReadonlySet<string>) {
    this.allowedSchemes = allowedSchemes;
  }

  resolve(raw: string): NativeRoute | null {
    let url: URL;
    try { url = new URL(raw); } catch { return null; }
    const scheme = url.protocol.replace(/:$/, "");
    if (!this.allowedSchemes.has(scheme)) return null;
    const parts = url.pathname.split("/").filter(Boolean);
    if (url.hostname === "reports" && parts.length === 1 && parts[0]) return { kind: "REPORT", reportId: parts[0] };
    if ((url.hostname === "history" || parts[0] === "history") && parts.length <= 1) return { kind: "HISTORY" };
    if ((url.hostname === "settings" || parts[0] === "settings") && parts.length <= 1) return { kind: "SETTINGS" };
    return null;
  }
}

export class FakeFileShareClient implements FileShareClient {
  shared: string[] = [];
  cleaned: string[] = [];
  available = true;
  async shareAuthorizedFile(uri: string) {
    if (!this.available) return "UNAVAILABLE" as const;
    this.shared.push(uri);
    return "SHARED" as const;
  }
  async cleanup(uri: string) { this.cleaned.push(uri); }
}

export class FakePushRegistration implements PushRegistration {
  current: { installationId: string; token: string; principalId: string } | null = null;
  denied = false;
  async register(principalId: string) {
    if (this.denied) return null;
    this.current = { installationId: "installation_test", token: "push_test", principalId };
    return { installationId: this.current.installationId, token: this.current.token };
  }
  async clear() { this.current = null; }
}

export class FakeAbuseAttestation implements AbuseAttestationClient {
  status: "ACCEPTED" | "REJECTED" | "UNAVAILABLE" = "UNAVAILABLE";
  async attest(_operation: string, _nonce: string) {
    return { status: this.status, token: this.status === "ACCEPTED" ? "attestation_test" : null };
  }
}

export class FakeNativeIdentityTransport implements NativeIdentityTransport {
  requests: NativeAuthorizationRequest[] = [];
  next: NativeAuthorizationResult = { status: "CANCELLED", callbackUrl: null };

  async authorize(request: NativeAuthorizationRequest) {
    this.requests.push(request);
    return this.next;
  }
}
