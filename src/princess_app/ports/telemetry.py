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
_URL = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s?#]*(\?[^\s#]*)?")
REDACTED = "[redacted]"
MAX_VALUE_LENGTH = 128
# String attributes must look like low-cardinality codes, route templates or
# opaque IDs; any other free text (exception messages, user input) is redacted.
_CODE_VALUE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_ROUTE_VALUE = re.compile(r"^(?:[a-z][a-z0-9+.-]*://[A-Za-z0-9.-]+(?::\d+)?)?/[A-Za-z0-9_./{}-]{0,120}$")
_VALUE_SHAPES = {"route": _ROUTE_VALUE}


class RecordKind(str, Enum):
    SPAN = "span"
    METRIC = "metric"
    LOG = "log"


def redact_value(value: AttrValue, key: str | None = None) -> AttrValue:
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if not isinstance(value, str) or _SECRETISH.search(value):
        return REDACTED
    # Keep scheme/host/path of a URL, drop any query string.
    value = _URL.sub(lambda m: m.group(0).split("?", 1)[0], value)
    shape = _VALUE_SHAPES.get(key or "", _CODE_VALUE)
    return value if shape.match(value) else REDACTED


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
