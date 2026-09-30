"""Map the fixed operational posture contract onto bounded telemetry records.

The mapping is deliberately pure: it accepts only the already privacy-safe
OperationalSnapshot/OperationalAlert objects and imports no adapters, SQL or
provider SDKs. Every reviewed operational dimension emits a count gauge,
including zero when PostgreSQL omitted an empty group, so exporters receive a
complete point-in-time snapshot rather than a sparse series that can go stale.
"""
from __future__ import annotations

import re
from typing import Sequence

from ..ports.base import InvalidInput
from ..ports.telemetry import RecordKind, TelemetryRecord
from .operations import (
    CAPABILITY_NAMES,
    VALID_KEYS,
    OperationalAlert,
    OperationalSnapshot,
)

COUNT_METRIC = "operational.count"
OLDEST_AGE_METRIC = "operational.oldest_age_s"
MAX_ATTEMPTS_METRIC = "operational.max_attempts"
CAPABILITY_METRIC = "operational.capability"
ALERT_METRIC = "operational.alert"

_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def _code(value: str) -> str:
    if not _CODE.fullmatch(value):
        raise InvalidInput("operational_telemetry_code")
    return value


def _operation(source: str, category: str, state: str) -> str:
    return _code(f"{source}.{category}.{state}")


def snapshot_records(snapshot: OperationalSnapshot) -> tuple[TelemetryRecord, ...]:
    """Return a complete bounded gauge set for one operational snapshot."""
    indexed = {(o.source, o.category, o.state): o for o in snapshot.observations}
    environment = _code(snapshot.environment.value)
    records: list[TelemetryRecord] = []

    for key in sorted(VALID_KEYS):
        observation = indexed.get(key)
        attributes = {"environment": environment, "operation": _operation(*key)}
        records.append(TelemetryRecord(
            RecordKind.METRIC, COUNT_METRIC, attributes,
            float(observation.count if observation is not None else 0),
        ))
        if observation is not None and observation.oldest_age_s is not None:
            records.append(TelemetryRecord(
                RecordKind.METRIC, OLDEST_AGE_METRIC, attributes, float(observation.oldest_age_s),
            ))
        if observation is not None and observation.max_attempts is not None:
            records.append(TelemetryRecord(
                RecordKind.METRIC, MAX_ATTEMPTS_METRIC, attributes, float(observation.max_attempts),
            ))

    for capability in CAPABILITY_NAMES:
        enabled = snapshot.capabilities[capability]
        records.append(TelemetryRecord(
            RecordKind.METRIC,
            CAPABILITY_METRIC,
            {
                "environment": environment,
                "operation": _code(capability),
                "outcome": "enabled" if enabled else "disabled",
            },
            1.0 if enabled else 0.0,
        ))
    return tuple(records)


def alert_records(snapshot: OperationalSnapshot,
                  alerts: Sequence[OperationalAlert]) -> tuple[TelemetryRecord, ...]:
    """Map reviewed fired alerts; alert codes remain bounded low-cardinality values."""
    environment = _code(snapshot.environment.value)
    records: list[TelemetryRecord] = []
    for alert in sorted(alerts, key=lambda item: (item.alert_code, item.source, item.category, item.state)):
        key = (alert.source, alert.category, alert.state)
        if key not in VALID_KEYS:
            raise InvalidInput("unknown_operational_dimension")
        records.append(TelemetryRecord(
            RecordKind.METRIC,
            ALERT_METRIC,
            {
                "environment": environment,
                "operation": _operation(*key),
                "outcome": "fired",
                "error_code": _code(alert.alert_code),
            },
            1.0,
        ))
    return tuple(records)


def operational_records(snapshot: OperationalSnapshot,
                        alerts: Sequence[OperationalAlert] = ()) -> tuple[TelemetryRecord, ...]:
    return snapshot_records(snapshot) + alert_records(snapshot, alerts)


__all__ = [
    "ALERT_METRIC", "CAPABILITY_METRIC", "COUNT_METRIC", "MAX_ATTEMPTS_METRIC",
    "OLDEST_AGE_METRIC", "alert_records", "operational_records", "snapshot_records",
]
