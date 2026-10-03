// Deterministic fakes for every native port. They model refusals and lifecycle
// (denial, cancellation, pending purchases, grant-before-finish, cleanup) and
// never fabricate a capture, a grant or an authorization.
import { ApiError, sha256HexSync, type AuthorizedDownload, type UploadMediaType, type UploadTicket } from "@princess/api-client";

import type { LocalFiles } from "../work/capture-workflow.ts";
import type {
  AbuseAttestationClient, AuthorizedFileClient, CaptureClient, CaptureOutcome, CropRect,
  DevicePushClient, DevicePushToken, DownloadedFile, FileShareClient, ImagePreparer, KeyValueFile,
  NativeAuthorizationRequest, NativeAuthorizationResult, NativeIdentityTransport, NativePurchaseClient,
  NotificationOpen, PermissionState, PickedImage, PreparationResult, PurchaseObservation, SecureSessionStore,
  StoreProduct, WorkingImage,
} from "./contracts.ts";

export class FakeSecureSessionStore implements SecureSessionStore {
  value: string | null = null;
  async read() { return this.value; }
  async write(credential: string) { this.value = credential; }
  async clear() { this.value = null; }
}

export class FakeKeyValueFile implements KeyValueFile {
  readonly values = new Map<string, string>();
  failWrites = false;
  async read(name: string) { return this.values.get(name) ?? null; }
  async write(name: string, value: string) {
    if (this.failWrites) throw new Error("disk_full");
    this.values.set(name, value);
  }
  async remove(name: string) { this.values.delete(name); }
}

export class FakeCaptureClient implements CaptureClient {
  camera: PermissionState = "GRANTED";
  cancelNext = false;
  next: PickedImage | null = null;
  async cameraPermission() { return this.camera; }
  async takePhoto(): Promise<CaptureOutcome> {
    if (this.camera === "UNAVAILABLE") return { status: "UNAVAILABLE" };
    if (this.camera === "DENIED") return { status: "DENIED", canAskAgain: false };
    return this.result("CAMERA");
  }
  async pickPhoto(): Promise<CaptureOutcome> { return this.result("LIBRARY"); }
  private result(source: PickedImage["source"]): CaptureOutcome {
    if (this.cancelNext || this.next === null) return { status: "CANCELLED" };
    return { status: "SELECTED", image: { ...this.next, source } };
  }
}

/** In-memory private files: the bytes a URI names, so digests describe exactly what is uploaded. */
export class FakeLocalFiles implements LocalFiles {
  readonly files = new Map<string, Uint8Array>();
  readonly uploads: Array<{ uploadId: string; sha256: string; mediaType: string }> = [];
  readonly removed: string[] = [];
  /** Server-side effect of a PUT; may throw ApiError/TransportError to simulate failures. */
  onUpload: (ticket: UploadTicket, bytes: Uint8Array, mediaType: string) => Promise<void> = async () => undefined;

  add(uri: string, bytes: Uint8Array): string {
    this.files.set(uri, bytes);
    return uri;
  }

  async digest(uri: string) {
    const bytes = this.files.get(uri);
    return bytes === undefined ? null : { sha256: sha256HexSync(bytes), bytes: bytes.byteLength };
  }

  async upload(ticket: UploadTicket, uri: string, mediaType: UploadMediaType) {
    const bytes = this.files.get(uri);
    if (bytes === undefined) throw new ApiError(0, "local_file_missing");
    await this.onUpload(ticket, bytes, mediaType);
    this.uploads.push({ uploadId: ticket.upload_id, sha256: sha256HexSync(bytes), mediaType });
  }

  async remove(uri: string) {
    this.files.delete(uri);
    this.removed.push(uri);
  }
}

export class FakeImagePreparer implements ImagePreparer {
  readonly files = new Map<string, Uint8Array>();
  readonly discarded: string[] = [];
  private counter = 0;
  private readonly sink: FakeLocalFiles | undefined;

  constructor(sink?: FakeLocalFiles) {
    this.sink = sink;
  }

  private emit(width: number, height: number, source: WorkingImage["source"]): WorkingImage {
    this.counter += 1;
    const uri = `file:///private/work_${this.counter}.jpg`;
    const bytes = new TextEncoder().encode(`${uri}:${width}x${height}`);
    this.files.set(uri, bytes);
    this.sink?.add(uri, bytes);
    return { uri, width, height, mediaType: "image/jpeg", source };
  }

  async normalize(picked: PickedImage): Promise<PreparationResult> {
    if (picked.width < 32 || picked.height < 32) return { ok: false, code: "image_too_small" };
    return { ok: true, image: this.emit(picked.width, picked.height, picked.source) };
  }

  async rotate(image: WorkingImage, quarterTurns: 1 | 2 | 3): Promise<PreparationResult> {
    const swap = quarterTurns % 2 === 1;
    return { ok: true, image: this.emit(swap ? image.height : image.width, swap ? image.width : image.height,
                                        image.source) };
  }

  async finalize(image: WorkingImage, crop: CropRect | null): Promise<PreparationResult> {
    const width = crop?.width ?? image.width;
    const height = crop?.height ?? image.height;
    if (width < 32 || height < 32) return { ok: false, code: "image_too_small" };
    return { ok: true, image: this.emit(width, height, image.source) };
  }

  async discard(uri: string) {
    this.files.delete(uri);
    this.discarded.push(uri);
  }

  async sweep(keep: ReadonlySet<string>) {
    let removed = 0;
    for (const uri of [...this.files.keys()]) {
      if (!keep.has(uri)) {
        await this.discard(uri);
        removed += 1;
      }
    }
    return removed;
  }
}

export class FakeAuthorizedFiles implements AuthorizedFileClient {
  readonly requests: AuthorizedDownload[] = [];
  readonly removed: string[] = [];
  next: DownloadedFile | Error = { uri: "file:///private/export.pdf", bytes: 1024, mediaType: "application/pdf" };

  async download(request: AuthorizedDownload, _name: string,
                 limits: { readonly maxBytes: number; readonly mediaTypes: readonly string[] }) {
    this.requests.push(request);
    if (this.next instanceof Error) throw this.next;
    if (this.next.bytes > limits.maxBytes || !limits.mediaTypes.includes(this.next.mediaType)) {
      throw new ApiError(502, "download_out_of_bounds");
    }
    return this.next;
  }

  async remove(uri: string) { this.removed.push(uri); }
  async sweep() { return 0; }
}

export class FakeFileShareClient implements FileShareClient {
  shared: string[] = [];
  cleaned: string[] = [];
  available = true;
  cancel = false;
  async shareAuthorizedFile(uri: string, _mediaType: string) {
    if (!this.available) return "UNAVAILABLE" as const;
    if (this.cancel) return "CANCELLED" as const;
    this.shared.push(uri);
    return "SHARED" as const;
  }
  async cleanup(uri: string) { this.cleaned.push(uri); }
}

/**
 * A store that issues proofs and only lets the app finish a transaction after
 * the test records the server's durable grant. It never grants credit itself.
 */
export class FakeNativePurchaseClient implements NativePurchaseClient {
  readonly rail: "apple_app_store" | "google_play";
  products = new Map<string, StoreProduct>();
  connected = false;
  available = true;
  nextState: PurchaseObservation["state"] = "PROOF_READY";
  readonly accountTokens: string[] = [];
  readonly observations: PurchaseObservation[] = [];
  readonly finished: string[] = [];
  private counter = 0;
  private readonly listeners = new Set<(observation: PurchaseObservation) => void>();
  private readonly serverGranted = new Set<string>();

  constructor(rail: "apple_app_store" | "google_play" = "apple_app_store") {
    this.rail = rail;
  }

  async connect() {
    this.connected = this.available;
    return this.connected;
  }

  async listProducts(productIds: readonly string[]) {
    return productIds.flatMap((id) => {
      const product = this.products.get(id);
      return product ? [product] : [];
    });
  }

  async beginPurchase(productId: string, accountToken: string): Promise<PurchaseObservation> {
    if (!this.connected) return { productId, state: "UNAVAILABLE", proof: null, transactionId: null, errorCode: "not_connected" };
    this.accountTokens.push(accountToken);
    this.counter += 1;
    const transactionId = `txn_${this.counter}`;
    const ready = this.nextState === "PROOF_READY";
    const observation: PurchaseObservation = {
      productId, state: this.nextState, proof: ready ? `proof:${productId}:${transactionId}` : null,
      transactionId: ready || this.nextState === "PENDING" ? transactionId : null,
      errorCode: this.nextState === "FAILED" ? "purchase_error" : null,
    };
    this.observations.push(observation);
    return observation;
  }

  /** Simulates a delivered update (Ask to Buy approval, pending payment completion, startup replay). */
  deliver(observation: PurchaseObservation) {
    this.observations.push(observation);
    for (const listener of this.listeners) listener(observation);
  }

  subscribe(listener: (observation: PurchaseObservation) => void) {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  async recoverPendingTransactions() {
    return this.observations.filter((o) => o.state === "PROOF_READY" && o.proof !== null
      && !this.finished.includes(o.proof));
  }

  recordServerGrant(proof: string) {
    if (!this.observations.some((o) => o.proof === proof)) throw new Error("unknown_purchase_proof");
    this.serverGranted.add(proof);
  }

  async finishAfterServerGrant(observation: PurchaseObservation) {
    const proof = observation.proof;
    if (proof === null || !this.observations.some((o) => o.proof === proof)) throw new Error("unknown_purchase_proof");
    if (!this.serverGranted.has(proof)) throw new Error("server_grant_required");
    if (!this.finished.includes(proof)) this.finished.push(proof);
  }

  async disconnect() { this.connected = false; }
}

export class FakeDevicePushClient implements DevicePushClient {
  state: PermissionState = "GRANTED";
  token: DevicePushToken | null = { token: "fcm-device-token-0001", platform: "fcm" };
  launch: NotificationOpen | null = null;
  private readonly tokenListeners = new Set<(token: DevicePushToken) => void>();
  private readonly openListeners = new Set<(open: NotificationOpen) => void>();

  async permission() { return this.state; }
  async requestToken() { return this.state === "GRANTED" ? this.token : null; }
  onTokenChanged(listener: (token: DevicePushToken) => void) {
    this.tokenListeners.add(listener);
    return () => { this.tokenListeners.delete(listener); };
  }
  onOpen(listener: (open: NotificationOpen) => void) {
    this.openListeners.add(listener);
    return () => { this.openListeners.delete(listener); };
  }
  async launchOpen() { return this.launch; }
  rotate(token: DevicePushToken) {
    this.token = token;
    for (const listener of this.tokenListeners) listener(token);
  }
  open(event: NotificationOpen) {
    for (const listener of this.openListeners) listener(event);
  }
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
