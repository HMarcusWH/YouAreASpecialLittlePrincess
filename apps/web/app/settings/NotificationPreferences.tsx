"use client";

import { useEffect, useMemo, useState } from "react";

import { ApiError, PrincessApi, type NotificationPreferences as Preferences } from "@princess/api-client";

type Phase = "loading" | "guest" | "ready" | "error";

export function NotificationPreferences() {
  const api = useMemo(() => new PrincessApi({ baseUrl: "/api" }), []);
  const [phase, setPhase] = useState<Phase>("loading");
  const [saved, setSaved] = useState<Preferences | null>(null);
  const [checked, setChecked] = useState(false);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const who = await api.me();
        if (!active) return;
        if (who.kind === "GUEST") {
          setPhase("guest");
          return;
        }
        const preferences = await api.notificationPreferences();
        if (!active) return;
        setSaved(preferences);
        setChecked(preferences.mail_report_ready);
        setPhase("ready");
      } catch (cause) {
        if (!active) return;
        setError(cause instanceof ApiError && cause.status === 401
          ? "Your session has ended. Return to the start page to continue."
          : "Email preferences could not be loaded. Please try again.");
        setPhase("error");
      }
    })();
    return () => { active = false; };
  }, [api]);

  async function save() {
    if (!saved || saving) return;
    setSaving(true);
    setStatus(null);
    setError(null);
    try {
      const confirmed = await api.setNotificationPreferences({
        mail_report_ready: checked,
        locale: saved.locale,
      });
      setSaved(confirmed);
      setChecked(confirmed.mail_report_ready);
      setStatus("Email preference saved.");
    } catch (cause) {
      setChecked(saved.mail_report_ready);
      setError(cause instanceof ApiError && cause.status === 401
        ? "Your session has ended. Return to the start page to continue."
        : "Email preference could not be saved. Your previous setting is unchanged.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="stack" aria-labelledby="email-notifications-heading">
      <h2 id="email-notifications-heading">Email notifications</h2>
      <p id="email-notifications-description">
        Receive an email when a report finishes. The email contains a link, not your handwriting or report contents.
      </p>
      {phase === "loading" && <p role="status" aria-live="polite">Loading email preference…</p>}
      {phase === "guest" && <p>Email notifications are available after signing in to an account.</p>}
      {phase === "error" && error && <p role="alert">{error}</p>}
      {phase === "ready" && saved && (
        <>
          <label>
            <input
              type="checkbox"
              checked={checked}
              disabled={saving}
              aria-describedby="email-notifications-description"
              onChange={(event) => {
                setChecked(event.currentTarget.checked);
                setStatus(null);
                setError(null);
              }}
            />{" "}
            Email me when a report is ready
          </label>
          <p>
            <button
              type="button"
              className="button button-secondary"
              disabled={saving || checked === saved.mail_report_ready}
              onClick={save}
            >
              {saving ? "Saving…" : "Save email preference"}
            </button>
          </p>
          {status && <p role="status" aria-live="polite">{status}</p>}
          {error && <p role="alert">{error}</p>}
        </>
      )}
    </section>
  );
}
