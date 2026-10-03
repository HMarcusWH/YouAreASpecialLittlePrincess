// StoreKit 2 / Play Billing through expo-iap. This adapter only observes the
// store: it never grants credit and never finishes a transaction before the
// server has durably granted it.
//
// * Apple: the transaction's signed JWS is the proof; the app finishes the
//   consumable only after the server answered granted/already_granted, so an
//   unfinished transaction is redelivered by StoreKit after a crash.
// * Google: the purchase token is the proof; the server consumes eligible
//   consumables after its grant (docs/roadmap/14), so the client never
//   consumes or acknowledges and does not compete with server completion.
//
// Real behaviour (Ask to Buy, pending payments, sandbox proof formats) needs
// signed-device sandbox qualification; nothing here is evidence of that.
import {
  ErrorCode, endConnection, fetchProducts, finishTransaction, getAvailablePurchases, initConnection,
  purchaseErrorListener, purchaseUpdatedListener, requestPurchase, type Purchase, type PurchaseError,
} from "expo-iap";

import type { NativePurchaseClient, PurchaseObservation, StoreProduct } from "../contracts.ts";

const OUTCOME_WAIT_MS = 120_000;

function observe(purchase: Purchase): PurchaseObservation {
  const proof = typeof purchase.purchaseToken === "string" && purchase.purchaseToken.length > 0
    ? purchase.purchaseToken : null;
  const transactionId = ("transactionId" in purchase && purchase.transactionId) || purchase.id || null;
  if (purchase.purchaseState === "purchased" && proof !== null) {
    return { productId: purchase.productId, state: "PROOF_READY", proof, transactionId, errorCode: null };
  }
  // "pending" (Ask to Buy, deferred payment) and "unknown" never grant and never ask to pay again.
  return { productId: purchase.productId, state: "PENDING", proof: null, transactionId, errorCode: null };
}

type StoreError = Pick<PurchaseError, "message"> & { readonly code?: string | undefined;
                                                    readonly productId?: string | null | undefined };

function fromError(productId: string, error: StoreError): PurchaseObservation {
  if (error.code === ErrorCode.UserCancelled) {
    return { productId, state: "CANCELLED", proof: null, transactionId: null, errorCode: "user_cancelled" };
  }
  if (error.code === ErrorCode.DeferredPayment || error.code === ErrorCode.Pending) {
    return { productId, state: "PENDING", proof: null, transactionId: null, errorCode: "pending" };
  }
  if (error.code === ErrorCode.IapNotAvailable || error.code === ErrorCode.BillingUnavailable
      || error.code === ErrorCode.ServiceDisconnected || error.code === ErrorCode.FeatureNotSupported) {
    return { productId, state: "UNAVAILABLE", proof: null, transactionId: null, errorCode: error.code ?? "unavailable" };
  }
  return { productId, state: "FAILED", proof: null, transactionId: null, errorCode: error.code ?? "purchase_error" };
}

export class ExpoIapPurchaseClient implements NativePurchaseClient {
  readonly rail: "apple_app_store" | "google_play";
  private connected = false;
  private readonly listeners = new Set<(observation: PurchaseObservation) => void>();
  private readonly waiting = new Map<string, (observation: PurchaseObservation) => void>();
  /** Store objects needed to finish an Apple transaction, keyed by proof. In memory only. */
  private readonly purchases = new Map<string, Purchase>();
  private subscriptions: Array<{ remove(): void }> = [];

  constructor(rail: "apple_app_store" | "google_play") {
    this.rail = rail;
  }

  async connect(): Promise<boolean> {
    if (this.connected) return true;
    try {
      this.connected = await initConnection();
    } catch {
      this.connected = false;
    }
    if (this.connected && this.subscriptions.length === 0) {
      this.subscriptions = [
        purchaseUpdatedListener((purchase) => this.emit(this.remember(purchase))),
        purchaseErrorListener((error) => {
          const productId = error.productId ?? "";
          this.emit(fromError(productId, error));
        }),
      ];
    }
    return this.connected;
  }

  private remember(purchase: Purchase): PurchaseObservation {
    const observation = observe(purchase);
    if (observation.proof !== null) this.purchases.set(observation.proof, purchase);
    return observation;
  }

  private emit(observation: PurchaseObservation): void {
    const waiter = this.waiting.get(observation.productId);
    if (waiter) {
      this.waiting.delete(observation.productId);
      waiter(observation);
      return;
    }
    for (const listener of this.listeners) listener(observation);
  }

  async listProducts(productIds: readonly string[]): Promise<StoreProduct[]> {
    if (!(await this.connect()) || productIds.length === 0) return [];
    const products = await fetchProducts({ skus: [...productIds], type: "in-app" });
    return (products ?? []).flatMap((product) => (productIds.includes(product.id)
      ? [{ productId: product.id, displayPrice: product.displayPrice, title: product.title }] : []));
  }

  async beginPurchase(productId: string, accountToken: string): Promise<PurchaseObservation> {
    if (!(await this.connect())) {
      return { productId, state: "UNAVAILABLE", proof: null, transactionId: null, errorCode: "store_unavailable" };
    }
    const outcome = new Promise<PurchaseObservation>((resolve) => {
      this.waiting.set(productId, resolve);
      setTimeout(() => {
        if (this.waiting.get(productId) === resolve) {
          this.waiting.delete(productId);
          // No answer is not a failure: the store may still complete it; never prompt to pay twice.
          resolve({ productId, state: "PENDING", proof: null, transactionId: null, errorCode: "outcome_unknown" });
        }
      }, OUTCOME_WAIT_MS);
    });
    try {
      const result = await requestPurchase({
        type: "in-app",
        request: {
          apple: { sku: productId, appAccountToken: accountToken, andDangerouslyFinishTransactionAutomatically: false },
          google: { skus: [productId], obfuscatedAccountId: accountToken },
        },
      });
      const first = Array.isArray(result) ? result[0] : result;
      if (first) this.emit(this.remember(first));
    } catch (error) {
      this.emit(fromError(productId, error as StoreError));
    }
    return outcome;
  }

  subscribe(listener: (observation: PurchaseObservation) => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  async recoverPendingTransactions(): Promise<PurchaseObservation[]> {
    if (!(await this.connect())) return [];
    const purchases = await getAvailablePurchases({ onlyIncludeActiveItemsIOS: true, alsoPublishToEventListenerIOS: false });
    return purchases.map((purchase) => this.remember(purchase)).filter((o) => o.state === "PROOF_READY");
  }

  async finishAfterServerGrant(observation: PurchaseObservation): Promise<void> {
    if (this.rail === "google_play") return;  // the server consumes after its durable grant
    const purchase = observation.proof === null ? undefined : this.purchases.get(observation.proof);
    if (purchase === undefined) throw new Error("unknown_purchase_proof");
    await finishTransaction({ purchase, isConsumable: true });
    this.purchases.delete(observation.proof!);
  }

  async disconnect(): Promise<void> {
    for (const subscription of this.subscriptions) subscription.remove();
    this.subscriptions = [];
    if (this.connected) await endConnection().catch(() => false);
    this.connected = false;
  }
}
