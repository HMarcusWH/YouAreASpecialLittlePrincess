"""Append-only, purpose-specific permission ledger semantics (T02 over T03).

Each event records one decision (grant, deny, withdraw) for one T03 purpose
version and scope. Effective permission is evaluated at use time from the
event history; events are never edited. Rules:

* Grants must use a scope the purpose allows (T03 ``grant_scopes``); a
  purpose with no grant scopes cannot be granted in the product.
* A deny/withdraw may always be subject-wide; it then overrides item grants.
* Among events already in effect, the one recorded last wins.
* A grant for a superseded purpose version does not authorize use.
* Events cannot claim effect before they were recorded.
* Purposes are independent: an ordinary-sharing grant never authorizes a
  partner comparison, and a purchase never implies any permission.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable, Mapping

from princess_contracts import generated as g

from ..ports.base import InvalidInput, require_opaque_id, require_utc

# Mirror of contracts/consent/v1/purposes.json grant_scopes (checked by tests).
GRANT_SCOPES: Mapping[str, frozenset[str]] = {
    "service_processing": frozenset({"SPECIMEN"}),
    "image_retention": frozenset({"SUBJECT_WIDE", "SPECIMEN"}),
    "third_party_ai_processing": frozenset({"REPORT"}),
    "ordinary_sharing": frozenset({"SHARE_GRANT"}),
    "partner_comparison": frozenset({"COMPARISON"}),
    "reference_contribution": frozenset({"SUBJECT_WIDE", "SPECIMEN"}),
    "engineering_evaluation": frozenset({"PILOT_ENROLLMENT", "SPECIMEN"}),
    "support_human_review": frozenset({"SUPPORT_CASE"}),
    "product_analytics": frozenset({"SUBJECT_WIDE"}),
    "model_training": frozenset(),
    "public_example": frozenset(),
}
SCOPE_KINDS = frozenset({"SUBJECT_WIDE", "SPECIMEN", "REPORT", "SHARE_GRANT", "COMPARISON", "PILOT_ENROLLMENT",
                         "SUPPORT_CASE"})


class Decision(str, Enum):
    GRANT = "GRANT"
    DENY = "DENY"
    WITHDRAW = "WITHDRAW"


def current_version(purpose_id: str) -> int:
    versions = g.PURPOSE_AUTHORITY["versions"].get(purpose_id)
    if not versions:
        raise InvalidInput("unknown_purpose", detail=purpose_id[:64])
    return max(versions)


@dataclass(frozen=True)
class Scope:
    kind: str
    ref: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in SCOPE_KINDS:
            raise InvalidInput("unknown_scope_kind")
        if (self.kind == "SUBJECT_WIDE") != (self.ref is None):
            raise InvalidInput("scope_ref_mismatch")
        if self.ref is not None:
            require_opaque_id(self.ref, "scope_ref")

    @property
    def subject_wide(self) -> bool:
        return self.kind == "SUBJECT_WIDE"


SUBJECT_WIDE = Scope("SUBJECT_WIDE")


@dataclass(frozen=True)
class PermissionEvent:
    event_id: str
    subject_id: str
    purpose_id: str
    purpose_version: int
    scope: Scope
    decision: Decision
    recorded_at: datetime
    effective_at: datetime
    actor_id: str
    notice_version: str
    sequence: int = 0  # store-assigned monotonic tie-breaker

    def __post_init__(self) -> None:
        for name in ("event_id", "subject_id", "actor_id", "notice_version"):
            require_opaque_id(getattr(self, name), name)
        require_utc(self.recorded_at, "recorded_at")
        require_utc(self.effective_at, "effective_at")
        versions = g.PURPOSE_AUTHORITY["versions"].get(self.purpose_id)
        if not versions or self.purpose_version not in versions:
            raise InvalidInput("unknown_purpose_version")
        if self.effective_at < self.recorded_at:
            raise InvalidInput("backdated_permission_event")
        if self.decision is Decision.GRANT:
            if self.scope.kind not in GRANT_SCOPES[self.purpose_id]:
                raise InvalidInput("scope_not_grantable")
        elif not self.scope.subject_wide and self.scope.kind not in GRANT_SCOPES[self.purpose_id]:
            raise InvalidInput("scope_not_applicable")


@dataclass(frozen=True)
class Effective:
    allowed: bool
    reason: str
    event_id: str | None = None


def evaluate(events: Iterable[PermissionEvent], *, subject_id: str, purpose_id: str, scope: Scope,
             at: datetime) -> Effective:
    """Effective permission for one use, evaluated from the full history."""
    require_utc(at, "at")
    current = current_version(purpose_id)
    relevant = [e for e in events
                if e.subject_id == subject_id and e.purpose_id == purpose_id and e.effective_at <= at
                # A subject-wide event applies to every scope; a subject-wide grant
                # can only exist where the purpose allows one (checked at construction).
                and (e.scope == scope or e.scope.subject_wide)]
    if not relevant:
        return Effective(False, "no_decision")
    latest = max(relevant, key=lambda e: (e.recorded_at, e.sequence))
    if latest.decision is not Decision.GRANT:
        return Effective(False, latest.decision.value.lower(), latest.event_id)
    if latest.purpose_version != current:
        return Effective(False, "stale_purpose_version", latest.event_id)
    return Effective(True, "granted", latest.event_id)
