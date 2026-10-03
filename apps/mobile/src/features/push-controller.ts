// Device push registration bound to the current principal. Permission is
// requested only when the user turns notifications on; a denial or a device
// without push support leaves every other flow working. Notifications carry a
// type and an opaque reference only, and opening one re-reads current state.
import { ApiError, type PrincessApi } from "@princess/api-client";

import type { DevicePushClient, KeyValueFile, NotificationOpen } from "../platform/contracts.ts";
import type { NativeRoute } from "../platform/contracts.ts";

export const PUSH_FILE = "push-installations.v1.json";

type Registry = Record<string, { installationId: string; token: string }>;

export type PushStatus = "REGISTERED" | "NOT_REGISTERED" | "DENIED" | "UNAVAILABLE" | "FAILED";

type PushApi = Pick<PrincessApi, "registerPush" | "unregisterPush">;

export class PushController {
  private readonly api: PushApi;
  private readonly device: DevicePushClient;
  private readonly file: KeyValueFile;
  private readonly environment: string;

  constructor(api: PushApi, device: DevicePushClient, file: KeyValueFile, environment: string) {
    this.api = api;
    this.device = device;
    this.file = file;
    this.environment = environment;
  }

  private async registry(): Promise<Registry> {
    try {
      const parsed = JSON.parse((await this.file.read(PUSH_FILE)) ?? "{}") as unknown;
      return parsed !== null && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Registry : {};
    } catch {
      return {};
    }
  }

  private async save(registry: Registry): Promise<void> {
    await this.file.write(PUSH_FILE, JSON.stringify(registry));
  }

  async status(principalId: string): Promise<PushStatus> {
    if ((await this.registry())[principalId]) return "REGISTERED";
    const permission = await this.device.permission();
    return permission === "DENIED" ? "DENIED" : permission === "UNAVAILABLE" ? "UNAVAILABLE" : "NOT_REGISTERED";
  }

  /** The user asked for report-ready notifications on this device. */
  async enable(principalId: string, locale: string): Promise<PushStatus> {
    const token = await this.device.requestToken();
    if (token === null) {
      const permission = await this.device.permission();
      return permission === "UNAVAILABLE" ? "UNAVAILABLE" : "DENIED";
    }
    try {
      const installationId = await this.api.registerPush({ device_token: token.token, platform: token.platform,
                                                           app_environment: this.environment,
                                                           locale: locale === "sv" ? "sv" : "en" });
      // One device, one principal: an earlier binding on this device belongs to nobody now.
      await this.save({ [principalId]: { installationId, token: token.token } });
      return "REGISTERED";
    } catch (error) {
      if (error instanceof ApiError) return "FAILED";
      throw error;
    }
  }

  /** Token rotation or reinstall: re-bind only if this principal had opted in. */
  async refresh(principalId: string, locale: string): Promise<PushStatus> {
    const current = (await this.registry())[principalId];
    if (!current) return "NOT_REGISTERED";
    const token = await this.device.requestToken();
    if (token === null) return this.status(principalId);
    if (token.token === current.token) return "REGISTERED";
    return this.enable(principalId, locale);
  }

  /** Sign-out, account switch or deletion: unbind before the credential is forgotten. */
  async forget(principalId: string): Promise<void> {
    const registry = await this.registry();
    const binding = registry[principalId];
    if (binding) {
      try {
        await this.api.unregisterPush(binding.installationId);
      } catch {
        // Logout-everywhere/deletion already unbind server-side; a stale binding stops at the next token check.
      }
    }
    await this.save({});
  }
}

/**
 * A notification selects a resource; it never proves the resource still
 * exists or is authorized. The destination screen fetches current state.
 */
export function routeForNotification(open: NotificationOpen): NativeRoute | null {
  if (open.type === "report_ready" && open.reference !== null
      && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(open.reference)) {
    return { kind: "REPORT", reportId: open.reference };
  }
  return open.type === "report_ready" ? { kind: "HISTORY" } : null;
}
