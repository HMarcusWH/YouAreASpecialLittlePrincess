import type { ConsentNotice } from "@princess/api-client";
import { router } from "expo-router";
import { useEffect, useState } from "react";
import { useWindowDimensions, View } from "react-native";

import { useApp } from "../src/bootstrap/AppProvider.tsx";
import type { CropRect } from "../src/platform/contracts.ts";
import { Banner, Body, Busy, Button, Paper, SectionLabel, KeyValue, Screen, Toggle } from "../src/ui/components.tsx";
import { CropView } from "../src/ui/crop.tsx";

export default function Review() {
  const { t, services, draft, setDraft, session, locale } = useApp();
  const { height } = useWindowDimensions();
  const [crop, setCrop] = useState<CropRect | null>(null);
  const [cropping, setCropping] = useState(false);
  const [cropKey, setCropKey] = useState(0);
  const [notice, setNotice] = useState<ConsentNotice | null | "error">(null);
  const [agreed, setAgreed] = useState(false);
  const [retain, setRetain] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    // The exact notice text and version the server accepts; nothing is sent without it.
    services.api.consentNotices(locale).then((notices) => {
      if (alive) setNotice(notices.find((n) => n.purposes.some((p) => p.purpose_id === "service_processing")) ?? "error");
    }).catch(() => { if (alive) setNotice("error"); });
    return () => { alive = false; };
  }, [services, locale]);

  if (draft === null) {
    return (
      <Screen title={t("review.title")}>
        <Button label={t("review.retake")} onPress={() => router.replace("/capture")} />
      </Screen>
    );
  }
  const image = draft;
  const service = notice && notice !== "error" ? notice.purposes.find((p) => p.purpose_id === "service_processing") : undefined;
  const retention = notice && notice !== "error" ? notice.purposes.find((p) => p.purpose_id === "image_retention") : undefined;
  const accepted = notice !== null && notice !== "error" && notice.accepted_for_use && service !== undefined ? notice : null;
  const usable = accepted !== null;

  async function rotate() {
    setBusy(true);
    const rotated = await services.ports.preparer.rotate(image, 1);
    setBusy(false);
    if (!rotated.ok) return setError(t("review.unreadable"));
    await services.ports.preparer.discard(image.uri);
    setCrop(null);
    setDraft(rotated.image);
  }

  async function submit() {
    if (session.status !== "ACTIVE" || accepted === null) return;
    setBusy(true);
    setError(null);
    try {
      const final = await services.ports.preparer.finalize(image, cropping ? crop : null);
      if (!final.ok) {
        setError(t(final.code === "image_too_small" ? "review.too_small"
          : final.code === "image_too_large" ? "review.too_large" : "review.unreadable"));
        return;
      }
      const entry = await services.workflow.create(session.principalId, final.image, accepted.notice_version,
                                                   { retainImage: retain });
      if (final.image.uri !== image.uri) await services.ports.preparer.discard(image.uri);
      setDraft(null);
      services.runner.kick();
      router.replace(`/work/${entry.opId}`);
    } catch {
      setError(t("common.error"));
    } finally {
      setBusy(false);
    }
  }

  async function discard() {
    await services.ports.preparer.discard(image.uri);
    setDraft(null);
    router.replace("/");
  }

  return (
    <Screen title={t("review.title")} footer={
      <View style={{ gap: 8 }}>
        {busy ? <Busy label={t("review.submitting")} /> : null}
        <Button label={t("review.submit")} disabled={!agreed || !usable || busy} onPress={() => void submit()} />
      </View>
    }>
      <CropView key={cropKey} image={image} enabled={cropping} maxHeight={height * 0.5} onChange={setCrop}
                labels={{ tl: `${t("review.crop_on")} ↖`, tr: `${t("review.crop_on")} ↗`, bl: `${t("review.crop_on")} ↙`,
                          br: `${t("review.crop_on")} ↘` }} />
      <KeyValue label={t("review.dimensions")} value={`${crop?.width ?? image.width} × ${crop?.height ?? image.height} px`} />
      <View style={{ flexDirection: "row", gap: 12, flexWrap: "wrap" }}>
        <Button tone="secondary" label={t("review.rotate")} disabled={busy} onPress={() => void rotate()} />
        <Button tone="secondary" label={cropping ? t("review.crop_reset") : t("review.crop_on")} disabled={busy}
                onPress={() => { setCropping(!cropping); setCrop(null); setCropKey(cropKey + 1); }} />
      </View>
      {cropping ? <Body muted>{t("review.crop_hint")}</Body> : null}
      <Paper>
        <SectionLabel>{t("review.consent_title")}</SectionLabel>
        {notice === null ? <Busy label={t("app.loading")} /> : null}
        {notice === "error" ? <Banner tone="danger">{t("review.notice_unavailable")}</Banner> : null}
        {notice !== null && notice !== "error" && notice.status === "DRAFT" ? (
          <Banner tone="attention">{t("review.notice_draft")}</Banner>
        ) : null}
        {notice !== null && notice !== "error" && !notice.accepted_for_use ? (
          <Banner tone="danger">{t("review.notice_not_accepted")}</Banner>
        ) : null}
        {service ? (
          <>
            <Toggle label={service.label} hint={`${service.explanation} ${service.decline_consequence}`} value={agreed}
                    onChange={setAgreed} />
            {retention ? <Toggle label={retention.label} hint={`${retention.explanation} ${retention.decline_consequence}`}
                                 value={retain} onChange={setRetain} /> : null}
          </>
        ) : null}
      </Paper>
      {error ? <Banner tone="danger">{error}</Banner> : null}
      <Button tone="secondary" label={t("review.retake")} disabled={busy} onPress={() => router.replace("/capture")} />
      <Button tone="danger" label={t("review.discard")} disabled={busy} onPress={() => void discard()} />
    </Screen>
  );
}
