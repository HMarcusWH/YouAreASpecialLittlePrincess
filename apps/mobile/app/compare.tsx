import { ApiError } from "@princess/api-client";
import { useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { Text, View } from "react-native";

import { useApp } from "../src/bootstrap/AppProvider.tsx";
import { presentComparison, type ComparisonView } from "../src/features/comparison.ts";
import { Banner, Body, Busy, Card, Heading, KeyValue, Screen, styles } from "../src/ui/components.tsx";

function Bar({ from, to, color, second }: { from: number; to: number; color: string; second: string }) {
  // Both values on the feature's fixed display domain: no per-person rescaling.
  return (
    <View aria-hidden style={{ height: 14, justifyContent: "center" }}>
      <View style={{ height: 2, backgroundColor: color, opacity: 0.3 }} />
      <View style={{ position: "absolute", left: `${from * 100}%`, width: 10, height: 10, marginLeft: -5,
                     borderRadius: 5, backgroundColor: color }} />
      <View style={{ position: "absolute", left: `${to * 100}%`, width: 10, height: 10, marginLeft: -5,
                     borderWidth: 2, borderColor: second }} />
    </View>
  );
}

export default function Compare() {
  const { ids } = useLocalSearchParams<{ ids?: string }>();
  const { t, services, locale, theme } = useApp();
  const [view, setView] = useState<ComparisonView | "unavailable" | "failed" | null>(null);
  const reportIds = String(ids ?? "").split(",").filter(Boolean).slice(0, 16);

  useEffect(() => {
    let alive = true;
    const kind = reportIds.length === 2 ? "PAIR" : "HISTORY";
    services.api.compare(kind, reportIds).then((comparison) => {
      if (alive) setView(presentComparison(comparison, locale));
    }).catch((error: unknown) => {
      if (alive) setView(error instanceof ApiError && error.status === 501 ? "unavailable" : "failed");
    });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the selection is fixed for this screen
  }, [ids, locale, services]);

  if (view === null) return <Screen title={t("compare.title")}><Busy label={t("app.loading")} /></Screen>;
  if (view === "unavailable" || view === "failed") {
    return <Screen title={t("compare.title")}><Banner tone="attention">{t(`compare.${view}`)}</Banner></Screen>;
  }
  const formatter = new Intl.DateTimeFormat(locale === "sv" ? "sv-SE" : "en-GB", { dateStyle: "medium", timeStyle: "short" });
  return (
    <Screen title={t("compare.title")}>
      <Body muted>{t("compare.intro")}</Body>
      <KeyValue label={t("compare.coverage")} value={`${view.commonCount} / ${view.candidateCount}`} />
      <Card>
        {view.inputs.map((input, index) => (
          <KeyValue key={input.reportId} label={`${index === 0 ? t("compare.from") : `#${index + 1}`} · ${t("history.revision")} ${input.revision}`}
                    value={formatter.format(new Date(input.createdAt))} />
        ))}
        <Body muted>{t("history.created_hint")}</Body>
      </Card>
      {view.rows.length === 0 ? <Banner tone="info">{t("compare.none")}</Banner> : null}
      {view.rows.map((row) => (
        <View key={row.featureId} accessible
              accessibilityLabel={`${row.label}: ${t("compare.from")} ${row.from}, ${t("compare.to")} ${row.to}, ${t("compare.difference")} ${row.delta}`}
              style={{ gap: 6, borderTopWidth: 1, borderColor: theme.color.border, paddingVertical: 10 }}>
          <Text style={[styles.copy, { color: theme.color.text, fontFamily: theme.serif }]}>{row.label}</Text>
          <Bar from={row.fromPosition} to={row.toPosition} color={theme.chart[0] ?? theme.color.accent}
               second={theme.chart[1] ?? theme.color.text} />
          <Text style={[styles.small, { color: theme.color["text-muted"], fontFamily: theme.mono }]}>
            {row.from} → {row.to} ({row.delta})
          </Text>
        </View>
      ))}
      {view.exclusions.length > 0 ? (
        <Card>
          <Heading level={3}>{t("compare.excluded")}</Heading>
          {view.exclusions.map((group) => (
            <KeyValue key={group.reason} label={t(`compare.reason.${group.reason}`)} value={String(group.featureIds.length)} />
          ))}
        </Card>
      ) : null}
    </Screen>
  );
}
