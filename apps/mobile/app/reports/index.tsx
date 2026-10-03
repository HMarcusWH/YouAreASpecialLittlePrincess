import { ApiError } from "@princess/api-client";
import { router, useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { useApp } from "../../src/bootstrap/AppProvider.tsx";
import { HistoryController, type HistoryState } from "../../src/features/history.ts";
import { Banner, Body, Busy, Button, Card, Heading, Screen, styles } from "../../src/ui/components.tsx";
import { SelectableRow } from "../../src/ui/dossier.tsx";

export default function History() {
  const { select } = useLocalSearchParams<{ select?: string }>();
  const { t, services, session, theme, locale } = useApp();
  const controller = useRef(new HistoryController(services.api)).current;
  const [state, setState] = useState<HistoryState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [selecting, setSelecting] = useState(typeof select === "string");
  const [selected, setSelected] = useState<readonly string[]>(typeof select === "string" ? [select] : []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setError(null);
    try {
      const next = await services.session.guard(controller.refresh());
      if (next) setState(next);
    } catch (e) {
      setError(e instanceof ApiError && e.status === 401 ? t("home.signed_out_expired") : t("common.error"));
    } finally {
      setRefreshing(false);
    }
  }, [controller, services, t]);

  useFocusEffect(useCallback(() => { void refresh(); }, [refresh]));

  if (session.status !== "ACTIVE") {
    return <Screen title={t("history.title")}><Button label={t("common.back_home")} onPress={() => router.replace("/")} /></Screen>;
  }
  const formatter = new Intl.DateTimeFormat(locale === "sv" ? "sv-SE" : "en-GB", { dateStyle: "medium", timeStyle: "short" });
  const toggle = (id: string) => setSelected(selected.includes(id) ? selected.filter((s) => s !== id)
    : selected.length < 16 ? [...selected, id] : selected);

  return (
    <Screen title={t("history.title")} refreshing={refreshing} onRefresh={() => void refresh()} footer={selecting ? (
      <View style={{ gap: 8 }}>
        <Body muted>{t("history.compare_select")}</Body>
        <Button label={`${t("history.compare_go")} (${selected.length})`} disabled={selected.length < 2}
                onPress={() => router.push({ pathname: "/compare", params: { ids: selected.join(",") } })} />
        <Button tone="secondary" label={t("common.cancel")} onPress={() => { setSelecting(false); setSelected([]); }} />
      </View>
    ) : undefined}>
      {error ? <Banner tone="danger" action={<Button tone="secondary" label={t("common.retry")} onPress={() => void refresh()} />}>{error}</Banner> : null}
      {state === null && !error ? <Busy label={t("app.loading")} /> : null}
      {state && state.inProgress.length > 0 ? (
        <Banner tone="info">{`${t("home.elsewhere")}: ${state.inProgress.length}. ${t("home.elsewhere_hint")}`}</Banner>
      ) : null}
      {state && state.items.length === 0 ? (
        <Card>
          <Body>{t("history.empty")}</Body>
          <Button label={t("home.analyse")} onPress={() => router.push("/capture")} />
        </Card>
      ) : null}
      {state && state.items.length > 1 && !selecting ? (
        <Button tone="secondary" label={t("history.compare")} onPress={() => setSelecting(true)} />
      ) : null}
      {state ? <Body muted>{t("history.created_hint")}</Body> : null}
      {state?.items.map((item) => {
        const created = `${t("history.created")} ${formatter.format(new Date(item.created_at))}`;
        const title = `${t(`history.kind.${item.kind}`)} · ${t("history.revision")} ${item.revision}`;
        const body = (
          <View style={{ gap: 2 }}>
            <Heading level={3}>{title}</Heading>
            <Text style={[styles.small, { color: theme.color["text-muted"], fontFamily: theme.mono }]}>{created}</Text>
            {item.deletion === "REQUESTED" ? (
              <Text style={[styles.small, { color: theme.color["state-attention"] }]}>{t("history.deletion_requested")}</Text>
            ) : null}
          </View>
        );
        if (item.deletion === "REQUESTED") return <Card key={item.report_id}>{body}</Card>;
        return selecting ? (
          <SelectableRow key={item.report_id} label={`${title}, ${created}`} selected={selected.includes(item.report_id)}
                         onPress={() => toggle(item.report_id)}>{body}</SelectableRow>
        ) : (
          <Pressable key={item.report_id} accessibilityRole="link" accessibilityLabel={`${title}, ${created}`}
                     onPress={() => router.push(`/reports/${encodeURIComponent(item.report_id)}`)}>
            <Card>{body}</Card>
          </Pressable>
        );
      })}
      {state?.nextCursor ? (
        <Button tone="secondary" label={t("history.more")}
                onPress={() => void controller.more().then(setState).catch(() => setError(t("common.error")))} />
      ) : null}
    </Screen>
  );
}
