// Non-sensitive per-device display preferences. Nothing account-bound,
// private or authoritative is stored here.
import type { KeyValueFile } from "../platform/contracts.ts";

export const PREFERENCES_FILE = "preferences.v1.json";

export interface DevicePreferences {
  readonly locale: "system" | "en" | "sv";
  readonly theme: "system" | "light" | "dark";
}

const DEFAULTS: DevicePreferences = { locale: "system", theme: "system" };

export class Preferences {
  private readonly file: KeyValueFile;
  private value: DevicePreferences | null = null;

  constructor(file: KeyValueFile) {
    this.file = file;
  }

  async load(): Promise<DevicePreferences> {
    if (this.value !== null) return this.value;
    try {
      const raw = JSON.parse((await this.file.read(PREFERENCES_FILE)) ?? "{}") as Partial<DevicePreferences>;
      this.value = {
        locale: raw.locale === "en" || raw.locale === "sv" ? raw.locale : "system",
        theme: raw.theme === "light" || raw.theme === "dark" ? raw.theme : "system",
      };
    } catch {
      this.value = DEFAULTS;
    }
    return this.value;
  }

  async update(patch: Partial<DevicePreferences>): Promise<DevicePreferences> {
    const next = { ...(await this.load()), ...patch };
    this.value = next;
    await this.file.write(PREFERENCES_FILE, JSON.stringify(next));
    return next;
  }
}
