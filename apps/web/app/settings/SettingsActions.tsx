"use client";

import { useState } from "react";

import { PrincessApi } from "@princess/api-client";

export function SettingsActions() {
  const [message, setMessage] = useState<string | null>(null);
  const api = new PrincessApi({ baseUrl: "/api" });

  async function signOut() {
    await fetch("/api/session/logout", { method: "POST" });
    window.location.assign("/");
  }

  async function logoutEverywhere() {
    try {
      await api.logoutEverywhere();
      await signOut();
    } catch {
      setMessage("Could not sign out other sessions. Please try again.");
    }
  }

  async function deleteAccount() {
    if (!window.confirm("Delete your account and all reports? This cannot be undone.")) return;
    try {
      await api.deleteAccount();
      setMessage("Deletion requested. Your data is being erased.");
      await signOut();
    } catch {
      setMessage("Deletion could not be requested. Please try again.");
    }
  }

  return (
    <div className="stack">
      <p><button type="button" className="button button-secondary" onClick={signOut}>Sign out on this device</button></p>
      <p><button type="button" className="button button-secondary" onClick={logoutEverywhere}>Sign out everywhere</button></p>
      <p><button type="button" className="button" onClick={deleteAccount}>Delete my account</button></p>
      {message && <p role="status" aria-live="polite">{message}</p>}
    </div>
  );
}
