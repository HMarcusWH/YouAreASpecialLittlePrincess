// Native platform ports. Every port has a fake (fakes.ts) so controllers and
// journeys are testable without a device, a store account or a provider.
// None of these ports measures handwriting, mints credits or authorizes access.
import type { AuthorizedDownload, UploadMediaType } from "@princess/api-client";

export type PermissionState = "GRANTED" | "DENIED" | "LIMITED" | "UNAVAILABLE";

// --- capture and image preparation --------------------------------------------------

export interface PickedImage {
  readonly uri: string;
  readonly width: number;
  readonly height: number;
  readonly mimeType: string | null;
  readonly fileName: string | null;
  readonly fileSize: number | null;
  readonly source: "CAMERA" | "LIBRARY";
}

export type CaptureOutcome =
  | { readonly status: "SELECTED"; readonly image: PickedImage }
  | { readonly status: "CANCELLED" }
  | { readonly status: "DENIED"; readonly canAskAgain: boolean }
  | { readonly status: "UNAVAILABLE" }
  | { readonly status: "FAILED"; readonly code: string };

export interface CaptureClient {
  cameraPermission(): Promise<PermissionState>;
  /** Requests camera permission only at the moment of capture. */
  takePhoto(): Promise<CaptureOutcome>;
  /** System photo picker: no broad media-library permission is requested. */
  pickPhoto(): Promise<CaptureOutcome>;
}

/** An app-private working image the user is reviewing (already oriented upright). */
export interface WorkingImage {
  readonly uri: string;
  readonly width: number;
  readonly height: number;
  readonly mediaType: UploadMediaType;
  readonly source: "CAMERA" | "LIBRARY";
}

/** Crop in the working image's pixel frame. A crop edge is not a page boundary. */
export interface CropRect {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

export type PreparationResult =
  | { readonly ok: true; readonly image: WorkingImage }
  | { readonly ok: false; readonly code: "image_too_small" | "image_too_large" | "image_unreadable" };

export interface ImagePreparer {
  /** Decode, orient upright and re-encode into app-private storage; no metadata is kept. */
  normalize(picked: PickedImage): Promise<PreparationResult>;
  rotate(image: WorkingImage, quarterTurns: 1 | 2 | 3): Promise<PreparationResult>;
  /** Final derivative: optional crop, pixel/byte bounds, re-encode. These bytes are hashed and uploaded. */
  finalize(image: WorkingImage, crop: CropRect | null): Promise<PreparationResult>;
  discard(uri: string): Promise<void>;
  /** Remove private working files older than ``maxAgeMs`` that ``keep`` does not reference. */
  sweep(keep: ReadonlySet<string>, maxAgeMs: number): Promise<number>;
}

// --- storage --------------------------------------------------------------------------

export interface SecureSessionStore {
  read(): Promise<string | null>;
  write(credential: string): Promise<void>;
  clear(): Promise<void>;
}

/** Small JSON documents in app-private storage (journal, preferences, installation IDs). */
export interface KeyValueFile {
  read(name: string): Promise<string | null>;
  write(name: string, value: string): Promise<void>;
  remove(name: string): Promise<void>;
}

// --- authorized files and sharing ----------------------------------------------------

export interface DownloadedFile {
  readonly uri: string;
  readonly bytes: number;
  readonly mediaType: string;
}

export interface AuthorizedFileClient {
  /** Bounded bearer download of an API file into private temporary storage. */
  download(request: AuthorizedDownload, name: string,
           limits: { readonly maxBytes: number; readonly mediaTypes: readonly string[] }): Promise<DownloadedFile>;
  remove(uri: string): Promise<void>;
  /** Remove expired temporary downloads. */
  sweep(maxAgeMs: number): Promise<number>;
}

export interface FileShareClient {
  /** Opens the native share sheet. A completed sheet does not prove publication. */
  shareAuthorizedFile(uri: string, mediaType: string): Promise<"SHARED" | "CANCELLED" | "UNAVAILABLE">;
  cleanup(uri: string): Promise<void>;
}

// --- store purchases ----------------------------------------------------------------------

export type StoreProduct = { readonly productId: string; readonly displayPrice: string; readonly title: string };

export type PurchaseState = "PENDING" | "CANCELLED" | "FAILED" | "PROOF_READY" | "UNAVAILABLE";

export interface PurchaseObservation {
  readonly productId: string;
  readonly state: PurchaseState;
  /** Store proof for the server (Apple signed transaction / Play purchase token). Never logged. */
  readonly proof: string | null;
  readonly transactionId: string | null;
  readonly errorCode: string | null;
}

export interface NativePurchaseClient {
  readonly rail: "apple_app_store" | "google_play";
  connect(): Promise<boolean>;
  listProducts(productIds: readonly string[]): Promise<StoreProduct[]>;
  /** ``accountToken`` binds the store transaction to the application account. */
  beginPurchase(productId: string, accountToken: string): Promise<PurchaseObservation>;
  /** Transaction updates delivered outside a purchase call (startup, Ask to Buy, pending completion). */
  subscribe(listener: (observation: PurchaseObservation) => void): () => void;
  recoverPendingTransactions(): Promise<PurchaseObservation[]>;
  /** Only after the server recorded a durable grant (or reported it already granted). */
  finishAfterServerGrant(observation: PurchaseObservation): Promise<void>;
  disconnect(): Promise<void>;
}

// --- links and notifications ------------------------------------------------------------------

export type NativeRoute =
  | { kind: "REPORT"; reportId: string }
  | { kind: "HISTORY" }
  | { kind: "SETTINGS" };

export interface DeepLinkRouter {
  resolve(url: string): NativeRoute | null;
}

export interface DevicePushToken {
  readonly token: string;
  readonly platform: "apns" | "fcm";
}

/** Opaque notification content: a type and an object reference, never results or private URLs. */
export interface NotificationOpen {
  readonly type: string;
  readonly reference: string | null;
}

export interface DevicePushClient {
  permission(): Promise<PermissionState>;
  /** Asks for permission (contextually) and returns the device token, or null when denied/unavailable. */
  requestToken(): Promise<DevicePushToken | null>;
  onTokenChanged(listener: (token: DevicePushToken) => void): () => void;
  onOpen(listener: (open: NotificationOpen) => void): () => void;
  /** The notification that cold-launched the app, if any. */
  launchOpen(): Promise<NotificationOpen | null>;
}

export interface AbuseAttestationClient {
  attest(operation: string, nonce: string): Promise<{ status: "ACCEPTED" | "REJECTED" | "UNAVAILABLE"; token: string | null }>;
}

// --- identity transport ------------------------------------------------------------------------

export type NativeAuthorizationRequest = {
  authorizationUrl: string;
  redirectUrl: string;
  expectedState: string;
};

export type NativeAuthorizationResult =
  | { status: "SUCCESS"; callbackUrl: string }
  | { status: "CANCELLED" | "DISMISSED" | "FAILED"; callbackUrl: null };

export interface NativeIdentityTransport {
  authorize(request: NativeAuthorizationRequest): Promise<NativeAuthorizationResult>;
}
