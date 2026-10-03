import type { FeedbackCategory, FeedbackReceipt } from "@princess/api-client";
import { router, useLocalSearchParams } from "expo-router";
import { useRef, useState } from "react";

import { useApp } from "../../../src/bootstrap/AppProvider.tsx";
import { newClientId } from "../../../src/bootstrap/ids.ts";
import { MAX_COMMENT, normalizeComment, submitFeedback } from "../../../src/features/feedback.ts";
import { Banner, Body, Button, Choice, Field, Screen } from "../../../src/ui/components.tsx";

const CATEGORIES: readonly FeedbackCategory[] = ["MEASUREMENT_LOOKS_WRONG", "HARD_TO_UNDERSTAND", "HARMFUL_OR_OFFENSIVE",
                                                 "PREMIUM_TEXT_ISSUE", "OTHER"];

export default function Feedback() {
  const { reportId } = useLocalSearchParams<{ reportId: string }>();
  const { t, services } = useApp();
  const [category, setCategory] = useState<FeedbackCategory>("MEASUREMENT_LOOKS_WRONG");
  const [comment, setComment] = useState("");
  const [receipt, setReceipt] = useState<FeedbackReceipt | null>(null);
  const [state, setState] = useState<"idle" | "busy" | "failed" | "withdrawn">("idle");
  // One request ID per draft: a retried send converges on the same stored feedback.
  const requestId = useRef(`fb.${newClientId()}`).current;

  async function send() {
    setState("busy");
    try {
      setReceipt(await submitFeedback(services.api, String(reportId), {
        category, target: category === "PREMIUM_TEXT_ISSUE" ? "PREMIUM" : "REPORT", targetRef: null, comment,
      }, requestId));
      setState("idle");
    } catch {
      setState("failed");
    }
  }

  async function withdraw() {
    if (!receipt) return;
    setState("busy");
    try {
      await services.api.withdrawFeedback(receipt.feedback_id);
      setState("withdrawn");
    } catch {
      setState("failed");
    }
  }

  if (state === "withdrawn") {
    return (
      <Screen title={t("feedback.title")}>
        <Banner tone="ready">{t("feedback.withdrawn")}</Banner>
        <Button label={t("common.close")} onPress={() => router.back()} />
      </Screen>
    );
  }
  if (receipt) {
    return (
      <Screen title={t("feedback.title")}>
        <Banner tone="ready">{t("feedback.sent")}</Banner>
        <Button label={t("common.close")} onPress={() => router.back()} />
        <Button tone="secondary" label={t("feedback.withdraw")} busy={state === "busy"} onPress={() => void withdraw()} />
        {state === "failed" ? <Banner tone="danger">{t("common.error")}</Banner> : null}
      </Screen>
    );
  }
  const remaining = MAX_COMMENT - (normalizeComment(comment)?.length ?? 0);
  return (
    <Screen title={t("feedback.title")}>
      <Body muted>{t("feedback.intro")}</Body>
      <Choice label={t("feedback.category")} value={category} onChange={setCategory}
              options={CATEGORIES.map((value) => ({ value, label: t(`feedback.${value}`) }))} />
      <Field label={t("feedback.comment")} value={comment} onChange={setComment} multiline maxLength={MAX_COMMENT + 100}
             hint={`${Math.max(0, remaining)} ${t("feedback.characters")}`} />
      {state === "failed" ? <Banner tone="danger">{t("feedback.failed")}</Banner> : null}
      <Button label={t("feedback.send")} busy={state === "busy"} onPress={() => void send()} />
    </Screen>
  );
}
