// Composition root for the native app, free of React Native imports so the
// same wiring runs in tests and in the live development-API journey.
import { PrincessApi } from "@princess/api-client";

import type { RuntimeConfig } from "../config/runtime.ts";
import type {
  AuthorizedFileClient, CaptureClient, DeepLinkRouter, DevicePushClient, FileShareClient, ImagePreparer,
  KeyValueFile, NativePurchaseClient, SecureSessionStore,
} from "../platform/contracts.ts";
import { SessionManager, type SessionApi } from "../session/session-manager.ts";
import { CaptureWorkflow, type LocalFiles } from "../work/capture-workflow.ts";
import { WorkJournal } from "../work/journal.ts";
import { WorkRunner, type Timers } from "../work/runner.ts";
import { PushController } from "../features/push-controller.ts";
import { Preferences } from "../features/preferences.ts";

export interface NativePorts {
  readonly secureStore: SecureSessionStore;
  readonly documents: KeyValueFile;
  readonly files: LocalFiles;
  readonly preparer: ImagePreparer;
  readonly capture: CaptureClient;
  readonly downloads: AuthorizedFileClient;
  readonly share: FileShareClient;
  readonly purchases: NativePurchaseClient | null;
  readonly push: DevicePushClient;
  readonly links: DeepLinkRouter;
}

export interface Services {
  readonly config: RuntimeConfig;
  readonly ports: NativePorts;
  readonly session: SessionManager;
  readonly api: PrincessApi;
  readonly journal: WorkJournal;
  readonly workflow: CaptureWorkflow;
  readonly runner: WorkRunner;
  readonly push: PushController;
  readonly preferences: Preferences;
  /** A client bound to one explicit credential (verification, guest transfer). */
  readonly clientFor: (token: string | null) => PrincessApi;
}

const REQUEST_TIMEOUT_MS = 20_000;

function authorizationOf(init: RequestInit | undefined): string | null {
  const headers = init?.headers as Record<string, string> | undefined;
  const value = headers?.authorization ?? null;
  return value !== null && value.startsWith("Bearer ") ? value.slice("Bearer ".length) : null;
}

export function createServices(config: RuntimeConfig, ports: NativePorts, deps: {
  readonly fetch: typeof fetch; readonly timers: Timers; readonly newId: () => string; readonly now?: () => Date;
}): Services {
  const now = deps.now ?? (() => new Date());
  const clientFor = (token: string | null) => new PrincessApi({
    baseUrl: config.apiBaseUrl, fetch: deps.fetch, token, timeoutMs: REQUEST_TIMEOUT_MS });
  const sessionApi: SessionApi = {
    me: (token) => clientFor(token).me(),
    createGuestSession: () => clientFor(null).createGuestSession(),
    transferGuest: (accountToken, guestToken) => clientFor(accountToken).transferGuest(guestToken),
    logoutEverywhere: (token) => clientFor(token).logoutEverywhere(),
    deleteAccount: (token) => clientFor(token).deleteAccount(),
  };
  const session = new SessionManager(ports.secureStore, sessionApi, now);
  // Every authenticated response reports back: a 401 forgets exactly the credential that was rejected.
  const observedFetch: typeof fetch = async (input, init) => {
    const token = authorizationOf(init);
    const response = await deps.fetch(input, init);
    if (token !== null) {
      if (response.status === 401) void session.credentialRejected(token);
      else if (response.ok) session.markVerified(token);
    }
    return response;
  };
  const api = new PrincessApi({ baseUrl: config.apiBaseUrl, fetch: observedFetch, credentials: () => session.token(),
                                timeoutMs: REQUEST_TIMEOUT_MS });
  const journal = new WorkJournal(ports.documents);
  const workflow = new CaptureWorkflow({ api, files: ports.files, journal, now, newId: deps.newId });
  const runner = new WorkRunner(workflow, journal, deps.timers, now);
  const preferences = new Preferences(ports.documents);
  const push = new PushController(api, ports.push, ports.documents, config.backendEnvironment);

  session.onPrincipalExit(async (principalId) => {
    runner.stop();
    // Unregister while the outgoing credential is still current; queued notices for it are dropped server-side.
    await push.forget(principalId);
    for (const entry of await journal.purge(principalId)) {
      if (entry.local !== null) await ports.files.remove(entry.local.uri).catch(() => undefined);
    }
    await ports.downloads.sweep(0).catch(() => 0);
  });
  session.subscribe((state) => {
    if (state.status === "ACTIVE") runner.start(state.principalId);
    else runner.stop();
  });
  return { config, ports, session, api, journal, workflow, runner, push, preferences, clientFor };
}
