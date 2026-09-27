# PushProvider — APNs and FCM lifecycle

[Index](README.md) · [Mobile](../roadmap/11-mobile-architecture.md) · [Apple](../roadmap/12-apple-platform-and-app-store.md) · [Android](../roadmap/13-android-and-google-play.md) · [T29](../roadmap/06-agent-backlog.md#t29).

Implemented operation (T24): `send(target, message, delivery_key, ctx)`, where `PushTarget` is a device token, platform and app environment, plus delivery-error normalization. APNs and FCM keep no server-side registry, so the port is stateless. The application owns bindings in `app.push_installation`: account, app environment, locale and a token digest. It handles rotation, logout, account switch and retirement. Only the notification worker's database role can read tokens, and the API never calls a push provider. Tokens are not permanent person IDs. Provider secrets remain server-side.

The application writes notification work to an outbox after a report or operation state commits. APNs/FCM delivery is best effort. Payloads contain generic notification text and opaque operation/report references, not handwriting, analysis conclusions, balances, auth tokens or signed private URLs. Opening a notification calls the normal authorized API; the notification does not grant access or prove the job succeeded.

Native clients request permission contextually and handle denied/provisional/revoked states. Update token bindings on rotation, reinstall, environment change, logout and account switch. Late notifications for an old account must reveal no private result. Deep-link destinations are allowlisted and verified through Universal/App Links; safe web fallback does not disclose unapproved fields.

Implement distinct APNs and FCM adapters or an explicitly approved broker behind the port. A broker is an additional processor/credential dependency and needs its own decision. Handle invalid/unregistered tokens by retiring the binding; distinguish temporary throttling from permanent failures. Collapse/delivery keys are optimization hints, not application exactly-once guarantees.

Tests cover duplicate sends, token rotation, sandbox/production mismatch, logout then delivery, denied permission, app cold/warm start, deleted report, expired grant, provider outage and message reordering. Use actual signed-device checks in T30/T31 before release; fakes cover server orchestration. Sources E29/E30 and platform checklists in [22](../roadmap/22-research-and-source-refresh.md).
