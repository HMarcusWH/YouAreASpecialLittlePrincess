"""TransactionalMailer and PushProvider ports (docs/connectors/email.md, push.md).

Messages carry template/kind IDs, locale and opaque object references only:
no handwriting, analysis conclusions, balances, tokens or signed URLs.
Delivery is best effort; business state never waits on it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Protocol

from .base import CallContext, CapabilityProfile, Environment, InvalidInput, require_opaque_id

MAIL_PORT = "TransactionalMailer"
PUSH_PORT = "PushProvider"

# Capability names. Signed bounce/delivery events arrive with T24's operation.
PROVIDER_IDEMPOTENCY = "provider_idempotency"

MAIL_TEMPLATES: Mapping[str, frozenset[str]] = {
    # template_id -> allowed safe variable names
    "report_ready": frozenset({"app_link"}),
    "purchase_receipt": frozenset({"app_link", "credits_granted"}),
    "deletion_completed": frozenset(),
    "share_invitation": frozenset({"app_link", "inviter_display_name"}),
}
PUSH_KINDS = frozenset({"report_ready", "premium_ready", "comparison_ready", "deletion_completed"})

_URLISH = re.compile(r"(?i)(https?://|token=|signature=|x-amz-|sig=)")
_LOCALE = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")
_APP_LINK = re.compile(r"^app://[a-z0-9/_-]{1,128}$")


def validate_mail_request(template_id: str, locale: str, safe_variables: Mapping[str, str]) -> None:
    allowed = MAIL_TEMPLATES.get(template_id)
    if allowed is None:
        raise InvalidInput("unknown_template", detail=template_id[:64])
    if not isinstance(locale, str) or not _LOCALE.match(locale):
        raise InvalidInput("invalid_locale")
    for key, value in safe_variables.items():
        if key not in allowed:
            raise InvalidInput("variable_not_allowed", detail=key[:64])
        if not isinstance(value, str) or len(value) > 200 or "<" in value:
            raise InvalidInput("unsafe_variable", detail=key)
        if key == "app_link":
            if not _APP_LINK.match(value):
                raise InvalidInput("unsafe_variable", detail=key)
        elif _URLISH.search(value):
            raise InvalidInput("unsafe_variable", detail=key)


class DeliveryState(str, Enum):
    ACCEPTED = "ACCEPTED"
    SUPPRESSED = "SUPPRESSED"


@dataclass(frozen=True)
class DeliveryObservation:
    delivery_key: str
    state: DeliveryState
    provider_message_ref: str | None


class TransactionalMailer(Protocol):
    profile: CapabilityProfile

    def send(self, template_id: str, locale: str, recipient_ref: str, safe_variables: Mapping[str, str],
             delivery_key: str, ctx: CallContext) -> DeliveryObservation:
        """``recipient_ref`` is an internal reference resolved by the adapter's
        address book; raw addresses never travel with business events."""
        ...


class PushPlatform(str, Enum):
    APNS = "apns"
    FCM = "fcm"


_DEVICE_TOKEN = re.compile(r"^[A-Za-z0-9_:.-]{8,4096}$")


def validate_device_token(device_token: object) -> str:
    """APNs tokens are hex; FCM registration tokens use a URL-safe alphabet."""
    if not isinstance(device_token, str) or not _DEVICE_TOKEN.match(device_token):
        raise InvalidInput("invalid_device_token")
    return device_token


@dataclass(frozen=True)
class PushTarget:
    """Where one notification goes. The application owns installation
    bindings (account, rotation, logout, retirement); adapters are stateless
    and only translate a target into an APNs/FCM request. The token never
    appears in ``repr`` and so not in logs."""

    device_token: str = field(repr=False)
    platform: PushPlatform
    app_environment: Environment

    def __post_init__(self) -> None:
        validate_device_token(self.device_token)
        object.__setattr__(self, "platform", PushPlatform(self.platform))
        object.__setattr__(self, "app_environment", Environment.parse(self.app_environment))


@dataclass(frozen=True)
class PushMessage:
    kind: str
    object_ref: str
    locale: str

    def __post_init__(self) -> None:
        if self.kind not in PUSH_KINDS:
            raise InvalidInput("unknown_push_kind", detail=str(self.kind)[:64])
        require_opaque_id(self.object_ref, "object_ref")
        if not _LOCALE.match(self.locale):
            raise InvalidInput("invalid_locale")


class PushProvider(Protocol):
    profile: CapabilityProfile

    def send(self, target: PushTarget, message: PushMessage, delivery_key: str,
             ctx: CallContext) -> DeliveryObservation:
        """Raises ``PermanentFailure('unregistered')`` when the token is gone and
        ``PermanentFailure('environment_mismatch')`` for a sandbox token sent to
        production (or the reverse); the application then retires the binding."""
        ...
