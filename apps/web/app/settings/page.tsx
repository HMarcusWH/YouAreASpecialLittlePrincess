import { NotificationPreferences } from "./NotificationPreferences.tsx";
import { SettingsActions } from "./SettingsActions.tsx";

export default function Settings() {
  return (
    <div className="stack">
      <h1>Settings</h1>
      <NotificationPreferences />
      <section className="stack" aria-labelledby="account-actions-heading">
        <h2 id="account-actions-heading">Account and session</h2>
        <SettingsActions />
      </section>
    </div>
  );
}
