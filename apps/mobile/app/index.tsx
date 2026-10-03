import type { RunSummary } from "@princess/api-client";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { useApp } from "../src/bootstrap/AppProvider.tsx";
import { Banner, Body, Button, Card, Heading, Screen, styles } from "../src/ui/components.tsx";
import { TERMINAL_PHASES } from "../src/work/journal.ts";

function SignedOut() {
  const { t, services, session } = useApp();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reason = session.status === "SIGNED_OUT" ? session.reason : "fresh";
  async function startGuest() {
    setBusy(true);
    setError(null);
    try {
      await services.session.startGuest();
    } catch {
      setError(t("common.error"));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Screen eyebrow={t("app.name")} title={t("app.tagline")}>
      {reason === "expired" ? <Banner tone="attention">{t("home.signed_out_expired")}</Banner> : null}
      {reason === "deleted" ? <Banner tone="ready">{t("home.signed_out_deleted")}</Banner> : null}
      {reason === "logged_out_everywhere" ? <Banner tone="ready">{t("home.signed_out_everywhere")}</Banner> : null}
      <Body muted>{t("home.intro")}</Body>
      {error ? <Banner tone="danger">{error}</Banner> : null}
      <Button label={t("home.start_private")} busy={busy} onPress={() => void startGuest()}
              hint={t("home.start_private_hint")} />
      <Body muted>{t("home.start_private_hint")}</Body>
      <Button tone="secondary" label={t("home.sign_in")} onPress={() => router.push("/account")} />
    </Screen>
  );
}

export default function Home() {
  const { t, services, session, work, theme } = useApp();
  const [elsewhere, setElsewhere] = useState<readonly RunSummary[]>([]);

  useFocusEffect(useCallback(() => {
    if (session.status !== "ACTIVE") return undefined;
    let alive = true;
    services.runner.kick();
    // Server-side discovery: unfinished runs this device's journal does not know about.
    void services.session.guard(services.api.recentAnalyses(20)).then((runs) => {
      if (alive && runs) setElsewhere(runs.filter((run) => run.state === "QUEUED" || run.state === "RUNNING"));
    }).catch(() => undefined);
    return () => { alive = false; };
  }, [services, session.status]));

  if (session.status !== "ACTIVE") return <SignedOut />;
  const local = work.filter((entry) => !TERMINAL_PHASES.has(entry.phase) || entry.phase === "SUCCEEDED").slice(0, 6);
  const known = new Set(work.map((entry) => entry.runId).filter(Boolean));
  const remote = elsewhere.filter((run) => !known.has(run.run_id));

  return (
    <Screen eyebrow={t("app.name")} title={t("app.tagline")}>
      {session.kind === "GUEST" ? <Banner tone="info">{t("home.guest_banner")}</Banner> : null}
      {!session.verified ? <Banner tone="attention">{t("home.offline_banner")}</Banner> : null}
      <Body muted>{t("home.intro")}</Body>
      <Button label={t("home.analyse")} onPress={() => router.push("/capture")} />
      {local.length > 0 ? (
        <Card>
          <Heading>{t("home.in_progress")}</Heading>
          {local.map((entry) => (
            <Pressable key={entry.opId} accessibilityRole="link" onPress={() => router.push(`/work/${entry.opId}`)}
                       style={{ minHeight: 44, justifyContent: "center", gap: 2 }}>
              <Text style={[styles.copy, { color: theme.color.accent, fontFamily: theme.serif }]}>
                {t(`work.${entry.phase}`)}
              </Text>
              <Text style={[styles.small, { color: theme.color["text-muted"], fontFamily: theme.mono }]}>
                {new Date(entry.createdAt).toLocaleString()}
              </Text>
            </Pressable>
          ))}
        </Card>
      ) : null}
      {remote.length > 0 ? (
        <Card>
          <Heading>{t("home.elsewhere")}</Heading>
          <Body muted>{t("home.elsewhere_hint")}</Body>
          {remote.map((run) => (
            <View key={run.run_id} accessible style={{ minHeight: 44, justifyContent: "center" }}>
              <Text style={[styles.copy, { color: theme.color.text, fontFamily: theme.serif }]}>
                {t(run.state === "RUNNING" ? "work.STARTED" : "work.PERMITTED")}
              </Text>
            </View>
          ))}
        </Card>
      ) : null}
      <Button tone="secondary" label={t("home.reports")} onPress={() => router.push("/reports")} />
      <Button tone="secondary" label={t("home.settings")} onPress={() => router.push("/settings")} />
    </Screen>
  );
}
