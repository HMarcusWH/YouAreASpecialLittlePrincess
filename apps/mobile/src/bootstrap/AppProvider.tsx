// React composition: one set of services per process, the current session,
// device preferences, live work entries and app lifecycle wiring (foreground
// reconciliation, store replay, push token rotation and notification opens).
import { router } from "expo-router";
import { createContext, useContext, useEffect, useMemo, useRef, useState, type PropsWithChildren } from "react";
import { AppState, useColorScheme } from "react-native";

import type { RuntimeConfig } from "../config/runtime.ts";
import { PurchaseOrchestrator } from "../features/commerce.ts";
import { ExportController } from "../features/exports.ts";
import { PremiumController } from "../features/premium.ts";
import type { DevicePreferences } from "../features/preferences.ts";
import { routeForNotification } from "../features/push-controller.ts";
import { copy, resolveLocale, type AppLocale } from "../i18n/copy.ts";
import type { WorkingImage } from "../platform/contracts.ts";
import { pathFor } from "../platform/links.ts";
import type { SessionState } from "../session/session-manager.ts";
import { themeFor, type Theme } from "../ui/theme.ts";
import type { WorkEntry } from "../work/journal.ts";
import { newClientId } from "./ids.ts";
import { createNativeServices, nativePlatform } from "./native.ts";
import type { Services } from "./services.ts";

const CAPTURE_FILE_MAX_AGE_MS = 24 * 3600 * 1000;
const DOWNLOAD_MAX_AGE_MS = 3600 * 1000;

export interface AppValue {
  readonly services: Services;
  readonly config: RuntimeConfig;
  readonly platform: "ios" | "android";
  readonly session: SessionState;
  readonly locale: AppLocale;
  readonly theme: Theme;
  readonly t: (key: string) => string;
  readonly work: readonly WorkEntry[];
  readonly preferences: DevicePreferences;
  readonly setPreferences: (patch: Partial<DevicePreferences>) => Promise<void>;
  readonly draft: WorkingImage | null;
  readonly setDraft: (image: WorkingImage | null) => void;
  readonly purchases: PurchaseOrchestrator;
  readonly premium: PremiumController;
  readonly exports: ExportController;
}

const Context = createContext<AppValue | null>(null);

export function useApp(): AppValue {
  const value = useContext(Context);
  if (value === null) throw new Error("useApp outside AppProvider");
  return value;
}

function deviceLocale(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().locale;
  } catch {
    return null;
  }
}

export function AppProvider({ config, children }: PropsWithChildren<{ config: RuntimeConfig }>) {
  const servicesRef = useRef<Services | null>(null);
  if (servicesRef.current === null) servicesRef.current = createNativeServices(config);
  const services = servicesRef.current;
  const platform = nativePlatform();
  const [session, setSession] = useState<SessionState>(services.session.current());
  const [work, setWork] = useState<readonly WorkEntry[]>([]);
  const [preferences, setPrefs] = useState<DevicePreferences>({ locale: "system", theme: "system" });
  const [draft, setDraft] = useState<WorkingImage | null>(null);
  const systemScheme = useColorScheme();

  const controllers = useMemo(() => ({
    purchases: new PurchaseOrchestrator({
      api: services.api, store: services.ports.purchases, platform,
      principal: () => {
        const state = services.session.current();
        return state.status === "ACTIVE" ? { principalId: state.principalId, kind: state.kind } : null;
      },
    }),
    premium: new PremiumController(services.api, platform, newClientId),
    exports: new ExportController(services.api, services.ports.downloads, services.ports.share),
  }), [services, platform]);

  useEffect(() => {
    const offSession = services.session.subscribe(setSession);
    const offWork = services.runner.subscribe(setWork);
    void services.preferences.load().then(setPrefs);
    void (async () => {
      await services.session.hydrate().catch(() => undefined);
      // Private files expire: abandoned working copies and temporary downloads are removed at launch.
      const keep = await services.journal.allLocalUris();
      await services.ports.preparer.sweep(keep, CAPTURE_FILE_MAX_AGE_MS).catch(() => 0);
      await services.ports.downloads.sweep(DOWNLOAD_MAX_AGE_MS).catch(() => 0);
    })();
    return () => { offSession(); offWork(); };
  }, [services]);

  useEffect(() => {
    const stopStore = controllers.purchases.start();
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active") {
        services.runner.resume();
        void controllers.purchases.reconcile().catch(() => []);
      } else if (state === "background") {
        services.runner.suspend();
      }
    });
    return () => { stopStore(); subscription.remove(); };
  }, [services, controllers]);

  // Store replay and push binding follow the signed-in principal.
  useEffect(() => {
    if (session.status !== "ACTIVE") return undefined;
    const principalId = session.principalId;
    const language = resolveLocale(preferences.locale, deviceLocale());
    void controllers.purchases.reconcile().catch(() => []);
    void services.push.refresh(principalId, language).catch(() => undefined);
    const offToken = services.ports.push.onTokenChanged(() => {
      void services.push.refresh(principalId, language).catch(() => undefined);
    });
    return offToken;
  }, [session.status, session.status === "ACTIVE" ? session.principalId : null, preferences.locale, services,
      controllers]);

  useEffect(() => {
    const open = (event: Parameters<typeof routeForNotification>[0]) => {
      // A notification selects a screen; the screen re-reads current authorized state.
      const route = routeForNotification(event);
      if (route !== null) router.push(pathFor(route) as never);
    };
    void services.ports.push.launchOpen().then((event) => { if (event) open(event); }).catch(() => undefined);
    return services.ports.push.onOpen(open);
  }, [services]);

  const locale = resolveLocale(preferences.locale, deviceLocale());
  const scheme = preferences.theme === "system" ? (systemScheme === "dark" ? "dark" : "light") : preferences.theme;
  const value = useMemo<AppValue>(() => ({
    services, config, platform, session, locale, theme: themeFor(scheme), t: (key: string) => copy(locale, key), work,
    preferences,
    setPreferences: async (patch) => setPrefs(await services.preferences.update(patch)),
    draft, setDraft, ...controllers,
  }), [services, config, platform, session, locale, scheme, work, preferences, draft, controllers]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}
