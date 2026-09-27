"""Fake abuse challenge, analytics sink and telemetry exporter."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping, Sequence

from ...ports import abuse, analytics, telemetry
from ...ports.base import (
    CallContext,
    CapabilityProfile,
    Environment,
    ProviderMode,
    TransientUnavailable,
    check_mode_allowed,
    require_opaque_id,
)
from .base import FakeAdapter, SequentialIds


@dataclass
class _Challenge:
    action: str
    site: str
    expires_at: datetime
    used: bool = False


class FakeAbuseChallenge(FakeAdapter):
    port_name = abuse.PORT
    provider = "fake-challenge"
    default_capabilities = frozenset({abuse.WEB_CHALLENGE, abuse.APP_ATTESTATION})

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._ids = SequentialIds()
        self._tokens: dict[str, _Challenge] = {}
        self.outage = False

    def issue_token(self, action: str, site: str, *, ttl_s: int = 300) -> str:
        token = self._ids.new_id("chal")
        self._tokens[token] = _Challenge(action, site, self.clock.now() + timedelta(seconds=ttl_s))
        return token

    def verify(self, token: str, expected_action: str, expected_site: str,
               ctx: CallContext) -> abuse.ChallengeVerdict:
        def effect() -> abuse.ChallengeVerdict:
            if self.outage:
                return abuse.ChallengeVerdict(abuse.Verdict.UNAVAILABLE, "provider_unavailable")
            challenge = self._tokens.get(token)
            if challenge is None:
                return abuse.ChallengeVerdict(abuse.Verdict.REJECTED, "invalid_token")
            if challenge.used:
                return abuse.ChallengeVerdict(abuse.Verdict.REJECTED, "replayed")
            challenge.used = True
            if self.clock.now() >= challenge.expires_at:
                return abuse.ChallengeVerdict(abuse.Verdict.REJECTED, "expired")
            if challenge.action != expected_action:
                return abuse.ChallengeVerdict(abuse.Verdict.REJECTED, "wrong_action")
            if challenge.site != expected_site:
                return abuse.ChallengeVerdict(abuse.Verdict.REJECTED, "wrong_site")
            return abuse.ChallengeVerdict(abuse.Verdict.ACCEPTED)

        return self._run("verify", ctx, effect)


@dataclass(frozen=True)
class CapturedEvent:
    event_name: str
    properties: Mapping[str, analytics.PropertyValue]
    pseudonymous_ref: str | None


class FakeAnalyticsSink(FakeAdapter):
    port_name = analytics.PORT
    provider = "fake-analytics"

    def __init__(self, *, enabled: bool = True, **kwargs) -> None:
        super().__init__(**kwargs)
        self.enabled = enabled
        self.events: list[CapturedEvent] = []
        self._dedupe: set[str] = set()

    def capture(self, event_name: str, properties: Mapping[str, analytics.PropertyValue],
                consent: analytics.AnalyticsConsent, dedupe_key: str, ctx: CallContext) -> bool:
        if not self.enabled or not consent.granted:
            return False  # dropped before validation: optional analytics never fails a caller
        analytics.validate_event(event_name, properties)
        require_opaque_id(dedupe_key, "dedupe_key")

        def effect() -> bool:
            if dedupe_key not in self._dedupe:
                self._dedupe.add(dedupe_key)
                self.events.append(CapturedEvent(event_name, dict(properties), consent.pseudonymous_ref))
            return True

        return self._run("capture", ctx, effect)


class FakeTelemetryExporter:
    """Records sanitized records; ``outage`` makes every export fail."""

    def __init__(self, *, environment: Environment = Environment.TEST) -> None:
        check_mode_allowed(Environment.parse(environment), ProviderMode.FAKE)
        self.profile = CapabilityProfile(port=telemetry.PORT, provider="fake-telemetry", mode=ProviderMode.FAKE,
                                         capabilities=frozenset())
        self.exported: list[telemetry.TelemetryRecord] = []
        self.outage = False

    def export(self, records: Sequence[telemetry.TelemetryRecord]) -> None:
        if self.outage:
            raise TransientUnavailable("exporter_unavailable")
        self.exported.extend(records)
