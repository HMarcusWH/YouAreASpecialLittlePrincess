"""Fake transactional mailer and push provider."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping

from ...ports import messaging as port
from ...ports.base import CallContext, Environment, InvalidInput, PermanentFailure, require_opaque_id
from .base import FakeAdapter, SequentialIds


@dataclass(frozen=True)
class SentMail:
    template_id: str
    locale: str
    recipient_ref: str
    safe_variables: Mapping[str, str]
    delivery_key: str


class FakeMailer(FakeAdapter):
    """Provider-side idempotency lasts ``idempotency_window_s`` only; after it
    expires a repeated delivery key sends again, which is why the application
    keeps its own durable delivery records."""

    port_name = port.MAIL_PORT
    provider = "fake-mail"
    default_capabilities = frozenset({port.PROVIDER_IDEMPOTENCY, port.SIGNED_DELIVERY_EVENTS})

    def __init__(self, *, recipients: set[str] | None = None, idempotency_window_s: int = 86400, **kwargs) -> None:
        super().__init__(**kwargs)
        self._ids = SequentialIds()
        self.recipients = set(recipients or ())
        self.suppressed: set[str] = set()
        self.sent: list[SentMail] = []
        self._window = timedelta(seconds=idempotency_window_s)
        self._seen: dict[str, tuple[datetime, port.DeliveryObservation]] = {}

    def send(self, template_id: str, locale: str, recipient_ref: str, safe_variables: Mapping[str, str],
             delivery_key: str, ctx: CallContext) -> port.DeliveryObservation:
        port.validate_mail_request(template_id, locale, safe_variables)
        require_opaque_id(delivery_key, "delivery_key")

        def effect() -> port.DeliveryObservation:
            now = self.clock.now()
            seen = self._seen.get(delivery_key)
            if seen is not None and self.profile.supports(port.PROVIDER_IDEMPOTENCY) and now - seen[0] < self._window:
                return seen[1]
            if recipient_ref not in self.recipients:
                raise InvalidInput("invalid_recipient")
            if recipient_ref in self.suppressed:
                observation = port.DeliveryObservation(delivery_key, port.DeliveryState.SUPPRESSED, None)
            else:
                self.sent.append(SentMail(template_id, locale, recipient_ref, dict(safe_variables), delivery_key))
                observation = port.DeliveryObservation(delivery_key, port.DeliveryState.ACCEPTED,
                                                       self._ids.new_id("msg"))
            self._seen[delivery_key] = (now, observation)
            return observation

        return self._run("send", ctx, effect)


@dataclass
class _Installation:
    token: str
    record: port.PushInstallation
    active: bool = True


class FakePushProvider(FakeAdapter):
    """Best-effort delivery: duplicates are delivered twice (collapse keys are
    hints), invalidated tokens become ``unregistered``."""

    port_name = port.PUSH_PORT
    provider = "fake-push"
    default_capabilities = frozenset()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._ids = SequentialIds()
        self._installations: dict[str, _Installation] = {}
        self._invalid_tokens: set[str] = set()
        self.delivered: list[tuple[str, port.PushMessage]] = []

    def invalidate_token(self, device_token: str) -> None:
        self._invalid_tokens.add(device_token)

    def register_installation(self, device_token: str, platform: port.PushPlatform, app_environment: Environment,
                              principal_ref: str, ctx: CallContext) -> port.PushInstallation:
        require_opaque_id(principal_ref, "principal_ref")
        if not isinstance(device_token, str) or not 8 <= len(device_token) <= 4096:
            raise InvalidInput("invalid_device_token")

        def effect() -> port.PushInstallation:
            record = port.PushInstallation(self._ids.new_id("inst"), platform, Environment.parse(app_environment),
                                           principal_ref)
            self._installations[record.installation_ref] = _Installation(device_token, record)
            return record

        return self._run("register_installation", ctx, effect)

    def revoke_installation(self, installation_ref: str, ctx: CallContext) -> None:
        def effect() -> None:
            installation = self._installations.get(installation_ref)
            if installation is not None:
                installation.active = False

        self._run("revoke_installation", ctx, effect)

    def send(self, installation_ref: str, message: port.PushMessage, delivery_key: str,
             ctx: CallContext) -> port.DeliveryObservation:
        require_opaque_id(delivery_key, "delivery_key")

        def effect() -> port.DeliveryObservation:
            installation = self._installations.get(installation_ref)
            if installation is None or not installation.active or installation.token in self._invalid_tokens:
                raise PermanentFailure("unregistered")
            if installation.record.app_environment is not self.environment:
                raise PermanentFailure("environment_mismatch")
            self.delivered.append((installation_ref, message))
            return port.DeliveryObservation(delivery_key, port.DeliveryState.ACCEPTED, self._ids.new_id("push"))

        return self._run("send", ctx, effect)

