"""TelemetryExporter port and redaction rules (docs/connectors/telemetry.md).

Operational telemetry is best effort. :class:`TelemetryRecord` accepts only
allowlisted low-cardinality attributes; values that look like credentials,
signed URLs or query strings are replaced before any exporter sees them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Protocol, Sequence, Union

from .base import CapabilityProfile, InvalidInput

PORT = "TelemetryExporter"

AttrValue = Union[str, int, float, bool]

ALLOWED_ATTRIBUTES = frozenset({
    "environment", "service", "service_version", "operation", "outcome", "error_code",
    "latency_ms", "queue_age_ms", "attempt", "port", "provider", "http_status",
    "route", "job_kind", "correlation_id", "usage_input_tokens", "usage_output_tokens",
})
_SECRETISH = re.compile(
    r"(?i)(bearer\s+\S+|authorization|cookie|token=|signature=|sig=|x-amz-[a-z-]+=|"
    r"sk_(?:live|test)_\w+|-----BEGIN|eyJ[A-Za-z0-9_-]{8,})"
)
REDACTED = "[redacted]"
MAX_VALUE_LENGTH = 128
# String attributes must look like low-cardinality codes; ``route`` must be one
# of the registered API route templates (never a literal path with IDs).
_CODE_VALUE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
ROUTE_TEMPLATES = frozenset({
    "/v1/guest-sessions", "/v1/me", "/v1/me/guest-transfer", "/v1/me/logout-everywhere", "/v1/me/permissions",
    "/v1/me/permissions/{purpose_id}", "/v1/reports", "/v1/reports/{report_id}",
    "/v1/reports/{report_id}/evidence", "/v1/dev/id-tokens",
    "/v1/uploads", "/v1/uploads/{upload_id}/complete", "/v1/analyses", "/v1/analyses/{run_id}",
    "/v1/analyses/{run_id}/cancel", "/v1/captures/{capture_id}", "/v1/dev/uploads/{upload_id}",
    "/v1/catalog", "/v1/me/payment-account", "/v1/me/credits", "/v1/checkout/web", "/v1/payments/{rail}/events",
    "/v1/purchases/claims", "/v1/reports/{report_id}/premium", "/v1/premium-jobs/{job_id}",
    "/v1/report-exports", "/v1/report-exports/{export_id}", "/v1/report-exports/{export_id}/file",
    "/v1/reports/{report_id}/feedback", "/v1/feedback/{feedback_id}",
    "/v1/me/push-installations", "/v1/me/push-installations/{installation_id}",
    "/v1/me/notification-preferences",
})


class RecordKind(str, Enum):
    SPAN = "span"
    METRIC = "metric"
    LOG = "log"


def redact_value(value: AttrValue, key: str | None = None) -> AttrValue:
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if not isinstance(value, str) or _SECRETISH.search(value):
        return REDACTED
    if key == "route":
        return value if value in ROUTE_TEMPLATES else REDACTED
    return value if _CODE_VALUE.match(value) else REDACTED


def sanitize_attributes(attributes: Mapping[str, AttrValue]) -> dict[str, AttrValue]:
    """Drop non-allowlisted keys and redact values that are not code/route shaped."""
    return {key: redact_value(value, key) for key, value in attributes.items() if key in ALLOWED_ATTRIBUTES}


@dataclass(frozen=True)
class TelemetryRecord:
    kind: RecordKind
    name: str
    attributes: Mapping[str, AttrValue] = field(default_factory=dict)
    value: float | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_.]{0,63}", self.name or ""):
            raise InvalidInput("invalid_metric_name")
        object.__setattr__(self, "attributes", sanitize_attributes(self.attributes))


class TelemetryExporter(Protocol):
    profile: CapabilityProfile

    def export(self, records: Sequence[TelemetryRecord]) -> None:
        """May raise ``TransientUnavailable``; callers use a buffered wrapper that
        never propagates telemetry failures into business operations."""
        ...
