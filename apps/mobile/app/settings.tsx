import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Alert } from "react-native";

import { useApp } from "../src/bootstrap/AppProvider.tsx";
import { newClientId } from "../src/bootstrap/ids.ts";
import type { PushStatus } from "../src/features/push-controller.ts";
import { Banner, Body, Button, Card, Choice, Heading, KeyValue, Screen, Toggle } from "../src/ui/components.tsx";

export default function Settings() {
  const { t, services, session, config, preferences, setPreferences, locale } = useApp();
  const [retainAll, setRetainAll] = useState<boolean | null>(null);
  const [mail, setMail] = useState<boolean | null>(null);
  const [push, setPush] = useState<PushStatus | null>(null);
  const [message, setMessage] = useState<{ tone: "danger" | "ready"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const active = session.status === "ACTIVE" ? session : null;

  useFocusEffect(useCallback(() => {
    if (active === null) return;
    void services.session.guard(services.api.checkPermission("image_retention")).then((check) => {
      if (check) setRetainAll(check.allowed);
    }).catch(() => setRetainAll(null));
    void services.session.guard(services.api.notificationPreferences()).then((prefs) => {
      if (prefs) setMail(prefs.mail_report_ready);
    }).catch(() => setMail(null));
    void services.push.status(active.principalId).then(setPush).catch(() => setPush("UNAVAILABLE"));
  }, [services, active?.principalId]));

  async function attempt(action: () => Promise<void>) {
    setBusy(true);
    setMessage(null);
    try {
      await action();
    } catch {
      setMessage({ tone: "danger", text: t("settings.failed") });
    } finally {
      setBusy(false);
    }
  }

  async function changeRetention(value: boolean) {
    await attempt(async () => {
      const notices = await services.api.consentNotices(locale);
      const notice = notices.find((n) => n.accepted_for_use && n.purposes.some((p) => p.purpose_id === "image_retention"));
      if (value && !notice) throw new Error("notice_not_accepted");
      await services.api.recordPermission({ purpose_id: "image_retention", scope_kind: "SUBJECT_WIDE", scope_ref: null,
                                            decision: value ? "GRANT" : "WITHDRAW",
                                            notice_version: notice?.notice_version ?? "notice.consent-choices:1",
                                            request_id: `mobile.${newClientId()}.retention` });
      setRetainAll(value);
    });
  }

  function confirm(title: string, body: string, action: () => Promise<void>) {
    Alert.alert(title, body, [
      { text: t("common.cancel"), style: "cancel" },
      { text: t("common.confirm"), style: "destructive", onPress: () => void attempt(action) },
    ]);
  }

  return (
    <Screen title={t("settings.title")}>
      {message ? <Banner tone={message.tone}>{message.text}</Banner> : null}
      <Card>
        <Heading>{t("settings.account")}</Heading>
        {active ? <KeyValue label={active.kind === "GUEST" ? t("settings.guest") : t("settings.account_signed_in")}
                            value={`…${active.principalId.slice(-6)}`} /> : null}
        {active === null || active.kind === "GUEST" ? (
          <Button label={t("settings.sign_in")} onPress={() => router.push("/account")} />
        ) : null}
        {active ? (
          <>
            <Button tone="secondary" label={t("settings.sign_out")} disabled={busy}
                    onPress={() => void attempt(async () => { await services.session.signOut(); router.replace("/"); })} />
            <Button tone="secondary" label={t("settings.sign_out_everywhere")} disabled={busy}
                    onPress={() => confirm(t("settings.sign_out_everywhere"), t("settings.sign_out_everywhere_confirm"), async () => {
                      await services.session.logoutEverywhere();
                      router.replace("/");
                    })} />
            <Button tone="danger" label={t("settings.delete_account")} disabled={busy}
                    onPress={() => confirm(t("settings.delete_account"),
                                           active.kind === "GUEST" ? t("settings.delete_guest_confirm") : t("settings.delete_confirm"),
                                           async () => {
                                             await services.session.deleteAccount();
                                             router.replace("/");
                                           })} />
          </>
        ) : null}
      </Card>

      {active ? (
        <Card>
          <Heading>{t("settings.privacy")}</Heading>
          <Toggle label={t("settings.retain_all")} hint={t("settings.retain_hint")} value={retainAll === true}
                  disabled={retainAll === null || busy} onChange={(value) => void changeRetention(value)} />
        </Card>
      ) : null}

      {active ? (
        <Card>
          <Heading>{t("settings.notifications")}</Heading>
          <Toggle label={t("settings.push")} value={push === "REGISTERED"} disabled={busy || push === null}
                  onChange={(value) => void attempt(async () => {
                    if (value) setPush(await services.push.enable(active.principalId, locale));
                    else {
                      await services.push.forget(active.principalId);
                      setPush("NOT_REGISTERED");
                    }
                  })} />
          {push === "DENIED" ? <Body muted>{t("settings.push_denied")}</Body> : null}
          {push === "UNAVAILABLE" ? <Body muted>{t("settings.push_unavailable")}</Body> : null}
          {push === "FAILED" ? <Body muted>{t("settings.push_failed")}</Body> : null}
          {active.kind === "ACCOUNT" ? (
            <Toggle label={t("settings.mail")} value={mail === true} disabled={mail === null || busy}
                    onChange={(value) => void attempt(async () => {
                      const prefs = await services.api.setNotificationPreferences({ mail_report_ready: value, locale });
                      setMail(prefs.mail_report_ready);
                    })} />
          ) : <Body muted>{t("settings.mail_account_only")}</Body>}
        </Card>
      ) : null}

      <Card>
        <Heading>{t("settings.display")}</Heading>
        <Choice label={t("settings.language")} value={preferences.locale}
                onChange={(value) => void setPreferences({ locale: value })}
                options={(["system", "en", "sv"] as const).map((value) => ({ value, label: t(`settings.language.${value}`) }))} />
        <Choice label={t("settings.theme")} value={preferences.theme}
                onChange={(value) => void setPreferences({ theme: value })}
                options={(["system", "light", "dark"] as const).map((value) => ({ value, label: t(`settings.theme.${value}`) }))} />
      </Card>

      <Card>
        <Heading>{t("settings.about")}</Heading>
        <KeyValue label={t("settings.variant")} value={config.variant} />
        <KeyValue label={t("settings.backend")} value={config.backendEnvironment} />
      </Card>
    </Screen>
  );
}
