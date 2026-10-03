import { router } from "expo-router";
import { useState } from "react";

import { useApp } from "../src/bootstrap/AppProvider.tsx";
import { Banner, Body, Button, Field, Screen } from "../src/ui/components.tsx";

/**
 * Sign-in. Release builds have no account provider wired yet (N07 is gated on
 * the identity provider and processor approvals), so they say so plainly.
 * Development builds against a local/test API can sign in a synthetic subject
 * through the fake identity provider; that path is compiled out by config.
 */
export default function Account() {
  const { t, config, services, session } = useApp();
  const [subject, setSubject] = useState("synthetic-tester");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!config.devIdentity) {
    return (
      <Screen title={t("account.title")}>
        <Banner tone="info">{t("account.unavailable")}</Banner>
        <Button tone="secondary" label={t("common.close")} onPress={() => router.back()} />
      </Screen>
    );
  }

  async function signIn() {
    setBusy(true);
    setError(null);
    try {
      const token = await services.clientFor(null).devIdToken(subject.trim());
      await services.session.signIn(token, "development");
      router.back();
    } catch {
      setError(t("account.failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen title={t("account.title")}>
      <Banner tone="attention">{t("account.dev_intro")}</Banner>
      {session.status === "ACTIVE" && session.kind === "GUEST" ? <Body muted>{t("account.transfer_note")}</Body> : null}
      <Field label={t("account.dev_subject")} value={subject} onChange={setSubject} maxLength={64} />
      {error ? <Banner tone="danger">{error}</Banner> : null}
      <Button label={t("account.dev_sign_in")} busy={busy} disabled={!/^[A-Za-z0-9._-]{1,64}$/.test(subject.trim())}
              onPress={() => void signIn()} />
    </Screen>
  );
}
