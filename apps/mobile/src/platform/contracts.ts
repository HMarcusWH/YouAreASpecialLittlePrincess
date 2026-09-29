export type PermissionState = "GRANTED" | "DENIED" | "LIMITED" | "UNAVAILABLE";

export type LocalCapture = {
  localUri: string;
  width: number;
  height: number;
  mimeType: "image/jpeg" | "image/png";
  source: "CAMERA" | "LIBRARY";
  originalMimeType: string | null;
  fileName: string | null;
  orientationMetadata: "PRESENT" | "ABSENT" | "UNKNOWN";
};

export interface CaptureClient {
  cameraPermission(): Promise<PermissionState>;
  libraryPermission(): Promise<PermissionState>;
  takePhoto(): Promise<LocalCapture | null>;
  pickPhoto(): Promise<LocalCapture | null>;
}

export interface SecureSessionStore {
  read(): Promise<string | null>;
  write(credential: string): Promise<void>;
  clear(): Promise<void>;
}

export type StoreProduct = { productId: string; displayPrice: string };
export type PurchaseState = "STARTED" | "PENDING" | "CANCELLED" | "FAILED" | "PROOF_READY";
export type PurchaseObservation = { productId: string; state: PurchaseState; proof: string | null };

export interface NativePurchaseClient {
  listProducts(productIds: readonly string[]): Promise<StoreProduct[]>;
  beginPurchase(productId: string): Promise<PurchaseObservation>;
  recoverPendingTransactions(): Promise<PurchaseObservation[]>;
  finishAfterServerGrant(proof: string): Promise<void>;
}

export type NativeRoute =
  | { kind: "REPORT"; reportId: string }
  | { kind: "HISTORY" }
  | { kind: "SETTINGS" };

export interface DeepLinkRouter {
  resolve(url: string): NativeRoute | null;
}

export interface FileShareClient {
  shareAuthorizedFile(uri: string): Promise<"SHARED" | "CANCELLED" | "UNAVAILABLE">;
  cleanup(uri: string): Promise<void>;
}

export interface PushRegistration {
  register(principalId: string): Promise<{ installationId: string; token: string } | null>;
  clear(): Promise<void>;
}

export interface AbuseAttestationClient {
  attest(operation: string, nonce: string): Promise<{ status: "ACCEPTED" | "REJECTED" | "UNAVAILABLE"; token: string | null }>;
}

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
