"""AnalyticsSink port with the application-owned event allowlist
(docs/connectors/analytics.md).

Every sink receives events already validated by :func:`validate_event`.
Properties are bounded enums, counts or buckets; there is no generic
"log this object" entry point. Sending when analytics consent is absent is a
no-op, never an error that could block a business operation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Union

from .base import CallContext, CapabilityProfile, InvalidInput

PORT = "AnalyticsSink"
ALLOWLIST_VERSION = "analytics-events/1"

PropertyValue = Union[str, int, bool]

_PLATFORM = frozenset({"web", "ios", "android"})
_OUTCOME = frozenset({"success", "failure", "cancelled"})
_REPORT_KIND = frozenset({"individual", "pair", "history"})
_LATENCY = frozenset({"lt_1s", "1_5s", "5_30s", "30_120s", "gt_120s"})
_RAIL = frozenset({"stripe", "apple_app_store", "google_play"})
_EXPORT = frozenset({"pdf", "share_card"})


def _enum(values: frozenset[str]):
    def check(value: PropertyValue) -> bool:
        return isinstance(value, str) and value in values
    return check


def _count(maximum: int):
    def check(value: PropertyValue) -> bool:
        return type(value) is int and 0 <= value <= maximum
    return check


_COMMON = {"platform": _enum(_PLATFORM)}

EVENTS: Mapping[str, Mapping[str, object]] = {
    "upload_accepted": {**_COMMON},
    "analysis_completed": {**_COMMON, "outcome": _enum(_OUTCOME), "latency": _enum(_LATENCY),
                           "available_feature_count": _count(272)},
    "report_opened": {**_COMMON, "report_kind": _enum(_REPORT_KIND)},
    "offer_displayed": {**_COMMON},
    "checkout_started": {**_COMMON, "rail": _enum(_RAIL)},
    "purchase_verified": {**_COMMON, "rail": _enum(_RAIL)},
    "premium_published": {**_COMMON, "outcome": _enum(_OUTCOME)},
    "export_created": {**_COMMON, "export_kind": _enum(_EXPORT)},
    "share_dialog_opened": {**_COMMON},
    "invitation_redeemed": {**_COMMON},
    "deletion_completed": {**_COMMON},
}
MAX_PROPERTIES = 8


def validate_event(event_name: str, properties: Mapping[str, PropertyValue]) -> None:
    schema = EVENTS.get(event_name)
    if schema is None:
        raise InvalidInput("unknown_event", detail=str(event_name)[:64])
    if len(properties) > MAX_PROPERTIES:
        raise InvalidInput("too_many_properties")
    for key, value in properties.items():
        check = schema.get(key)
        if check is None:
            raise InvalidInput("property_not_allowed", detail=f"{event_name}.{str(key)[:32]}")
        if not check(value):  # type: ignore[operator]
            raise InvalidInput("property_value_not_allowed", detail=f"{event_name}.{key}")


@dataclass(frozen=True)
class AnalyticsConsent:
    """Optional product-analytics consent, separate from service processing."""

    granted: bool
    pseudonymous_ref: str | None = None


class AnalyticsSink(Protocol):
    profile: CapabilityProfile

    def capture(self, event_name: str, properties: Mapping[str, PropertyValue], consent: AnalyticsConsent,
                dedupe_key: str, ctx: CallContext) -> bool:
        """Returns ``True`` when accepted for delivery, ``False`` when dropped
        (disabled or no consent). Unknown events/properties raise ``InvalidInput``."""
        ...
