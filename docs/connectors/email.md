# TransactionalMailer — outbox delivery, not business state

[Index](README.md) · [T24](../roadmap/06-agent-backlog.md#t24) · [Mail ADR](../adr/ADR-007-email.md) · [Operations](../roadmap/18-observability-support-and-cost-control.md).

The port `send(template_id, locale, recipient_ref, safe_variables, delivery_key, deadline)` returns a delivery observation/provider ID or typed failure. It must not accept arbitrary user HTML, source handwriting, raw Premium text, signed private asset URLs or a provider SDK template object. The application owns template/version/consent selection and creates the outbox row in the same transaction as its business event.

Separate identity-provider security/login email from application notifications so two systems do not issue competing verification links. Use approved sender domains and authenticated mail configuration. Resend is a candidate; select the provider and data-processing terms through ADR-007. Provider idempotency is useful but may have a limited retention window; preserve application delivery keys and outcomes for durable deduplication.

On success record provider delivery ID. On an ambiguous timeout reconcile or retry with the same supported delivery key within a bounded policy. A purchase/report/deletion transaction remains valid if mail is delayed. A bounce does not revoke entitlement. Verify signed provider events before updating delivery/suppression records. Distinguish transactional notices from optional marketing preferences and never add marketing consent automatically.

Fake and sandbox tests cover duplicate outbox execution, invalid recipient, expired link, bounce/suppression, provider outage, timeout after acceptance and a deleted principal. Templates use a generic authorized app link, not private content in the message preview. Operations must support suppression review, key rotation and disabling noncritical mail without losing business state. Production gate: approved sender, templates, retention/region, recipient/privacy policy and support owner. E27 in [sources](../roadmap/22-research-and-source-refresh.md).
