import { ApiError, PayloadError, TransportError, type PrincessApi } from "@princess/api-client";
import type { EvidenceBundle, ReportViewModel } from "@princess/contracts";
import { buildDossier, t as reportText } from "@princess/report-core";
import { router, useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useState } from "react";
import { Alert, useWindowDimensions, View } from "react-native";

import { useApp } from "../../../src/bootstrap/AppProvider.tsx";
import { paperFor, type ExportPhase } from "../../../src/features/exports.ts";
import type { PremiumState } from "../../../src/features/premium.ts";
import { Banner, Body, Busy, Button, Card, Heading, Screen } from "../../../src/ui/components.tsx";
import { DossierView, EvidencePanel, SourceImage } from "../../../src/ui/dossier.tsx";
import { PremiumOverlay } from "../../../src/ui/premium.tsx";
import { WIDE_LAYOUT } from "../../../src/ui/theme.ts";

type Loaded = { view: ReportViewModel; evidence: EvidenceBundle | null; evidenceUnreadable: boolean };

/** Evidence may fail its integrity checks without hiding a validated report (same rule as web). */
async function loadReport(api: PrincessApi, reportId: string): Promise<Loaded> {
  const view = await api.report(reportId, "OWNER");
  try {
    return { view, evidence: await api.reportEvidence(reportId), evidenceUnreadable: false };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return { view, evidence: null, evidenceUnreadable: false };
    if (error instanceof PayloadError || (error instanceof ApiError
        && ((error.status === 409 && error.code === "stored_evidence_invalid")
            || (error.status === 502 && error.code === "evidence_lineage_invalid")))) {
      return { view, evidence: null, evidenceUnreadable: true };
    }
    throw error;
  }
}

export default function Report() {
  const { reportId } = useLocalSearchParams<{ reportId: string }>();
  const id = String(reportId);
  const { t, services, session, locale, exports, premium } = useApp();
  const { width } = useWindowDimensions();
  const [loaded, setLoaded] = useState<Loaded | "unavailable" | "error" | null>(null);
  const [premiumState, setPremiumState] = useState<PremiumState | null>(null);
  const [exporting, setExporting] = useState<ExportPhase | null>(null);
  const [deleted, setDeleted] = useState(false);

  const load = useCallback(async () => {
    try {
      const result = await services.session.guard(loadReport(services.api, id));
      if (result === null) return;
      setLoaded(result);
      if (session.status === "ACTIVE") {
        const state = await services.session.guard(premium.load(result.view, session.kind)).catch(() => null);
        setPremiumState(state);
      }
    } catch (error) {
      // A link or notice selects a report; authorization is decided here, on every open.
      setLoaded(error instanceof ApiError && (error.status === 404 || error.status === 403) ? "unavailable" : "error");
    }
  }, [services, id, session, premium]);

  useFocusEffect(useCallback(() => { void load(); }, [load]));

  if (deleted) {
    return (
      <Screen title={t("report.title")}>
        <Banner tone="ready">{t("report.deleted")}</Banner>
        <Button label={t("home.reports")} onPress={() => router.replace("/reports")} />
      </Screen>
    );
  }
  if (loaded === null) return <Screen title={t("report.title")}><Busy label={t("report.loading")} /></Screen>;
  if (loaded === "unavailable" || loaded === "error") {
    return (
      <Screen title={t("report.title")}>
        <Banner tone={loaded === "error" ? "danger" : "attention"}>
          {loaded === "error" ? t("common.error") : t("report.unavailable")}
        </Banner>
        {loaded === "error" ? <Button label={t("common.retry")} onPress={() => void load()} /> : null}
        <Button tone="secondary" label={t("common.back_home")} onPress={() => router.replace("/")} />
      </Screen>
    );
  }
  const { view, evidence, evidenceUnreadable } = loaded;
  const model = buildDossier(view, locale);
  // Deletion and comparison have native report-scoped flows below; the action list keeps the server's other verdicts.
  const shown = { ...model, actions: model.actions.filter((a) => a.kind !== "DELETE" && a.kind !== "COMPARE") };
  const wide = width >= WIDE_LAYOUT;

  async function exportPdf() {
    setExporting({ status: "PREPARING" });
    const phase = await exports.prepare(id, paperFor(Intl.DateTimeFormat().resolvedOptions().locale));
    setExporting(phase);
  }

  async function share() {
    if (exporting?.status !== "READY") return;
    await exports.shareAndClean(exporting.file);
    setExporting(null);
  }

  function onAction(kind: string) {
    if (kind === "EXPORT") void exportPdf();
    if (kind === "PURCHASE") router.push(`/reports/${encodeURIComponent(id)}/premium`);
  }

  function confirmDelete() {
    Alert.alert(t("report.delete"), t("report.delete_confirm"), [
      { text: t("common.cancel"), style: "cancel" },
      { text: t("report.delete"), style: "destructive", onPress: () => {
        void services.api.deleteReport(id).then(() => setDeleted(true)).catch((error: unknown) => {
          Alert.alert(error instanceof TransportError ? t("common.offline") : t("common.error"));
        });
      } },
    ]);
  }

  const evidenceBlock = (
    <View style={{ gap: 16 }}>
      {view.authorized_asset_ids.length > 0 ? <SourceImage reportId={id} bundle={evidence} locale={locale} /> : (
        <Body muted>{reportText(locale, "image.unavailable")}</Body>
      )}
      {evidenceUnreadable ? <Banner tone="danger">{t("report.evidence_unreadable")}</Banner> : null}
      {evidence ? <EvidencePanel bundle={evidence} locale={locale} /> : null}
    </View>
  );

  return (
    <Screen>
      <View style={{ flexDirection: wide ? "row" : "column", gap: 24, alignItems: "flex-start" }}>
        <View style={{ flex: wide ? 3 : undefined, width: wide ? undefined : "100%", gap: 16 }}>
          <DossierView model={shown} onAction={onAction} busyAction={exporting?.status === "PREPARING" ? "EXPORT" : null} />
          {exporting?.status === "PREPARING" ? <Busy label={t("report.export_preparing")} /> : null}
          {exporting?.status === "READY" ? (
            <Card>
              <Body>{t("report.export_ready")}</Body>
              <Button label={t("report.export_share")} onPress={() => void share()} />
              <Body muted>{t("report.export_not_recallable")}</Body>
            </Card>
          ) : null}
          {exporting && (exporting.status === "FAILED" || exporting.status === "TIMEOUT") ? (
            <Banner tone="danger">{t("report.export_failed")}</Banner>
          ) : null}
          {exporting?.status === "REVOKED" ? <Banner tone="attention">{t("report.export_revoked")}</Banner> : null}
          {exporting?.status === "UNAVAILABLE" ? <Banner tone="info">{t("report.export_unavailable")}</Banner> : null}
          {premiumState?.status === "SAVED" ? <PremiumOverlay content={premiumState.content} facts={view.facts} locale={locale} /> : null}
          {premiumState?.status === "REVOKED" ? <Banner tone="info">{t("premium.revoked")}</Banner> : null}
          {premiumState && premiumState.status !== "SAVED" && premiumState.status !== "REVOKED"
           && premiumState.status !== "NOT_OFFERED" ? (
            <Card>
              <Heading>{t("premium.title")}</Heading>
              <Button tone="secondary" label={t("premium.title")}
                      onPress={() => router.push(`/reports/${encodeURIComponent(id)}/premium`)} />
            </Card>
          ) : null}
        </View>
        <View style={{ flex: wide ? 2 : undefined, width: wide ? undefined : "100%", gap: 16 }}>
          {evidenceBlock}
          <Button tone="secondary" label={t("report.compare")}
                  onPress={() => router.push({ pathname: "/reports", params: { select: id } })} />
          <Button tone="secondary" label={t("report.feedback")}
                  onPress={() => router.push(`/reports/${encodeURIComponent(id)}/feedback`)} />
          <Button tone="danger" label={t("report.delete")} onPress={confirmDelete} />
        </View>
      </View>
    </Screen>
  );
}
