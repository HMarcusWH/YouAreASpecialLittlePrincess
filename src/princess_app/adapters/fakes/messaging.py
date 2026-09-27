"""Fake transactional mailer and push provider."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping

from ...ports import messaging as port
from ...ports.base import CallContext, InvalidInput, PermanentFailure, require_opaque_id
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
    default_capabilities = frozenset({port.PROVIDER_IDEMPOTENCY})

    def __init__(self, *, recipients: set[str] | None = None, idempotency_window_s: int = 86400,
                 accept_any_recipient: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self._ids = SequentialIds()
        self.recipients = set(recipients or ())
        self.accept_any_recipient = accept_any_recipient  # a local run has no address book
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
            if recipient_ref not in self.recipients and not self.accept_any_recipient:
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


class FakePushProvider(FakeAdapter):
    """Stateless best-effort delivery like APNs/FCM: duplicates are delivered
    twice (collapse keys are hints), invalidated tokens become ``unregistered``
    and a target from another app environment is refused."""

    port_name = port.PUSH_PORT
    provider = "fake-push"
    default_capabilities = frozenset()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._ids = SequentialIds()
        self._invalid_tokens: set[str] = set()
        self.delivered: list[tuple[port.PushTarget, port.PushMessage]] = []

    def invalidate_token(self, device_token: str) -> None:
        self._invalid_tokens.add(device_token)

    def send(self, target: port.PushTarget, message: port.PushMessage, delivery_key: str,
             ctx: CallContext) -> port.DeliveryObservation:
        require_opaque_id(delivery_key, "delivery_key")

        def effect() -> port.DeliveryObservation:
            if target.device_token in self._invalid_tokens:
                raise PermanentFailure("unregistered")
            if target.app_environment is not self.environment:
                raise PermanentFailure("environment_mismatch")
            self.delivered.append((target, message))
            return port.DeliveryObservation(delivery_key, port.DeliveryState.ACCEPTED, self._ids.new_id("push"))

        return self._run("send", ctx, effect)
