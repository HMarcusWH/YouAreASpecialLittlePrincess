"""Mail, push, abuse challenge, analytics and telemetry contract cases."""
from __future__ import annotations

import pytest
from port_harness import ENV, ctx

from princess_app.adapters.fakes import (
    FakeAbuseChallenge,
    FakeAnalyticsSink,
    FakeClock,
    FakeMailer,
    FakePushProvider,
    FakeTelemetryExporter,
)
from princess_app.application.telemetry import BufferedTelemetry
from princess_app.ports import abuse, analytics, messaging, telemetry
from princess_app.ports.base import Environment, InvalidInput, PermanentFailure


@pytest.mark.parametrize("template,variables", [
    ("unknown_template", {}),
    ("report_ready", {"app_link": "https://evil.example/?token=abc"}),
    ("report_ready", {"app_link": "app://reports/r1", "raw_premium_text": "..."}),
    ("share_invitation", {"inviter_display_name": "<b>html</b>"}),
    ("share_invitation", {"inviter_display_name": "see https://x.example/a?sig=1"}),
])
def test_mail_rejects_unsafe_templates_and_variables(template, variables):
    clock = FakeClock()
    with pytest.raises(InvalidInput):
        FakeMailer(clock=clock, recipients={"r1"}).send(template, "en", "r1", variables, "d1", ctx(clock))


def test_mail_invalid_recipient_suppression_and_idempotency_window():
    clock = FakeClock()
    mailer = FakeMailer(clock=clock, recipients={"r1", "r2"}, idempotency_window_s=60)
    with pytest.raises(InvalidInput):
        mailer.send("report_ready", "sv", "nobody", {}, "d0", ctx(clock))
    mailer.suppressed.add("r2")
    assert mailer.send("report_ready", "sv", "r2", {}, "d1", ctx(clock)).state is messaging.DeliveryState.SUPPRESSED
    link = {"app_link": "app://reports/r1"}
    mailer.send("report_ready", "sv-SE", "r1", link, "d2", ctx(clock))
    mailer.send("report_ready", "sv-SE", "r1", link, "d2", ctx(clock))
    assert len(mailer.sent) == 1
    clock.advance(61)
    mailer.send("report_ready", "sv-SE", "r1", link, "d2", ctx(clock))
    assert len(mailer.sent) == 2  # provider dedupe expired: the application must dedupe durably


def test_push_rotation_logout_environment_and_duplicates():
    clock = FakeClock()
    push = FakePushProvider(clock=clock)
    inst = push.register_installation("device-token-1", messaging.PushPlatform.APNS, ENV, "principal_1", ctx(clock))
    message = messaging.PushMessage("report_ready", "report_1", "en")
    push.send(inst.installation_ref, message, "k1", ctx(clock))
    push.send(inst.installation_ref, message, "k1", ctx(clock))
    assert len(push.delivered) == 2  # best effort; no exactly-once promise
    push.invalidate_token("device-token-1")
    with pytest.raises(PermanentFailure) as err:
        push.send(inst.installation_ref, message, "k2", ctx(clock))
    assert err.value.code == "unregistered"
    prod_inst = push.register_installation("device-token-2", messaging.PushPlatform.FCM, Environment.PRODUCTION,
                                           "principal_1", ctx(clock))
    with pytest.raises(PermanentFailure):
        push.send(prod_inst.installation_ref, message, "k3", ctx(clock))
    inst2 = push.register_installation("device-token-3", messaging.PushPlatform.FCM, ENV, "principal_1", ctx(clock))
    push.revoke_installation(inst2.installation_ref, ctx(clock))
    with pytest.raises(PermanentFailure):
        push.send(inst2.installation_ref, message, "k4", ctx(clock))


@pytest.mark.parametrize("kind,ref", [("balance_changed", "r1"), ("report_ready", "https://x/y")])
def test_push_payload_is_generic(kind, ref):
    with pytest.raises(InvalidInput):
        messaging.PushMessage(kind, ref, "en")


def test_challenge_verdicts_never_raise_for_outage_and_bind_action_site():
    clock = FakeClock()
    chal = FakeAbuseChallenge(clock=clock)
    token = chal.issue_token("upload", "app.example")
    assert chal.verify(token, "upload", "app.example", ctx(clock)).verdict is abuse.Verdict.ACCEPTED
    assert chal.verify(token, "upload", "app.example", ctx(clock)).reason == "replayed"
    assert chal.verify(chal.issue_token("login", "app.example"), "upload", "app.example",
                       ctx(clock)).reason == "wrong_action"
    assert chal.verify(chal.issue_token("upload", "evil"), "upload", "app.example", ctx(clock)).reason == "wrong_site"
    late = chal.issue_token("upload", "app.example", ttl_s=10)
    clock.advance(11)
    assert chal.verify(late, "upload", "app.example", ctx(clock)).reason == "expired"
    chal.outage = True
    assert chal.verify("x", "upload", "app.example", ctx(clock)).verdict is abuse.Verdict.UNAVAILABLE


@pytest.mark.parametrize("event,props", [
    ("screen_viewed", {}),
    ("analysis_completed", {"slant_mean": 12}),
    ("analysis_completed", {"available_feature_count": 9999}),
    ("report_opened", {"report_kind": "individual", "platform": "windows"}),
    ("report_opened", {"platform": True}),
    ("analysis_completed", {"platform": "web"}),  # declared properties are required
    ("report_opened", {}),
])
def test_analytics_allowlist_rejects_unknown_or_private_values(event, props):
    clock = FakeClock()
    with pytest.raises(InvalidInput):
        FakeAnalyticsSink(clock=clock).capture(event, props, analytics.AnalyticsConsent(True), "e1", ctx(clock))


def test_denied_analytics_consent_never_raises_even_for_unknown_events():
    clock = FakeClock()
    sink = FakeAnalyticsSink(clock=clock)
    assert sink.capture("future_event_v2", {"x": 1}, analytics.AnalyticsConsent(False), "e1", ctx(clock)) is False


def test_analytics_consent_disabled_and_dedupe():
    clock = FakeClock()
    sink = FakeAnalyticsSink(clock=clock)
    props = {"platform": "ios", "report_kind": "pair"}
    assert sink.capture("report_opened", props, analytics.AnalyticsConsent(False), "e1", ctx(clock)) is False
    assert sink.capture("report_opened", props, analytics.AnalyticsConsent(True), "e2", ctx(clock)) is True
    assert sink.capture("report_opened", props, analytics.AnalyticsConsent(True), "e2", ctx(clock)) is True
    assert len(sink.events) == 1
    sink.enabled = False
    assert sink.capture("report_opened", props, analytics.AnalyticsConsent(True), "e3", ctx(clock)) is False


def test_telemetry_redacts_and_drops_unknown_attributes():
    record = telemetry.TelemetryRecord(telemetry.RecordKind.LOG, "upload.completed", {
        "route": "/v1/reports/{report_id}", "error_code": "Bearer abc.def",
        "operation": "https://store.example/put/obj?X-Amz-Signature=abc",
        "user_text": "dear diary", "correlation_id": "corr-1", "latency_ms": 12,
    })
    assert record.attributes == {"route": "/v1/reports/{report_id}", "error_code": telemetry.REDACTED,
                                 "operation": telemetry.REDACTED, "correlation_id": "corr-1", "latency_ms": 12}


@pytest.mark.parametrize("key,value", [
    ("error_code", "dear diary, today I wrote"), ("operation", "user typed <b>this</b>"),
    ("route", "/reports/../../etc?x=1 plus text"), ("correlation_id", "asset handwriting text"),
    ("route", "/v1/reports/report_secret"), ("route", "https://api.example/v1/reports?page=2"),
])
def test_telemetry_redacts_free_text_in_allowlisted_keys(key, value):
    record = telemetry.TelemetryRecord(telemetry.RecordKind.LOG, "x.y", {key: value})
    assert record.attributes[key] == telemetry.REDACTED


def test_telemetry_fake_cannot_be_composed_into_production():
    with pytest.raises(InvalidInput):
        FakeTelemetryExporter(environment=Environment.PRODUCTION)


def test_buffered_telemetry_survives_outage_and_bounds_memory():
    exporter = FakeTelemetryExporter()
    buffered = BufferedTelemetry(exporter, capacity=3, batch_size=2)
    exporter.outage = True
    for i in range(5):
        buffered.record(telemetry.RecordKind.METRIC, "jobs.queue_age", {"queue_age_ms": i}, float(i))
    assert buffered.buffered == 3 and buffered.dropped == 2
    assert buffered.flush() == 0 and buffered.export_failures == 1
    exporter.outage = False
    assert buffered.flush() == 2 and buffered.flush() == 1 and buffered.flush() == 0
    buffered.record(telemetry.RecordKind.METRIC, "Bad Name!", {})
    assert buffered.dropped == 3


@pytest.mark.parametrize("granted,ref", [("false", None), (1, None), (True, "free text with spaces")])
def test_analytics_consent_requires_exact_boolean_and_opaque_ref(granted, ref):
    with pytest.raises(InvalidInput):
        analytics.AnalyticsConsent(granted, ref)
