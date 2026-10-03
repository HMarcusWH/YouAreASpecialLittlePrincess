// The native session boundary: one credential in platform secure storage,
// the current principal, and an epoch that fences late results after any
// credential change. Credential changes are serialized so two overlapping
// sign-in/out/guest operations cannot interleave and leave mixed state.
//
// Sign-out on this device, sign-out everywhere (an API revocation fence) and
// account deletion (an asynchronous server erasure) are separate operations.
// Provider-global session revocation belongs to the identity adapter (N07).
import { ApiError, SessionEpoch, TransportError, type Me, type PrincipalKind } from "@princess/api-client";

import type { SecureSessionStore } from "../platform/contracts.ts";

export const CREDENTIAL_VERSION = 1;

export type CredentialOrigin = "guest" | "development" | "provider";

export interface CredentialRecord {
  readonly v: 1;
  readonly kind: PrincipalKind;
  readonly principalId: string;
  readonly token: string;
  readonly origin: CredentialOrigin;
  readonly expiresAt: string | null;
}

export type SignedOutReason = "fresh" | "signed_out" | "expired" | "deleted" | "logged_out_everywhere";

export type SessionState =
  | { readonly status: "LOADING" }
  | { readonly status: "SIGNED_OUT"; readonly reason: SignedOutReason }
  | { readonly status: "ACTIVE"; readonly principalId: string; readonly kind: PrincipalKind;
      readonly origin: CredentialOrigin; readonly verified: boolean; readonly epoch: number };

/** The subset of the API the session needs; each call names the credential it uses. */
export interface SessionApi {
  me(token: string): Promise<Me>;
  createGuestSession(): Promise<{ principal_id: string; guest_token: string; expires_at: string | null }>;
  transferGuest(accountToken: string, guestToken: string): Promise<string>;
  logoutEverywhere(token: string): Promise<void>;
  deleteAccount(token: string): Promise<{ state: "DELETION_REQUESTED" }>;
}

/** Work that must run for the outgoing principal before its credential is forgotten. */
export type PrincipalExitHook = (principalId: string, reason: SignedOutReason | "account_switch") => Promise<void>;

export function encodeCredential(record: CredentialRecord): string {
  return JSON.stringify(record);
}

export function decodeCredential(raw: string | null): CredentialRecord | null {
  if (raw === null) return null;
  try {
    const value = JSON.parse(raw) as Partial<CredentialRecord>;
    if (value.v !== CREDENTIAL_VERSION || (value.kind !== "GUEST" && value.kind !== "ACCOUNT")
        || typeof value.principalId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value.principalId)
        || typeof value.token !== "string" || value.token.length < 10 || value.token.length > 8192
        || (value.origin !== "guest" && value.origin !== "development" && value.origin !== "provider")
        || (value.expiresAt !== null && typeof value.expiresAt !== "string")) {
      return null;
    }
    return value as CredentialRecord;
  } catch {
    return null;
  }
}

export class SessionManager {
  readonly epoch = new SessionEpoch();
  private state: SessionState = { status: "LOADING" };
  private record: CredentialRecord | null = null;
  private queue: Promise<unknown> = Promise.resolve();
  private readonly listeners = new Set<(state: SessionState) => void>();
  private readonly exitHooks: PrincipalExitHook[] = [];
  private readonly store: SecureSessionStore;
  private readonly api: SessionApi;
  private readonly now: () => Date;

  constructor(store: SecureSessionStore, api: SessionApi, now: () => Date = () => new Date()) {
    this.store = store;
    this.api = api;
    this.now = now;
  }

  current(): SessionState {
    return this.state;
  }

  /** The credential for the next request, or null; read per request by the API client. */
  token(): string | null {
    return this.record?.token ?? null;
  }

  subscribe(listener: (state: SessionState) => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  onPrincipalExit(hook: PrincipalExitHook): void {
    this.exitHooks.push(hook);
  }

  /** Drops the result if the principal or credential changed while ``work`` ran. */
  guard<T>(work: Promise<T>): Promise<T | null> {
    return this.epoch.guard(work);
  }

  private serialize<T>(operation: () => Promise<T>): Promise<T> {
    const run = this.queue.then(operation, operation);
    this.queue = run.catch(() => undefined);
    return run;
  }

  private publish(state: SessionState): void {
    this.state = state;
    for (const listener of this.listeners) listener(state);
  }

  private activate(record: CredentialRecord, verified: boolean): void {
    this.epoch.switchPrincipal();
    this.record = record;
    this.publish({ status: "ACTIVE", principalId: record.principalId, kind: record.kind, origin: record.origin,
                   verified, epoch: this.epoch.current() });
  }

  private async forget(reason: SignedOutReason | "account_switch"): Promise<void> {
    const outgoing = this.record;
    // Fence first: anything still in flight for the outgoing principal is discarded.
    this.epoch.switchPrincipal();
    if (outgoing !== null) {
      for (const hook of this.exitHooks) {
        try {
          await hook(outgoing.principalId, reason);
        } catch {
          // Cleanup is best effort and must never keep a credential alive.
        }
      }
    }
    this.record = null;
    await this.store.clear();
  }

  private expired(record: CredentialRecord): boolean {
    return record.expiresAt !== null && Date.parse(record.expiresAt) <= this.now().getTime();
  }

  /** Restore the stored credential at launch and verify it with the API when reachable. */
  hydrate(): Promise<SessionState> {
    return this.serialize(async () => {
      const record = decodeCredential(await this.store.read());
      if (record === null || this.expired(record)) {
        await this.store.clear();
        this.publish({ status: "SIGNED_OUT", reason: record === null ? "fresh" : "expired" });
        return this.state;
      }
      try {
        const me = await this.api.me(record.token);
        if (me.principal_id !== record.principalId || me.kind !== record.kind) {
          // The server now resolves this credential differently (for example a transferred guest).
          this.record = record;
          await this.forget("expired");
          this.publish({ status: "SIGNED_OUT", reason: "expired" });
          return this.state;
        }
        this.activate(record, true);
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          this.record = record;
          await this.forget("expired");
          this.publish({ status: "SIGNED_OUT", reason: "expired" });
        } else if (error instanceof TransportError || (error instanceof ApiError && error.status >= 500)) {
          // Offline at launch: keep the credential; the first authenticated call re-verifies it.
          this.activate(record, false);
        } else {
          throw error;
        }
      }
      return this.state;
    });
  }

  /** A private guest session: no account, nothing purchasable. */
  startGuest(): Promise<SessionState> {
    return this.serialize(async () => {
      if (this.state.status === "ACTIVE") return this.state;
      const guest = await this.api.createGuestSession();
      const record: CredentialRecord = { v: 1, kind: "GUEST", principalId: guest.principal_id,
                                         token: guest.guest_token, origin: "guest", expiresAt: guest.expires_at };
      await this.store.write(encodeCredential(record));
      this.activate(record, true);
      return this.state;
    });
  }

  /**
   * Adopt an account credential obtained from the identity transport. When a
   * guest session is active its work moves to the account first, proving
   * possession of both credentials; a failed transfer leaves the guest intact.
   */
  signIn(token: string, origin: Exclude<CredentialOrigin, "guest">): Promise<SessionState> {
    return this.serialize(async () => {
      const me = await this.api.me(token);
      if (me.kind !== "ACCOUNT") throw new ApiError(422, "account_credential_required");
      const previous = this.record;
      if (previous !== null && previous.kind === "GUEST") {
        try {
          await this.api.transferGuest(token, previous.token);
        } catch (error) {
          // Already transferred (409) is converged; anything else keeps the guest session.
          if (!(error instanceof ApiError && error.status === 409)) throw error;
        }
      }
      if (previous !== null && previous.principalId !== me.principal_id) await this.forget("account_switch");
      const record: CredentialRecord = { v: 1, kind: "ACCOUNT", principalId: me.principal_id, token, origin,
                                         expiresAt: null };
      await this.store.write(encodeCredential(record));
      this.activate(record, true);
      return this.state;
    });
  }

  /** Forget the credential on this device only. Other devices stay signed in. */
  signOut(): Promise<SessionState> {
    return this.serialize(async () => {
      await this.forget("signed_out");
      this.publish({ status: "SIGNED_OUT", reason: "signed_out" });
      return this.state;
    });
  }

  /** Revoke every session of this principal at the API, then forget it here. */
  logoutEverywhere(): Promise<SessionState> {
    return this.serialize(async () => {
      const record = this.record;
      if (record === null) return this.state;
      await this.api.logoutEverywhere(record.token);
      await this.forget("logged_out_everywhere");
      this.publish({ status: "SIGNED_OUT", reason: "logged_out_everywhere" });
      return this.state;
    });
  }

  /** Request erasure. The 202 means requested, not finished; the credential is forgotten either way. */
  deleteAccount(): Promise<"DELETION_REQUESTED"> {
    return this.serialize(async () => {
      const record = this.record;
      if (record === null) throw new ApiError(401, "missing_credential");
      const result = await this.api.deleteAccount(record.token);
      await this.forget("deleted");
      this.publish({ status: "SIGNED_OUT", reason: "deleted" });
      return result.state;
    });
  }

  /**
   * An authenticated call answered 401. Only the credential that made the call
   * is forgotten: a 401 that arrives after a newer sign-in changes nothing.
   */
  credentialRejected(token: string): Promise<void> {
    return this.serialize(async () => {
      if (this.record === null || this.record.token !== token) return;
      await this.forget("expired");
      this.publish({ status: "SIGNED_OUT", reason: "expired" });
    });
  }

  /** The first successful authenticated call after an offline launch. */
  markVerified(token: string): void {
    if (this.state.status === "ACTIVE" && !this.state.verified && this.record?.token === token) {
      this.publish({ ...this.state, verified: true });
    }
  }
}
