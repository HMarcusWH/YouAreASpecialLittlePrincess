import { router, useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { Alert, Text, View } from "react-native";

import { useApp } from "../../src/bootstrap/AppProvider.tsx";
import { Banner, Body, Busy, Button, KeyValue, Paper, Screen, SectionLabel, styles } from "../../src/ui/components.tsx";
import { TERMINAL_PHASES, type WorkEntry, type WorkPhase } from "../../src/work/journal.ts";

const STEPS: readonly WorkPhase[] = ["PREPARED", "RESERVED", "UPLOADED", "COMPLETED", "PERMITTED", "STARTED", "SUCCEEDED"];

const BLOCKER_COPY: Record<string, string> = {
  network: "work.waiting_network",
  signin_required: "work.signin_required",
  permission_not_granted: "work.permission_not_granted",
  notice_not_accepted: "work.notice_not_accepted",
  local_file_missing: "work.local_file_missing",
  local_file_changed: "work.local_file_changed",
  upload_quota_exceeded: "work.upload_quota_exceeded",
  too_many_active_analyses: "work.too_many_active_analyses",
  uploads_disabled: "work.uploads_disabled",
};

export default function WorkStatus() {
  const { opId } = useLocalSearchParams<{ opId: string }>();
  const { t, services, session, work, theme, locale } = useApp();
  const [entry, setEntry] = useState<WorkEntry | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const principalId = session.status === "ACTIVE" ? session.principalId : null;

  useEffect(() => {
    const live = work.find((e) => e.opId === opId);
    if (live) return setEntry(live);
    if (principalId === null) return setEntry(null);
    void services.journal.get(principalId, String(opId)).then(setEntry);
  }, [work, opId, principalId, services]);

  useEffect(() => {
    if (entry?.phase === "SUCCEEDED" && entry.reportId) router.replace(`/reports/${entry.reportId}`);
  }, [entry?.phase, entry?.reportId]);

  if (entry === undefined) return <Screen title={t("work.title")}><Busy label={t("app.loading")} /></Screen>;
  if (entry === null || principalId === null) {
    return (
      <Screen title={t("work.title")}>
        <Banner tone="attention">{t("report.unavailable")}</Banner>
        <Button label={t("common.back_home")} onPress={() => router.replace("/")} />
      </Screen>
    );
  }
  const current = entry;
  const owner = principalId;
  const index = STEPS.indexOf(current.phase);
  const terminal = TERMINAL_PHASES.has(current.phase);

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      services.runner.kick();
    } catch {
      Alert.alert(t("common.error"));
    } finally {
      setBusy(false);
    }
  }

  function confirmCancel() {
    Alert.alert(t("work.cancel"), t("work.cancel_confirm"), [
      { text: t("common.cancel"), style: "cancel" },
      { text: t("common.confirm"), style: "destructive",
        onPress: () => void act(() => services.workflow.cancel(owner, current.opId)) },
    ]);
  }

  async function reconsent() {
    // Show the current notice again; the user confirms on the review of the notice text.
    const notices = await services.api.consentNotices(locale);
    const notice = notices.find((n) => n.accepted_for_use && n.purposes.some((p) => p.purpose_id === "service_processing"));
    if (!notice) return Alert.alert(t("review.notice_not_accepted"));
    const service = notice.purposes.find((p) => p.purpose_id === "service_processing")!;
    Alert.alert(service.label, `${service.explanation}\n\n${service.decline_consequence}`, [
      { text: t("common.cancel"), style: "cancel" },
      { text: t("common.confirm"),
        onPress: () => void act(() => services.workflow.reconsent(owner, current.opId, notice.notice_version)) },
    ]);
  }

  const blockerKey = current.errorCode ? BLOCKER_COPY[current.errorCode] : undefined;
  return (
    <Screen title={t(`work.${current.phase}`)}>
      <Paper>
        <SectionLabel>{t("work.title")}</SectionLabel>
        {STEPS.slice(0, -1).map((step, i) => {
          const done = index > i || current.phase === "SUCCEEDED";
          const active = index === i && !terminal;
          return (
            <View key={step} accessible accessibilityLabel={`${t(`work.${step}`)}${done ? " ✓" : active ? " …" : ""}`}
                  style={{ flexDirection: "row", gap: 12, alignItems: "center", minHeight: 32 }}>
              <Text aria-hidden style={{ color: done ? theme.color["state-ready"] : active ? theme.color.accent
                                                                                       : theme.color["text-muted"] }}>
                {done ? "✓" : active ? "●" : "○"}
              </Text>
              <Text style={[styles.copy, { color: active ? theme.color.text : theme.color["text-muted"],
                                           fontFamily: theme.serif }]}>{t(`work.${step}`)}</Text>
            </View>
          );
        })}
      </Paper>
      {!terminal && current.blocked === null ? <Busy label={t(`work.${current.phase}`)} /> : null}
      {!terminal && current.blocked === "RETRY" ? <Banner tone="attention">{t(blockerKey ?? "work.waiting_network")}</Banner> : null}
      {!terminal && current.blocked === "WAIT" ? <Banner tone="attention">{t(blockerKey ?? "work.waiting_server")}</Banner> : null}
      {!terminal && current.blocked === "USER" ? <Banner tone="danger">{t(blockerKey ?? "common.error")}</Banner> : null}
      {current.phase === "FAILED" ? (
        <Banner tone="danger">{blockerKey ? t(blockerKey) : `${t("work.FAILED")}. ${t("work.reason")}: ${current.errorCode ?? "—"}`}</Banner>
      ) : null}
      {!terminal ? <Body muted>{t("work.background_note")}</Body> : null}
      {current.reservations > 1 ? <KeyValue label={t("work.slots_used")} value={String(current.reservations)} /> : null}

      {current.phase === "SUCCEEDED" && current.reportId ? (
        <Button label={t("work.open_report")} onPress={() => router.replace(`/reports/${current.reportId}`)} />
      ) : null}
      {current.blocked === "USER" && current.errorCode === "signin_required" ? (
        <Button label={t("home.sign_in")} onPress={() => router.push("/account")} />
      ) : null}
      {current.blocked === "USER" && current.errorCode === "notice_not_accepted" ? (
        <Button label={t("work.review_notice")} busy={busy} onPress={() => void reconsent()} />
      ) : null}
      {!terminal && current.blocked !== "USER" ? (
        <Button tone="secondary" label={t("work.retry")} busy={busy}
                onPress={() => void act(() => services.workflow.retryNow(owner, current.opId))} />
      ) : null}
      {!terminal && current.runId !== null ? (
        <Button tone="danger" label={t("work.cancel")} disabled={busy} onPress={confirmCancel} />
      ) : null}
      {!terminal && current.runId === null ? (
        <Button tone="danger" label={t("work.discard")} disabled={busy}
                onPress={() => void act(() => services.workflow.discard(owner, current.opId))} />
      ) : null}
      {terminal && current.phase !== "SUCCEEDED" ? (
        <Button tone="secondary" label={t("home.analyse")} onPress={() => router.replace("/capture")} />
      ) : null}
    </Screen>
  );
}
