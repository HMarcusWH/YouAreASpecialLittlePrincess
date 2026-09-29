import { SessionEpoch } from "@princess/api-client";

import type { SecureSessionStore } from "../platform/contracts.ts";

export class NativeSessionBoundary {
  readonly epoch = new SessionEpoch();

  constructor(private readonly store: SecureSessionStore) {}

  async switchPrincipal(nextCredential: string | null) {
    this.epoch.switchPrincipal();
    await this.store.clear();
    if (nextCredential) await this.store.write(nextCredential);
  }

  guard<T>(work: Promise<T>) {
    return this.epoch.guard(work);
  }
}
