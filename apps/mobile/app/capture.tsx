import { router } from "expo-router";
import { useState } from "react";
import { Linking } from "react-native";

import { useApp } from "../src/bootstrap/AppProvider.tsx";
import type { CaptureOutcome } from "../src/platform/contracts.ts";
import { Banner, Body, Busy, Button, Screen } from "../src/ui/components.tsx";

type Message = { tone: "info" | "attention" | "danger"; text: string; settings?: boolean };

export default function Capture() {
  const { t, services, setDraft, draft } = useApp();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<Message | null>(null);

  async function run(source: "camera" | "library") {
    setBusy(true);
    setMessage(null);
    try {
      const outcome: CaptureOutcome = source === "camera"
        ? await services.ports.capture.takePhoto() : await services.ports.capture.pickPhoto();
      if (outcome.status === "CANCELLED") return setMessage({ tone: "info", text: t("capture.cancelled") });
      if (outcome.status === "DENIED") {
        return setMessage({ tone: "attention", text: t("capture.camera_denied"), settings: !outcome.canAskAgain });
      }
      if (outcome.status === "UNAVAILABLE") return setMessage({ tone: "attention", text: t("capture.camera_unavailable") });
      if (outcome.status === "FAILED") return setMessage({ tone: "danger", text: t("capture.failed") });
      const prepared = await services.ports.preparer.normalize(outcome.image);
      if (!prepared.ok) {
        const key = prepared.code === "image_too_small" ? "review.too_small"
          : prepared.code === "image_too_large" ? "review.too_large" : "review.unreadable";
        return setMessage({ tone: "danger", text: t(key) });
      }
      if (draft !== null) await services.ports.preparer.discard(draft.uri);
      setDraft(prepared.image);
      router.push("/review");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen title={t("capture.title")}>
      <Body muted>{t("capture.intro")}</Body>
      <Body muted>{t("capture.local_only")}</Body>
      {message ? (
        <Banner tone={message.tone} action={message.settings ? (
          <Button tone="secondary" label={t("capture.open_settings")} onPress={() => void Linking.openSettings()} />
        ) : undefined}>{message.text}</Banner>
      ) : null}
      {busy ? <Busy label={t("capture.preparing")} /> : null}
      <Button label={t("capture.take")} disabled={busy} onPress={() => void run("camera")} />
      <Button tone="secondary" label={t("capture.choose")} disabled={busy} onPress={() => void run("library")} />
    </Screen>
  );
}
