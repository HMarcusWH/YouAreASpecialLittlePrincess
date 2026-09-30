"""Versioned, privacy-safe operational posture contracts (T24).

This module consumes fixed aggregate observations. It deliberately has no SQL,
no provider SDK and no mutation path for kill switches.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..ports.base import Environment, InvalidInput

SNAPSHOT_VERSION = "operational-snapshot/1"
POLICY_VERSION = "operational-alert-policy/1"
CAPABILITY_NAMES = ("premium_generation", "commerce", "uploads", "sharing", "notifications")
MEASURES = ("count", "oldest_age_s", "max_attempts")
OPERATORS = ("gt", "gte")
_ALERT_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")

VALID_KEYS = frozenset(
    [(source, category, state)
     for source in ("jobs",)
     for category in ("analysis", "premium", "export", "other")
     for state in ("queued", "leased")]
    + [(source, category, "pending")
       for source, categories in (("outbox", ("privacy", "notification", "other")),
                                  ("payment_events", ("stripe", "apple_app_store", "google_play")))
       for category in categories]
    + [("notifications", category, state)
       for category in ("mail", "push") for state in ("pending", "failed")]
    + [("commerce_completion", "all", "pending"),
       ("credit_reservations", "all", "reserved"),
       ("premium_attempts", "all", "started"),
       ("premium_attempts", "all", "ambiguous"),
       ("exports", "all", "queued"),
       ("exports", "all", "failed"),
       ("privacy", "tombstone", "missing"),
       ("privacy", "tombstone", "unreadable")]
)


def _utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise InvalidInput("operational_time_requires_timezone")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class OperationalObservation:
    source: str
    category: str
    state: str
    count: int
    oldest_age_s: int | None = None
    max_attempts: int | None = None

    def __post_init__(self) -> None:
        if (self.source, self.category, self.state) not in VALID_KEYS:
            raise InvalidInput("unknown_operational_dimension")
        for name in ("count", "oldest_age_s", "max_attempts"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise InvalidInput("invalid_operational_value", detail=name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "category": self.category,
            "state": self.state,
            "count": self.count,
            "oldest_age_s": self.oldest_age_s,
            "max_attempts": self.max_attempts,
        }


@dataclass(frozen=True)
class OperationalSnapshot:
    environment: Environment
    observed_at: datetime
    schema_revision: str
    capabilities: Mapping[str, bool]
    observations: tuple[OperationalObservation, ...]
    tombstone_entries: int
    tombstone_unreadable: int
    tombstone_store_present: bool

    def __post_init__(self) -> None:
        if set(self.capabilities) != set(CAPABILITY_NAMES) or any(type(v) is not bool for v in self.capabilities.values()):
            raise InvalidInput("operational_capability_shape")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", self.schema_revision or ""):
            raise InvalidInput("operational_schema_revision")
        if type(self.tombstone_entries) is not int or self.tombstone_entries < 0:
            raise InvalidInput("operational_tombstone_entries")
        if type(self.tombstone_unreadable) is not int or self.tombstone_unreadable < 0:
            raise InvalidInput("operational_tombstone_unreadable")
        if type(self.tombstone_store_present) is not bool:
            raise InvalidInput("operational_tombstone_store")
        keys = [(o.source, o.category, o.state) for o in self.observations]
        if len(keys) != len(set(keys)):
            raise InvalidInput("duplicate_operational_observation")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": SNAPSHOT_VERSION,
            "environment": self.environment.value,
            "observed_at": _utc(self.observed_at),
            "schema_revision": self.schema_revision,
            "capabilities": {name: self.capabilities[name] for name in CAPABILITY_NAMES},
            "observations": [o.to_dict() for o in sorted(
                self.observations, key=lambda x: (x.source, x.category, x.state)
            )],
            "privacy": {
                "tombstone_store_present": self.tombstone_store_present,
                "tombstone_entries": self.tombstone_entries,
                "tombstone_unreadable": self.tombstone_unreadable,
            },
        }


def build_snapshot(*, environment: Environment, observed_at: datetime, schema_revision: str,
                   capabilities: Mapping[str, bool], database_observations: Sequence[OperationalObservation],
                   tombstone_entries: int, tombstone_unreadable: int,
                   tombstone_store_present: bool) -> OperationalSnapshot:
    privacy = (
        OperationalObservation("privacy", "tombstone", "missing", 0 if tombstone_store_present else 1),
        OperationalObservation("privacy", "tombstone", "unreadable", tombstone_unreadable),
    )
    return OperationalSnapshot(
        environment=environment,
        observed_at=observed_at,
        schema_revision=schema_revision,
        capabilities=dict(capabilities),
        observations=tuple(database_observations) + privacy,
        tombstone_entries=tombstone_entries,
        tombstone_unreadable=tombstone_unreadable,
        tombstone_store_present=tombstone_store_present,
    )


@dataclass(frozen=True)
class AlertRule:
    alert_code: str
    source: str
    category: str
    state: str
    measure: str
    operator: str
    threshold: int

    def __post_init__(self) -> None:
        if not _ALERT_CODE.fullmatch(self.alert_code or ""):
            raise InvalidInput("invalid_alert_code")
        if (self.source, self.category, self.state) not in VALID_KEYS:
            raise InvalidInput("unknown_alert_dimension")
        if self.measure not in MEASURES or self.operator not in OPERATORS:
            raise InvalidInput("invalid_alert_rule")
        if type(self.threshold) is not int or not (0 <= self.threshold <= 2_147_483_647):
            raise InvalidInput("invalid_alert_threshold")


@dataclass(frozen=True)
class AlertPolicy:
    environment: Environment
    rules: tuple[AlertRule, ...]


@dataclass(frozen=True)
class OperationalAlert:
    alert_code: str
    source: str
    category: str
    state: str
    measure: str
    actual: int
    threshold: int

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in items:
        if key in out:
            raise InvalidInput("duplicate_alert_policy_key")
        out[key] = value
    return out


def load_alert_policy(path: Path, *, expected_environment: Environment) -> AlertPolicy:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except (OSError, ValueError):
        raise InvalidInput("alert_policy_unreadable") from None
    if not isinstance(raw, dict) or set(raw) != {"version", "environment", "rules"}:
        raise InvalidInput("alert_policy_shape")
    if raw["version"] != POLICY_VERSION:
        raise InvalidInput("alert_policy_version")
    environment = Environment.parse(raw["environment"])
    if environment is not expected_environment:
        raise InvalidInput("alert_policy_environment_mismatch")
    rules = raw["rules"]
    if not isinstance(rules, list) or len(rules) > 64:
        raise InvalidInput("alert_policy_rules")
    parsed: list[AlertRule] = []
    seen: set[str] = set()
    for item in rules:
        required = {"alert_code", "source", "category", "state", "measure", "operator", "threshold"}
        if not isinstance(item, dict) or set(item) != required:
            raise InvalidInput("alert_rule_shape")
        rule = AlertRule(**item)
        if rule.alert_code in seen:
            raise InvalidInput("duplicate_alert_code")
        seen.add(rule.alert_code)
        parsed.append(rule)
    return AlertPolicy(environment, tuple(parsed))


def evaluate_alerts(snapshot: OperationalSnapshot, policy: AlertPolicy) -> tuple[OperationalAlert, ...]:
    if snapshot.environment is not policy.environment:
        raise InvalidInput("alert_policy_environment_mismatch")
    indexed = {(o.source, o.category, o.state): o for o in snapshot.observations}
    alerts: list[OperationalAlert] = []
    for rule in policy.rules:
        observation = indexed.get((rule.source, rule.category, rule.state))
        raw = getattr(observation, rule.measure) if observation is not None else None
        actual = 0 if raw is None else int(raw)
        fired = actual > rule.threshold if rule.operator == "gt" else actual >= rule.threshold
        if fired:
            alerts.append(OperationalAlert(
                rule.alert_code, rule.source, rule.category, rule.state,
                rule.measure, actual, rule.threshold,
            ))
    return tuple(alerts)


def verify_disabled(capabilities: Mapping[str, bool], switches: Sequence[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    requested = tuple(dict.fromkeys(switches))
    if not requested:
        raise InvalidInput("no_kill_switch_requested")
    if any(name not in CAPABILITY_NAMES for name in requested):
        raise InvalidInput("unknown_kill_switch")
    disabled = tuple(name for name in requested if capabilities[name] is False)
    enabled = tuple(name for name in requested if capabilities[name] is True)
    return disabled, enabled


__all__ = [
    "AlertPolicy", "AlertRule", "CAPABILITY_NAMES", "OperationalAlert", "OperationalObservation",
    "OperationalSnapshot", "POLICY_VERSION", "SNAPSHOT_VERSION", "VALID_KEYS", "build_snapshot",
    "evaluate_alerts", "load_alert_policy", "verify_disabled",
]
