"""Report-ready notifications (T24): planned from the outbox, delivered best effort.

A committed ``report.ready`` outbox event is turned into durable delivery
records, one per push installation of the owner and one for mail when an
account opted in, in the same transaction that marks the event dispatched.
A replayed event or a second worker plans nothing new: each record's key is
derived from the event and the target, and that key is also the provider
delivery key.

Delivery never touches business state. A report, purchase or deletion is
valid whether or not its notice went out; a mail or push outage only delays
or drops notices. Before each send the worker re-reads what the notice is
about: a deleted account, a report that went with its capture, a device that
logged out or moved to another account, a withdrawn mail opt-in or a
suppressed recipient each stop the send. Notices carry a generic kind, an
opaque report reference and an ``app://`` link, never handwriting, analysis
text, balances or signed URLs; opening one goes through the normal
authorized API.

Retries are bounded. A transient failure or a refused provider credential
(key revoked or rotated) backs off and gives up after ``MAX_ATTEMPTS``; a
notice older than ``STALE_AFTER`` is dropped instead of sent late. An
ambiguous mail timeout is retried with the same delivery key only where the
provider deduplicates on it; an ambiguous push is not retried, since a
duplicate notice is worse than a missing one. An ``unregistered`` or
``environment_mismatch`` push retires the binding.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Protocol

from ..ports.base import (
    AmbiguousOutcome,
    CallContext,
    Clock,
    Environment,
    IdGenerator,
    InvalidInput,
    NotAuthorized,
    PermanentFailure,
    PortError,
    RateLimited,
    TransientUnavailable,
    Unauthenticated,
)
from ..ports.messaging import (
    PROVIDER_IDEMPOTENCY,
    DeliveryState,
    PushMessage,
    PushPlatform,
    PushProvider,
    PushTarget,
    TransactionalMailer,
    validate_device_token,
)
from ..ports.telemetry import RecordKind
from .identity import Principal
from .telemetry import BufferedTelemetry

REPORT_READY_TOPIC = "report.ready"
REPORT_READY = "report_ready"
MAIL, PUSH = "MAIL", "PUSH"
MAX_INSTALLATIONS = 10  # per principal; registering another drops the oldest
MAX_ATTEMPTS = 5
STALE_AFTER = timedelta(hours=24)
LEASE = timedelta(seconds=120)  # longer than a send's deadline, so a live send is never re-claimed
SEND_DEADLINE = timedelta(seconds=30)
DELIVERY_RETENTION = timedelta(days=30)  # draft retention for delivery records, owner-pending
_LOCALE = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")
_LINK_SAFE = re.compile(r"^[a-z0-9_-]{1,100}$")
RETIRING_FAILURES = frozenset({"unregistered", "environment_mismatch"})


@dataclass(frozen=True)
class Installation:
    installation_id: str
    platform: PushPlatform
    app_environment: Environment
    locale: str
    registered_at: datetime


@dataclass(frozen=True)
class Preferences:
    mail_report_ready: bool
    locale: str


DEFAULT_PREFERENCES = Preferences(mail_report_ready=False, locale="en")


@dataclass(frozen=True)
class ClaimedDelivery:
    """A leased delivery with the state it depends on, read at claim time."""

    delivery_key: str
    owner_id: str
    report_id: str
    channel: str
    kind: str
    attempts: int  # including this claim
    created_at: datetime  # when the report became ready
    owner_kind: str | None  # None: the principal is deleted or was transferred
    locale: str
    target: PushTarget | None = None  # PUSH only: the bound device, if still bound to this owner
    installation_id: str | None = None
    mail_opt_in: bool = False
    suppressed: bool = False


@dataclass(frozen=True)
class DeliveryOutcome:
    delivery_key: str
    channel: str
    state: str  # ACCEPTED | SUPPRESSED | SKIPPED | FAILED | RETRY
    outcome: str


class NotificationRepository(Protocol):
    def bind(self, owner_id: str, installation_id: str, platform: PushPlatform, environment: Environment,
             device_token: str, locale: str, at: datetime, max_installations: int) -> str:
        """Bind a device to the owner; returns the existing ID when it is already theirs."""
        ...

    def installations(self, owner_id: str) -> list[Installation]: ...

    def unbind(self, owner_id: str, installation_id: str) -> bool: ...

    def unbind_all(self, owner_id: str, registered_before: datetime | None = None) -> int: ...

    def preferences(self, owner_id: str) -> Preferences | None: ...

    def set_preferences(self, owner_id: str, preferences: Preferences, at: datetime) -> None: ...

    def plan(self, topic: str, channels: frozenset[str], environment: Environment, now: datetime,
             limit: int) -> int:
        """Create delivery records for pending events and mark them dispatched, atomically."""
        ...

    def claim(self, now: datetime, lease_until: datetime, limit: int) -> list[ClaimedDelivery]: ...

    def complete(self, delivery_key: str, state: str, outcome: str, provider_ref: str | None,
                 at: datetime) -> None: ...

    def retry(self, delivery_key: str, not_before: datetime, outcome: str) -> None: ...

    def retire_installation(self, installation_id: str) -> None: ...

    def suppress(self, recipient_ref: str, reason: str, at: datetime) -> None: ...

    def expire(self, completed_before: datetime, limit: int) -> int: ...


class NotificationService:
    """Owner-facing registration and preferences (API side, no provider access)."""

    def __init__(self, *, repo: NotificationRepository, clock: Clock, ids: IdGenerator,
                 environment: Environment) -> None:
        self._repo = repo
        self._clock = clock
        self._ids = ids
        self._environment = environment

    def register(self, who: Principal, device_token: str, platform: str, app_environment: str,
                 locale: str) -> str:
        validate_device_token(device_token)
        try:
            parsed_platform = PushPlatform(platform)
        except ValueError:
            raise InvalidInput("unknown_platform") from None
        # A sandbox build must not register against production (or the reverse).
        if Environment.parse(app_environment) is not self._environment:
            raise InvalidInput("environment_mismatch")
        _check_locale(locale)
        return self._repo.bind(who.principal_id, self._ids.new_id("inst"), parsed_platform, self._environment,
                               device_token, locale, self._clock.now(), MAX_INSTALLATIONS)

    def installations(self, owner_id: str) -> list[Installation]:
        return self._repo.installations(owner_id)

    def unregister(self, owner_id: str, installation_id: str) -> None:
        """Logout or account switch on the device. Idempotent; queued notices go too."""
        self._repo.unbind(owner_id, installation_id)

    def forget_devices(self, owner_id: str, registered_before: datetime | None = None) -> int:
        """Logout everywhere or account deletion: no device keeps receiving notices.
        A restore replay passes the revocation time, so later bindings stay."""
        return self._repo.unbind_all(owner_id, registered_before)

    def preferences(self, owner_id: str) -> Preferences:
        return self._repo.preferences(owner_id) or DEFAULT_PREFERENCES

    def set_preferences(self, who: Principal, mail_report_ready: bool, locale: str) -> Preferences:
        _check_locale(locale)
        if mail_report_ready and who.kind != "ACCOUNT":
            raise NotAuthorized("account_required")  # a guest has no address to mail
        preferences = Preferences(bool(mail_report_ready), locale)
        self._repo.set_preferences(who.principal_id, preferences, self._clock.now())
        return preferences


def _check_locale(locale: object) -> None:
    if not isinstance(locale, str) or not _LOCALE.match(locale):
        raise InvalidInput("invalid_locale")


class NotificationWorker:
    def __init__(self, *, repo: NotificationRepository, clock: Clock, environment: Environment,
                 context: Callable[[str], CallContext], mailer: TransactionalMailer | None = None,
                 push: PushProvider | None = None, enabled: Callable[[], bool] = lambda: True,
                 telemetry: BufferedTelemetry | None = None, batch: int = 20) -> None:
        self._repo = repo
        self._clock = clock
        self._environment = environment
        self._context = context
        self._mailer = mailer
        self._push = push
        self._enabled = enabled
        self._telemetry = telemetry
        self._batch = batch

    def run_once(self) -> list[DeliveryOutcome]:
        now = self._clock.now()
        # Switched off, events are consumed without planning: turning notices
        # back on does not send a backlog of late ones.
        enabled = self._enabled()
        channels = frozenset(c for c, adapter in ((MAIL, self._mailer), (PUSH, self._push))
                             if enabled and adapter is not None)
        self._repo.plan(REPORT_READY_TOPIC, channels, self._environment, now, self._batch)
        self._repo.expire(now - DELIVERY_RETENTION, 500)
        if not enabled:
            return []
        return [self._deliver(d) for d in self._repo.claim(now, now + LEASE, self._batch)]

    def _deliver(self, d: ClaimedDelivery) -> DeliveryOutcome:
        now = self._clock.now()
        reason = self._blocked(d, now)
        if reason is not None:
            return self._finish(d, "SKIPPED", reason)
        if d.channel == PUSH and d.target is not None and d.target.app_environment is not self._environment:
            self._repo.retire_installation(d.installation_id or "")
            return self._finish(d, "FAILED", "environment_mismatch")
        if d.channel == MAIL and d.suppressed:
            return self._finish(d, "SUPPRESSED", "suppressed")
        try:
            observation = self._send(d)
        except AmbiguousOutcome:
            deduplicated = (d.channel == MAIL and self._mailer is not None
                            and self._mailer.profile.supports(PROVIDER_IDEMPOTENCY))
            if deduplicated:
                return self._retry(d, "ambiguous", None)
            return self._finish(d, "FAILED", "ambiguous")
        except (TransientUnavailable, Unauthenticated, NotAuthorized) as exc:
            code = exc.code if isinstance(exc, TransientUnavailable) else "provider_auth"
            hint = exc.retry_after_s if isinstance(exc, RateLimited) else None
            return self._retry(d, code, hint)
        except PermanentFailure as exc:
            if d.channel == PUSH and exc.code in RETIRING_FAILURES and d.installation_id:
                self._repo.retire_installation(d.installation_id)
            return self._finish(d, "FAILED", exc.code)
        except PortError as exc:
            return self._finish(d, "FAILED", exc.code)
        if observation.state is DeliveryState.SUPPRESSED:
            if d.channel == MAIL:
                self._repo.suppress(d.owner_id, "PROVIDER", now)
            return self._finish(d, "SUPPRESSED", "provider_suppressed")
        return self._finish(d, "ACCEPTED", "accepted", observation.provider_message_ref)

    def _blocked(self, d: ClaimedDelivery, now: datetime) -> str | None:
        if now - d.created_at > STALE_AFTER:
            return "stale"
        if d.owner_kind is None:
            return "owner_gone"
        if d.channel == PUSH:
            if self._push is None:
                return "channel_unavailable"
            if d.target is None:
                return "binding_gone"  # logged out, rotated away or moved to another account
            return None
        if self._mailer is None:
            return "channel_unavailable"
        if d.owner_kind != "ACCOUNT" or not d.mail_opt_in:
            return "not_opted_in"
        return None

    def _send(self, d: ClaimedDelivery):
        ctx = self._context(d.delivery_key)
        if d.channel == PUSH:
            assert self._push is not None and d.target is not None
            return self._push.send(d.target, PushMessage(REPORT_READY, d.report_id, d.locale), d.delivery_key, ctx)
        assert self._mailer is not None
        link = f"app://reports/{d.report_id}" if _LINK_SAFE.match(d.report_id) else "app://reports"
        # ``recipient_ref`` is the principal; the adapter resolves the address.
        return self._mailer.send(REPORT_READY, d.locale, d.owner_id, {"app_link": link}, d.delivery_key, ctx)

    def _retry(self, d: ClaimedDelivery, code: str, hint_s: float | None) -> DeliveryOutcome:
        if d.attempts >= MAX_ATTEMPTS:
            return self._finish(d, "FAILED", "attempts_exhausted")
        delay = min(30 * 2 ** (d.attempts - 1), 3600)
        if hint_s is not None:
            delay = max(delay, min(hint_s, 3600))
        self._repo.retry(d.delivery_key, self._clock.now() + timedelta(seconds=delay), code)
        self._record(d.channel, "retry", code)
        return DeliveryOutcome(d.delivery_key, d.channel, "RETRY", code)

    def _finish(self, d: ClaimedDelivery, state: str, outcome: str,
                provider_ref: str | None = None) -> DeliveryOutcome:
        self._repo.complete(d.delivery_key, state, outcome, provider_ref, self._clock.now())
        self._record(d.channel, state.lower(), outcome)
        return DeliveryOutcome(d.delivery_key, d.channel, state, outcome)

    def _record(self, channel: str, state: str, outcome: str) -> None:
        if self._telemetry is not None:
            self._telemetry.record(RecordKind.METRIC, "notification.delivery",
                                   {"operation": channel.lower(), "outcome": state, "error_code": outcome}, 1)


__all__ = ["ClaimedDelivery", "DEFAULT_PREFERENCES", "DeliveryOutcome", "Installation", "MAIL", "MAX_ATTEMPTS",
           "MAX_INSTALLATIONS", "NotificationRepository", "NotificationService", "NotificationWorker", "PUSH",
           "Preferences", "REPORT_READY_TOPIC", "STALE_AFTER"]
