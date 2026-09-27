"""Cross-port contract cases: environment/mode guards, deadlines, ambiguity,
error translation and capability refusal."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from port_harness import ENV, ctx

from princess_app.adapters.fakes import (
    FakeAbuseChallenge,
    FakeAnalyticsSink,
    FakeClock,
    FakeIdentityProvider,
    FakeMailer,
    FakeObjectStore,
    FakePaymentProvider,
    FakePremiumModel,
    FakePushProvider,
)
from princess_app.ports import payments
from princess_app.ports.base import (
    ALLOWED_MODES,
    AmbiguousOutcome,
    CallContext,
    DeadlineExceeded,
    Environment,
    InvalidInput,
    PermanentFailure,
    PortError,
    ProviderMode,
    RateLimited,
    TransientUnavailable,
    Unsupported,
    check_mode_allowed,
    provider_errors,
)

FAKE_FACTORIES = [
    lambda **kw: FakeIdentityProvider(**kw),
    lambda **kw: FakeObjectStore(**kw),
    lambda **kw: FakePremiumModel(lambda request: {}, **kw),
    lambda **kw: FakePaymentProvider(payments.PaymentRail.STRIPE, **kw),
    lambda **kw: FakeMailer(**kw),
    lambda **kw: FakePushProvider(**kw),
    lambda **kw: FakeAbuseChallenge(**kw),
    lambda **kw: FakeAnalyticsSink(**kw),
]


@pytest.mark.parametrize("factory", FAKE_FACTORIES)
def test_fakes_cannot_be_composed_into_production(factory):
    with pytest.raises(InvalidInput) as err:
        factory(environment=Environment.PRODUCTION)
    assert err.value.code == "mode_not_allowed_in_environment"


@pytest.mark.parametrize("factory", FAKE_FACTORIES)
def test_fake_profiles_declare_fake_mode(factory):
    adapter = factory()
    assert adapter.profile.mode is ProviderMode.FAKE
    assert adapter.profile.port != "unset"


def test_mode_matrix_keeps_live_out_of_dev_and_fakes_out_of_production():
    assert ALLOWED_MODES[Environment.PRODUCTION] == {ProviderMode.LIVE}
    for env in (Environment.LOCAL, Environment.TEST, Environment.PREVIEW):
        assert ProviderMode.LIVE not in ALLOWED_MODES[env]
        with pytest.raises(InvalidInput):
            check_mode_allowed(env, ProviderMode.LIVE)
    check_mode_allowed(Environment.STAGING, ProviderMode.SANDBOX)


@pytest.mark.parametrize("value", ["prod", "PRODUCTION", "", None, 3])
def test_unknown_environment_is_rejected(value):
    with pytest.raises(InvalidInput) as err:
        Environment.parse(value)
    assert err.value.code == "unknown_environment"


def test_call_context_requires_aware_utc_deadline_and_safe_ids():
    with pytest.raises(InvalidInput):
        CallContext("corr-1", ENV, datetime(2026, 1, 1))
    with pytest.raises(InvalidInput):
        CallContext("bad id with spaces", ENV, datetime(2026, 1, 1).astimezone())


def test_wrong_environment_call_is_rejected_before_any_effect():
    clock = FakeClock()
    mailer = FakeMailer(clock=clock, recipients={"r1"})
    with pytest.raises(InvalidInput) as err:
        mailer.send("report_ready", "en", "r1", {}, "d1", ctx(clock, environment=Environment.PREVIEW))
    assert err.value.code == "environment_mismatch"
    assert mailer.sent == [] and mailer.calls == []


def test_expired_deadline_fails_before_send():
    clock = FakeClock()
    mailer = FakeMailer(clock=clock, recipients={"r1"})
    call = ctx(clock, seconds=1)
    clock.advance(2)
    with pytest.raises(DeadlineExceeded):
        mailer.send("report_ready", "en", "r1", {}, "d1", call)
    assert mailer.sent == []


def test_latency_past_deadline_is_ambiguous_and_the_effect_happened():
    clock = FakeClock()
    mailer = FakeMailer(clock=clock, recipients={"r1"}, latency_s=5)
    with pytest.raises(AmbiguousOutcome):
        mailer.send("report_ready", "en", "r1", {}, "d1", ctx(clock, seconds=2))
    assert len(mailer.sent) == 1  # the remote side accepted it anyway


def test_scripted_fault_after_effect_models_timeout_after_acceptance():
    clock = FakeClock()
    mailer = FakeMailer(clock=clock, recipients={"r1"})
    mailer.faults.inject("send", AmbiguousOutcome("timeout_after_send"), after_effect=True)
    with pytest.raises(AmbiguousOutcome):
        mailer.send("report_ready", "en", "r1", {}, "d1", ctx(clock))
    assert len(mailer.sent) == 1
    # Retrying with the same delivery key inside the provider window converges.
    observation = mailer.send("report_ready", "en", "r1", {}, "d1", ctx(clock))
    assert len(mailer.sent) == 1 and observation.provider_message_ref is not None


def test_scripted_fault_before_effect_has_no_effect():
    clock = FakeClock()
    mailer = FakeMailer(clock=clock, recipients={"r1"})
    mailer.faults.inject("send", RateLimited(retry_after_s=30))
    with pytest.raises(RateLimited) as err:
        mailer.send("report_ready", "en", "r1", {}, "d1", ctx(clock))
    assert err.value.retry_after_s == 30 and err.value.retryable
    assert mailer.sent == []


def test_provider_exceptions_never_leak_through_ports():
    class SdkError(Exception):
        pass

    with pytest.raises(PermanentFailure) as err:
        with provider_errors():
            raise SdkError("Authorization: Bearer sk_live_secret body={'handwriting': ...}")
    assert "secret" not in str(err.value) and "handwriting" not in str(err.value)
    assert err.value.__cause__ is None and err.value.__suppress_context__
    assert err.value.code == "provider_error"


def test_provider_error_mapper_classifies_known_errors():
    class Throttled(Exception):
        retry_after = 7

    def mapper(exc):
        return RateLimited(retry_after_s=exc.retry_after) if isinstance(exc, Throttled) else None

    with pytest.raises(RateLimited) as err:
        with provider_errors(mapper):
            raise Throttled()
    assert err.value.retry_after_s == 7
    with pytest.raises(TransientUnavailable):
        with provider_errors(mapper):
            raise TransientUnavailable("upstream_503")


def test_port_error_codes_must_be_safe():
    with pytest.raises(ValueError):
        PortError("Token eyJhbGciOi...")


@pytest.mark.parametrize("detail", ["https://x.example/a?token=abc", "'secret body'", "x" * 200, "a\nb"])
def test_port_error_details_are_redacted_unless_identifier_like(detail):
    error = InvalidInput("bad_input", detail=detail)
    assert error.detail == "[redacted]" and str(error) == "bad_input" and detail not in repr(error)
    assert InvalidInput("bad_input", detail="max_bytes").detail == "max_bytes"
    with pytest.raises(InvalidInput) as err:
        Environment.parse("prod'; DROP TABLE")
    assert "DROP" not in str(err.value)


def test_unsupported_capability_fails_explicitly():
    clock = FakeClock()
    store = FakeObjectStore(clock=clock, capabilities=set())
    with pytest.raises(Unsupported):
        store.delete_asset_versions("asset_1", ctx(clock))
    apple = FakePaymentProvider(payments.PaymentRail.APPLE_APP_STORE, clock=clock)
    with pytest.raises(Unsupported):
        apple.request_refund_if_supported("txn_000001", ctx(clock))
    with pytest.raises(Unsupported):
        apple.complete_store_purchase("txn_000001", payments.CompletionAction.SERVER_CONSUME, ctx(clock))


def test_fake_clock_never_goes_backwards():
    clock = FakeClock()
    with pytest.raises(ValueError):
        clock.advance(-1)
    with pytest.raises(ValueError):
        clock.set(clock.now() - timedelta(seconds=1))
