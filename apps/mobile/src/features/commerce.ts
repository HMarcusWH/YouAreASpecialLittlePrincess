// Native purchase orchestration over the server ledger (docs/roadmap/14).
//
// The store only produces a proof; the server verifies it and grants credit
// in its one ledger. The app finishes a store transaction only after the
// server reports a durable grant, shows pending/unknown outcomes without
// asking the user to pay again, requires an account before a consumable
// purchase (guest work moves to the account first) and never keeps its own
// credit counter: balances are read from the server.
import { ApiError, TransportError, type CatalogProduct, type ClaimResult, type ClientPlatform, type Credits,
         type StoreRail } from "@princess/api-client";

import type { NativePurchaseClient, PurchaseObservation, StoreProduct } from "../platform/contracts.ts";

export interface CommerceApi {
  catalog(): Promise<readonly CatalogProduct[]>;
  paymentAccount(): Promise<string>;
  credits(platform: ClientPlatform): Promise<Credits>;
  claimStorePurchase(rail: StoreRail, proof: string): Promise<ClaimResult>;
}

export interface Principal {
  readonly principalId: string;
  readonly kind: "ACCOUNT" | "GUEST";
}

export interface Offer {
  readonly productId: string;
  readonly storeProductId: string;
  readonly credits: number;
  readonly displayPrice: string;
  readonly title: string;
}

export type OffersResult =
  | { readonly status: "OK"; readonly offers: readonly Offer[] }
  | { readonly status: "ACCOUNT_REQUIRED" | "STORE_UNAVAILABLE" | "SALES_CLOSED" | "NO_PRODUCTS" };

export type BuyOutcome =
  | { readonly status: "ACCOUNT_REQUIRED" | "STORE_UNAVAILABLE" | "CANCELLED" | "PENDING" | "VERIFYING" }
  | { readonly status: "SALES_CLOSED" | "FAILED" | "NOT_GRANTED"; readonly code: string }
  | { readonly status: "GRANTED"; readonly alreadyGranted: boolean };

export class PurchaseOrchestrator {
  private readonly api: CommerceApi;
  private readonly store: NativePurchaseClient | null;
  private readonly platform: "ios" | "android";
  private readonly principal: () => Principal | null;
  private readonly listeners = new Set<(outcome: BuyOutcome, observation: PurchaseObservation) => void>();
  private readonly settling = new Map<string, Promise<BuyOutcome>>();

  constructor(deps: { api: CommerceApi; store: NativePurchaseClient | null; platform: "ios" | "android";
                      principal: () => Principal | null }) {
    this.api = deps.api;
    this.store = deps.store;
    this.platform = deps.platform;
    this.principal = deps.principal;
  }

  onOutcome(listener: (outcome: BuyOutcome, observation: PurchaseObservation) => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  /** Server catalog joined with store-localized prices; price text is display metadata only. */
  async offers(): Promise<OffersResult> {
    const who = this.principal();
    if (who === null || who.kind !== "ACCOUNT") return { status: "ACCOUNT_REQUIRED" };
    if (this.store === null || !(await this.store.connect())) return { status: "STORE_UNAVAILABLE" };
    let catalog: readonly CatalogProduct[];
    try {
      catalog = await this.api.catalog();
    } catch (error) {
      if (error instanceof ApiError && (error.status === 501 || error.status === 503)) {
        return { status: "SALES_CLOSED" };
      }
      throw error;
    }
    const rail = this.store.rail;
    const mapped = catalog.flatMap((product) => {
      const storeId = product.rails[rail];
      return storeId ? [{ product, storeId }] : [];
    });
    if (mapped.length === 0) return { status: "NO_PRODUCTS" };
    const storeProducts = new Map<string, StoreProduct>(
      (await this.store.listProducts(mapped.map((m) => m.storeId))).map((p) => [p.productId, p]));
    const offers = mapped.flatMap(({ product, storeId }) => {
      const listed = storeProducts.get(storeId);
      return listed ? [{ productId: product.product_id, storeProductId: storeId, credits: product.credits,
                         displayPrice: listed.displayPrice, title: listed.title }] : [];
    });
    return offers.length > 0 ? { status: "OK", offers } : { status: "NO_PRODUCTS" };
  }

  async balance(): Promise<Credits | null> {
    const who = this.principal();
    if (who === null) return null;
    return this.api.credits(this.platform);
  }

  async buy(offer: Offer): Promise<BuyOutcome> {
    const who = this.principal();
    if (who === null || who.kind !== "ACCOUNT") return { status: "ACCOUNT_REQUIRED" };
    if (this.store === null || !(await this.store.connect())) return { status: "STORE_UNAVAILABLE" };
    let accountToken: string;
    try {
      accountToken = await this.api.paymentAccount();
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) return { status: "ACCOUNT_REQUIRED" };
      throw error;
    }
    const observation = await this.store.beginPurchase(offer.storeProductId, accountToken);
    // A purchase that resolves after the user switched accounts is claimed later by its own account.
    const now = this.principal();
    if (now === null || now.principalId !== who.principalId) return { status: "VERIFYING" };
    return this.settle(observation);
  }

  /** Claim a store observation with the server; finish the store transaction only after a durable grant. */
  settle(observation: PurchaseObservation): Promise<BuyOutcome> {
    switch (observation.state) {
      case "CANCELLED": return Promise.resolve({ status: "CANCELLED" });
      case "PENDING": return Promise.resolve({ status: "PENDING" });
      case "UNAVAILABLE": return Promise.resolve({ status: "STORE_UNAVAILABLE" });
      case "FAILED": return Promise.resolve({ status: "FAILED", code: observation.errorCode ?? "purchase_failed" });
      default: break;
    }
    const proof = observation.proof!;
    const existing = this.settling.get(proof);
    if (existing) return existing;
    const run = this.claim(observation).finally(() => this.settling.delete(proof));
    this.settling.set(proof, run);
    return run;
  }

  private async claim(observation: PurchaseObservation): Promise<BuyOutcome> {
    const who = this.principal();
    if (who === null || who.kind !== "ACCOUNT" || this.store === null) return { status: "VERIFYING" };
    let result: ClaimResult;
    try {
      result = await this.api.claimStorePurchase(this.store.rail, observation.proof!);
    } catch (error) {
      if (error instanceof TransportError || (error instanceof ApiError && error.status >= 500)) {
        // Unknown verification outcome: the store redelivers the unfinished transaction; nothing is charged again.
        return { status: "VERIFYING" };
      }
      if (error instanceof ApiError && error.status === 403) return { status: "ACCOUNT_REQUIRED" };
      if (error instanceof ApiError) return { status: "NOT_GRANTED", code: error.code };
      throw error;
    }
    if (result.outcome === "granted" || result.outcome === "already_granted") {
      if (result.finish_transaction || this.store.rail === "google_play") {
        try {
          await this.store.finishAfterServerGrant(observation);
        } catch {
          // The grant is durable; the next startup replay finishes the transaction and converges.
        }
      }
      return { status: "GRANTED", alreadyGranted: result.outcome === "already_granted" };
    }
    if (result.outcome === "pending") return { status: "PENDING" };
    return { status: "NOT_GRANTED", code: result.outcome };
  }

  /** Startup/foreground replay of store transactions that were never finished. */
  async reconcile(): Promise<BuyOutcome[]> {
    const who = this.principal();
    if (who === null || who.kind !== "ACCOUNT" || this.store === null || !(await this.store.connect())) return [];
    const outcomes: BuyOutcome[] = [];
    for (const observation of await this.store.recoverPendingTransactions()) {
      const outcome = await this.settle(observation);
      outcomes.push(outcome);
      for (const listener of this.listeners) listener(outcome, observation);
    }
    return outcomes;
  }

  /** Deliver store updates that arrive outside a purchase call (Ask to Buy, pending completion). */
  start(): () => void {
    if (this.store === null) return () => undefined;
    return this.store.subscribe((observation) => {
      void this.settle(observation).then((outcome) => {
        for (const listener of this.listeners) listener(outcome, observation);
      });
    });
  }
}
