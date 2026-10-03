import { ApiError } from "@princess/api-client";
import type { ReportViewModel } from "@princess/contracts";
import { router, useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";

import { useApp } from "../../../src/bootstrap/AppProvider.tsx";
import type { BuyOutcome, Offer } from "../../../src/features/commerce.ts";
import type { PremiumState } from "../../../src/features/premium.ts";
import { Banner, Body, Busy, Button, Card, Heading, KeyValue, Screen } from "../../../src/ui/components.tsx";
import { PremiumOverlay } from "../../../src/ui/premium.tsx";

const OUTCOME_COPY: Partial<Record<BuyOutcome["status"], string>> = {
  STORE_UNAVAILABLE: "premium.store_unavailable", CANCELLED: "premium.cancelled", PENDING: "premium.pending",
  VERIFYING: "premium.verifying", NOT_GRANTED: "premium.not_granted", GRANTED: "premium.granted",
  SALES_CLOSED: "premium.sales_closed", ACCOUNT_REQUIRED: "premium.account_required", FAILED: "common.error",
};

export default function Premium() {
  const { reportId } = useLocalSearchParams<{ reportId: string }>();
  const id = String(reportId);
  const { t, services, session, locale, premium, purchases } = useApp();
  const [view, setView] = useState<ReportViewModel | null>(null);
  const [state, setState] = useState<PremiumState | null>(null);
  const [offers, setOffers] = useState<readonly Offer[] | string | null>(null);
  const [outcome, setOutcome] = useState<BuyOutcome | null>(null);
  const [busy, setBusy] = useState(false);
  const polling = useRef(false);
  const kind = session.status === "ACTIVE" ? session.kind : "GUEST";

  const load = useCallback(async () => {
    try {
      const report = await services.api.report(id, "OWNER");
      setView(report);
      setState(await premium.load(report, kind));
    } catch (error) {
      setState({ status: "FAILED", code: error instanceof ApiError ? error.code : "unavailable" });
    }
  }, [services, id, premium, kind]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (state?.status !== "NEEDS_CREDIT") return;
    void purchases.offers().then((result) => setOffers(result.status === "OK" ? result.offers : result.status))
      .catch(() => setOffers("STORE_UNAVAILABLE"));
  }, [state?.status, purchases]);

  // Store updates that complete later (Ask to Buy, pending payment) refresh the offer state.
  useEffect(() => purchases.onOutcome((result) => {
    setOutcome(result);
    if (result.status === "GRANTED") void load();
  }), [purchases, load]);

  useEffect(() => {
    if (state?.status !== "GENERATING" || polling.current) return;
    polling.current = true;
    let alive = true;
    const jobId = state.jobId;
    void (async () => {
      for (let attempt = 0; alive && attempt < 60; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, Math.min(8000, 1000 * 2 ** Math.min(attempt, 3))));
        const next = await premium.poll(id, jobId).catch(() => null);
        if (!alive || next === null) continue;
        if (next.status !== "GENERATING") {
          setState(next);
          break;
        }
      }
      polling.current = false;
    })();
    return () => { alive = false; polling.current = false; };
  }, [state, premium, id]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  }

  if (state === null || view === null && state.status !== "FAILED") {
    return <Screen title={t("premium.title")}><Busy label={t("app.loading")} /></Screen>;
  }
  const credits = "credits" in state && state.credits ? state.credits : null;

  return (
    <Screen title={t("premium.title")}>
      {state.status === "SAVED" && view ? <PremiumOverlay content={state.content} facts={view.facts} locale={locale} /> : null}
      {state.status === "REVOKED" ? <Banner tone="info">{t("premium.revoked")}</Banner> : null}
      {state.status === "NOT_OFFERED" ? <Banner tone="info">{t("premium.not_offered")}</Banner> : null}
      {state.status === "ACCOUNT_REQUIRED" ? (
        <Banner tone="attention" action={<Button label={t("home.sign_in")} onPress={() => router.push("/account")} />}>
          {t("premium.account_required")}
        </Banner>
      ) : null}
      {state.status === "NO_IMAGE" ? <Banner tone="info">{t("premium.no_image")}</Banner> : null}
      {credits ? <KeyValue label={t("premium.credits")} value={String(credits.available)} /> : null}
      {state.status === "NEEDS_PERMISSION" ? (
        <Card>
          <Heading>{t("premium.title")}</Heading>
          <Body>{t("premium.disclosure")}</Body>
          <Button label={t("premium.agree")} busy={busy} onPress={() => void run(async () => {
            const notices = await services.api.consentNotices(locale);
            const notice = notices.find((n) => n.accepted_for_use
              && n.purposes.some((p) => p.purpose_id === "third_party_ai_processing"));
            if (!notice) return setState({ status: "NOT_OFFERED", reason: "notice_not_accepted" });
            await premium.grantPermission(id, notice.notice_version);
            await load();
          })} />
        </Card>
      ) : null}
      {state.status === "NEEDS_CREDIT" ? (
        <Card>
          {offers === null ? <Busy label={t("app.loading")} /> : null}
          {typeof offers === "string" ? (
            <Banner tone="info">{t(offers === "NO_PRODUCTS" ? "premium.no_products" : offers === "SALES_CLOSED"
              ? "premium.sales_closed" : offers === "ACCOUNT_REQUIRED" ? "premium.account_required" : "premium.store_unavailable")}</Banner>
          ) : null}
          {Array.isArray(offers) ? offers.map((offer) => (
            <Button key={offer.productId} label={`${t("premium.buy")} · ${offer.title} · ${offer.displayPrice}`} busy={busy}
                    onPress={() => void run(async () => {
                      const result = await purchases.buy(offer);
                      setOutcome(result);
                      if (result.status === "GRANTED") await load();
                    })} />
          )) : null}
        </Card>
      ) : null}
      {outcome && OUTCOME_COPY[outcome.status] ? (
        <Banner tone={outcome.status === "GRANTED" ? "ready" : outcome.status === "CANCELLED" ? "info" : "attention"}>
          {t(OUTCOME_COPY[outcome.status]!)}
        </Banner>
      ) : null}
      {state.status === "READY" ? (
        <Card>
          <Body>{t("premium.disclosure")}</Body>
          <Button label={t("premium.generate")} busy={busy} onPress={() => void run(async () => {
            setState(await premium.request(id));
          })} />
        </Card>
      ) : null}
      {state.status === "GENERATING" ? <Busy label={t("premium.generating")} /> : null}
      {state.status === "FAILED" ? <Banner tone="danger">{t("premium.failed")}</Banner> : null}
      {state.status === "UNKNOWN" ? (
        <Banner tone="attention" action={<Button tone="secondary" label={t("premium.check_again")} onPress={() => void load()} />}>
          {t("premium.unknown")}
        </Banner>
      ) : null}
    </Screen>
  );
}
