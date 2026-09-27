"""Erasure and retention consumer for intake assets (T04 over T03 retention).

Two outbox topics end the ``upload_original`` retention class:

* ``capture.deletion_requested`` — the owner deleted the capture or withdrew
  service processing: erase every object version, verify, record the erasure.
* ``capture.retention_review`` — an analysis finished or image retention was
  withdrawn: erase the original unless a current image-retention grant covers
  the capture. While an analysis for the capture is still queued or running
  the review waits, because the original is still needed to finish it.

A third topic, ``account.deletion_requested``, ends every retention class the
account owns: each remaining asset's object versions are erased and verified,
then the account's analysis records, reports and Premium payloads are removed
in one database step that refuses to run while any asset is unverified.

Deletes are idempotent, so an event processed twice (crash before marking it
dispatched, or two consumers) is harmless. An event whose erasure cannot be
verified stays pending and is retried.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Protocol

from ..domain.permissions import Scope
from ..ports.base import CallContext, Clock, PortError
from ..ports.storage import ObjectStore
from .intake import RETENTION_PURPOSE
from .permissions import PermissionService

DELETION = "capture.deletion_requested"
RETENTION_REVIEW = "capture.retention_review"
ACCOUNT_DELETION = "account.deletion_requested"
UPLOAD_REJECTED = "upload.rejected"  # promoted bytes failed inspection; erase them
TOPICS = (DELETION, RETENTION_REVIEW, ACCOUNT_DELETION, UPLOAD_REJECTED)


@dataclass(frozen=True)
class OutboxEvent:
    event_id: str
    topic: str
    owner_id: str
    aggregate_ref: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class CaptureAsset:
    asset_id: str
    capture_deleted: bool
    erased: bool
    active_jobs: int


class ErasureOutbox(Protocol):
    def pending(self, topics: tuple[str, ...], limit: int) -> list[OutboxEvent]: ...

    def capture_asset(self, owner_id: str, capture_id: str) -> CaptureAsset | None: ...

    def mark_erased(self, owner_id: str, asset_id: str, at: datetime) -> None: ...

    def unerased_assets(self, owner_id: str) -> list[str]:
        """Every asset of the owner (originals, derivatives, exports) not yet erased."""
        ...

    def erase_account_records(self, owner_id: str, at: datetime) -> None:
        """Delete a deleted account's rows once all its assets are erased."""
        ...

    def dispatched(self, event_id: str, at: datetime) -> None: ...


@dataclass(frozen=True)
class ErasureOutcome:
    event_id: str
    action: str  # ERASED | KEPT | WAITING | UNVERIFIED | SKIPPED


class ErasureWorker:
    def __init__(self, *, outbox: ErasureOutbox, store: ObjectStore, permissions: PermissionService, clock: Clock,
                 context: Callable[[], CallContext], batch: int = 20) -> None:
        self._outbox = outbox
        self._store = store
        self._permissions = permissions
        self._clock = clock
        self._context = context
        self._batch = batch

    def run_once(self) -> list[ErasureOutcome]:
        return [self._handle(event) for event in self._outbox.pending(TOPICS, self._batch)]

    def _handle(self, event: OutboxEvent) -> ErasureOutcome:
        now = self._clock.now()
        if event.topic == ACCOUNT_DELETION:
            return self._erase_account(event)
        if event.topic in (DELETION, UPLOAD_REJECTED):
            asset_id = event.payload.get("asset_id")
            if not isinstance(asset_id, str):
                self._outbox.dispatched(event.event_id, now)
                return ErasureOutcome(event.event_id, "SKIPPED")
            return self._erase(event, asset_id)
        asset = self._outbox.capture_asset(event.owner_id, event.aggregate_ref)
        if asset is None or asset.capture_deleted or asset.erased:
            self._outbox.dispatched(event.event_id, now)  # already handled by deletion
            return ErasureOutcome(event.event_id, "SKIPPED")
        if asset.active_jobs:
            return ErasureOutcome(event.event_id, "WAITING")
        retained = self._permissions.check(event.owner_id, RETENTION_PURPOSE, Scope("SPECIMEN", event.aggregate_ref))
        if retained.allowed:
            self._outbox.dispatched(event.event_id, now)
            return ErasureOutcome(event.event_id, "KEPT")
        return self._erase(event, asset.asset_id)

    def _erase_object(self, owner_id: str, asset_id: str) -> bool:
        ctx = self._context()
        try:
            self._store.delete_asset_versions(asset_id, ctx)
            verified = self._store.verify_deletion(asset_id, ctx)
        except PortError:
            return False
        if verified:
            self._outbox.mark_erased(owner_id, asset_id, self._clock.now())
        return verified

    def _erase(self, event: OutboxEvent, asset_id: str) -> ErasureOutcome:
        if not self._erase_object(event.owner_id, asset_id):
            return ErasureOutcome(event.event_id, "UNVERIFIED")
        self._outbox.dispatched(event.event_id, self._clock.now())
        return ErasureOutcome(event.event_id, "ERASED")

    def _erase_account(self, event: OutboxEvent) -> ErasureOutcome:
        for asset_id in self._outbox.unerased_assets(event.owner_id):
            if not self._erase_object(event.owner_id, asset_id):
                return ErasureOutcome(event.event_id, "UNVERIFIED")  # retried; rows stay until then
        now = self._clock.now()
        self._outbox.erase_account_records(event.owner_id, now)
        self._outbox.dispatched(event.event_id, now)
        return ErasureOutcome(event.event_id, "ERASED")


__all__ = ["ACCOUNT_DELETION", "CaptureAsset", "DELETION", "ErasureOutbox", "ErasureOutcome", "ErasureWorker", "OutboxEvent",
           "RETENTION_REVIEW", "TOPICS", "UPLOAD_REJECTED"]
