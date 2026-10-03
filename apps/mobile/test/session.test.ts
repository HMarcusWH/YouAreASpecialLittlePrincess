import assert from "node:assert/strict";
import test from "node:test";

import { ApiError, TransportError, type Me } from "@princess/api-client";

import { FakeSecureSessionStore } from "../src/platform/fakes.ts";
import {
  SessionManager, decodeCredential, encodeCredential, type CredentialRecord, type SessionApi,
} from "../src/session/session-manager.ts";

class FakeSessionApi implements SessionApi {
  principals = new Map<string, Me>();
  guests = 0;
  transfers: Array<[string, string]> = [];
  meError: Error | null = null;
  transferError: Error | null = null;
  revoked: string[] = [];
  deleted: string[] = [];
  release: (() => void) | null = null;

  async me(token: string) {
    if (this.meError) throw this.meError;
    const me = this.principals.get(token);
    if (!me) throw new ApiError(401, "malformed_or_unknown_token");
    return me;
  }
  async createGuestSession() {
    if (this.release) await new Promise<void>((resolve) => { this.release = resolve; });
    this.guests += 1;
    const token = `guest-token-${this.guests}`;
    this.principals.set(token, { principal_id: `prn_guest_${this.guests}`, kind: "GUEST" });
    return { principal_id: `prn_guest_${this.guests}`, guest_token: token, expires_at: null };
  }
  async transferGuest(account: string, guest: string) {
    if (this.transferError) throw this.transferError;
    this.transfers.push([account, guest]);
    this.principals.delete(guest);
    return "prn_guest_1";
  }
  async logoutEverywhere(token: string) { this.revoked.push(token); }
  async deleteAccount(token: string) { this.deleted.push(token); return { state: "DELETION_REQUESTED" as const }; }
}

const account: CredentialRecord = { v: 1, kind: "ACCOUNT", principalId: "prn_alice", token: "account-token-alice",
                                    origin: "development", expiresAt: null };

function setup(stored: CredentialRecord | null = null) {
  const store = new FakeSecureSessionStore();
  if (stored) store.value = encodeCredential(stored);
  const api = new FakeSessionApi();
  api.principals.set(account.token, { principal_id: "prn_alice", kind: "ACCOUNT" });
  const session = new SessionManager(store, api, () => new Date("2026-10-03T12:00:00Z"));
  const exits: Array<[string, string]> = [];
  session.onPrincipalExit(async (principal, reason) => { exits.push([principal, reason]); });
  return { store, api, session, exits };
}

test("a clean install reaches an explicit signed-out state", async () => {
  const { session } = setup();
  assert.deepEqual(await session.hydrate(), { status: "SIGNED_OUT", reason: "fresh" });
  assert.equal(session.token(), null);
});

test("guest sessions persist only credential material and resume after restart", async () => {
  const { store, api, session } = setup();
  await session.hydrate();
  const state = await session.startGuest();
  assert.equal(state.status === "ACTIVE" && state.kind, "GUEST");
  const record = decodeCredential(store.value)!;
  assert.deepEqual(Object.keys(record).sort(), ["expiresAt", "kind", "origin", "principalId", "token", "v"]);
  const restarted = new SessionManager(store, api);
  const resumed = await restarted.hydrate();
  assert.equal(resumed.status === "ACTIVE" && resumed.principalId, "prn_guest_1");
  assert.equal(resumed.status === "ACTIVE" && resumed.verified, true);
});

test("a revoked credential at launch is forgotten and the exit hooks purge its local state", async () => {
  const { store, api, session, exits } = setup(account);
  api.principals.clear();
  assert.deepEqual(await session.hydrate(), { status: "SIGNED_OUT", reason: "expired" });
  assert.equal(store.value, null);
  assert.deepEqual(exits, [["prn_alice", "expired"]]);
});

test("offline launch keeps the credential unverified until an authenticated call succeeds", async () => {
  const { api, session } = setup(account);
  api.meError = new TransportError("NETWORK");
  const state = await session.hydrate();
  assert.equal(state.status === "ACTIVE" && state.verified, false);
  session.markVerified("someone-else");
  assert.equal((session.current() as { verified: boolean }).verified, false);
  session.markVerified(account.token);
  assert.equal((session.current() as { verified: boolean }).verified, true);
});

test("signing in from a guest transfers the guest's work with proof of both credentials", async () => {
  const { store, api, session, exits } = setup();
  await session.hydrate();
  await session.startGuest();
  const state = await session.signIn(account.token, "development");
  assert.deepEqual(api.transfers, [[account.token, "guest-token-1"]]);
  assert.equal(state.status === "ACTIVE" && state.principalId, "prn_alice");
  assert.equal(decodeCredential(store.value)!.kind, "ACCOUNT");
  assert.deepEqual(exits, [["prn_guest_1", "account_switch"]]);
});

test("a failed guest transfer keeps the guest session intact", async () => {
  const { store, api, session } = setup();
  await session.hydrate();
  await session.startGuest();
  api.transferError = new ApiError(503, "unavailable");
  await assert.rejects(session.signIn(account.token, "development"), (e: unknown) => e instanceof ApiError);
  assert.equal(decodeCredential(store.value)!.kind, "GUEST");
  assert.equal(session.token(), "guest-token-1");
  await assert.rejects(session.signIn("guest-token-1", "development"), /account_credential_required/);
});

test("late results for the previous principal are fenced after any credential change", async () => {
  const { session } = setup(account);
  await session.hydrate();
  let release!: (value: string) => void;
  const pending = session.guard(new Promise<string>((resolve) => { release = resolve; }));
  await session.signOut();
  release("alice's report");
  assert.equal(await pending, null);
});

test("a 401 for an older credential never signs out the newer session", async () => {
  const { session } = setup(account);
  await session.hydrate();
  await session.credentialRejected("stale-guest-token");
  assert.equal(session.current().status, "ACTIVE");
  await session.credentialRejected(account.token);
  assert.deepEqual(session.current(), { status: "SIGNED_OUT", reason: "expired" });
});

test("overlapping credential changes are serialized", async () => {
  const { api, session } = setup();
  await session.hydrate();
  api.release = () => undefined;
  const first = session.startGuest();
  const second = session.startGuest();
  await new Promise((resolve) => setTimeout(resolve, 5));
  api.release!();
  await first;
  api.release = null;
  await second;
  assert.equal(api.guests, 1, "the second start sees the first guest and creates nothing");
});

test("sign-out here, sign-out everywhere and deletion are separate, honest operations", async () => {
  const one = setup(account);
  await one.session.hydrate();
  assert.deepEqual(await one.session.logoutEverywhere(), { status: "SIGNED_OUT", reason: "logged_out_everywhere" });
  assert.deepEqual(one.api.revoked, [account.token]);

  const two = setup(account);
  await two.session.hydrate();
  assert.equal(await two.session.deleteAccount(), "DELETION_REQUESTED");
  assert.deepEqual(two.session.current(), { status: "SIGNED_OUT", reason: "deleted" });
  assert.equal(two.store.value, null);

  const three = setup(account);
  await three.session.hydrate();
  await three.session.signOut();
  assert.deepEqual(three.api.revoked, [], "local sign-out does not revoke other devices");
});

test("corrupt or expired stored credentials are refused", async () => {
  assert.equal(decodeCredential("{not json"), null);
  assert.equal(decodeCredential(JSON.stringify({ ...account, v: 2 })), null);
  assert.equal(decodeCredential(JSON.stringify({ ...account, principalId: "../x" })), null);
  const { store, session } = setup({ ...account, expiresAt: "2026-10-01T00:00:00Z" });
  assert.deepEqual(await session.hydrate(), { status: "SIGNED_OUT", reason: "expired" });
  assert.equal(store.value, null);
});
