"""Safe intake use cases (T04): upload slots, verified captures and the
explicit, idempotent transition to one deterministic analysis run.

Upload completion validates and promotes bytes to an immutable version and
records a capture; it never creates a run. ``start_analysis`` does, under a
service-processing permission for that capture, and records the permission
epoch so the worker cannot publish after a withdrawal.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Protocol

from ..domain import intake as policy
from ..domain.intake import ImageHeader
from ..domain.permissions import Scope
from ..ports.abuse import AbuseChallengeProvider, Verdict
from ..ports.base import (
    CallContext,
    Clock,
    Conflict,
    IdGenerator,
    InvalidInput,
    NotAuthorized,
    NotFound,
    RateLimited,
    Unsupported,
)
from ..ports.storage import ObjectStore, StoredObject, UploadPolicy, UploadTicket
from .permissions import PermissionService

ANALYSIS_KIND = "analysis"
SERVICE_PURPOSE = "service_processing"
ENGINE_MAX_DIMENSION = 2200
ANALYSIS_CONFIG_SHA256 = hashlib.sha256(
    f"engine:max_dimension={ENGINE_MAX_DIMENSION};deskew=true;{policy.INTAKE_POLICY_VERSION}".encode()).hexdigest()


@dataclass(frozen=True)
class UploadRow:
    upload_id: str
    owner_id: str
    asset_id: str
    media_type: str
    max_bytes: int
    state: str
    expires_at: datetime


@dataclass(frozen=True)
class CaptureRow:
    capture_id: str
    owner_id: str
    upload_id: str
    asset_id: str
    media_type: str
    width: int
    height: int
    exif_orientation: int
    sha256: str
    version_ref: str
    size_bytes: int
    deleted: bool = False

    def stored_object(self) -> StoredObject:
        return StoredObject(self.asset_id, self.version_ref, self.sha256, self.size_bytes, self.media_type)


@dataclass(frozen=True)
class RunStatus:
    run_id: str
    state: str  # QUEUED | RUNNING | SUCCEEDED | FAILED | CANCELLED
    report_id: str | None
    error_code: str | None


class IntakeRepository(Protocol):
    def count_uploads_since(self, owner_id: str, since: datetime) -> int: ...

    def create_upload(self, row: UploadRow, created_at: datetime) -> None: ...

    def upload(self, owner_id: str, upload_id: str) -> UploadRow | None: ...

    def capture_for_upload(self, owner_id: str, upload_id: str) -> CaptureRow | None: ...

    def record_capture(self, capture: CaptureRow, at: datetime) -> CaptureRow:
        """Atomically add the asset and capture rows and complete the upload.
        A concurrent duplicate returns the already recorded capture."""
        ...

    def capture(self, owner_id: str, capture_id: str) -> CaptureRow | None: ...

    def count_active_jobs(self, owner_id: str) -> int: ...

    def create_analysis(self, capture: CaptureRow, *, run_id: str, job_id: str, dedupe_key: str,
                        permission_epoch: int, at: datetime) -> str:
        """Create the QUEUED run and job, or return the existing run for ``dedupe_key``."""
        ...

    def run_status(self, owner_id: str, run_id: str) -> RunStatus | None: ...

    def cancel_run(self, owner_id: str, run_id: str, at: datetime) -> bool: ...

    def delete_capture(self, owner_id: str, capture_id: str, at: datetime) -> None: ...


@dataclass(frozen=True)
class ChallengeProof:
    token: str
    action: str
    site: str


class IntakeService:
    def __init__(self, *, repo: IntakeRepository, store: ObjectStore, permissions: PermissionService,
                 challenge: AbuseChallengeProvider, inspect: Callable[[bytes], ImageHeader], clock: Clock,
                 ids: IdGenerator, uploads_enabled: Callable[[], bool] = lambda: True) -> None:
        self._repo = repo
        self._store = store
        self._permissions = permissions
        self._challenge = challenge
        self._inspect = inspect
        self._clock = clock
        self._ids = ids
        self._uploads_enabled = uploads_enabled

    def reserve_upload(self, owner_id: str, media_type: str, proof: ChallengeProof | None,
                       ctx: CallContext) -> UploadTicket:
        if not self._uploads_enabled():
            raise Unsupported("uploads_disabled")
        if media_type not in policy.ALLOWED_MEDIA:
            raise InvalidInput("unsupported_media")
        limit = policy.UPLOADS_PER_DAY_WITHOUT_CHALLENGE
        if proof is not None:
            verdict = self._challenge.verify(proof.token, proof.action, proof.site, ctx).verdict
            if verdict is Verdict.REJECTED:
                raise NotAuthorized("challenge_rejected")
            if verdict is Verdict.ACCEPTED:
                limit = policy.UPLOADS_PER_DAY
        now = self._clock.now()
        if self._repo.count_uploads_since(owner_id, now - timedelta(days=1)) >= limit:
            raise RateLimited("upload_quota_exceeded", retry_after_s=3600)
        asset_id = self._ids.new_id("asset")
        ticket = self._store.issue_upload_ticket(
            asset_id, media_type,
            UploadPolicy(frozenset({media_type}), policy.MAX_UPLOAD_BYTES, policy.UPLOAD_TICKET_SECONDS), ctx)
        self._repo.create_upload(UploadRow(ticket.upload_id, owner_id, asset_id, media_type,
                                           policy.MAX_UPLOAD_BYTES, "RESERVED", ticket.expires_at), now)
        return ticket

    def complete_upload(self, owner_id: str, upload_id: str, declared_sha256: str, ctx: CallContext) -> CaptureRow:
        existing = self._repo.capture_for_upload(owner_id, upload_id)
        if existing is not None:
            if existing.sha256 != declared_sha256:
                raise Conflict("upload_completed_with_different_bytes")
            return existing
        upload = self._repo.upload(owner_id, upload_id)
        if upload is None or upload.state != "RESERVED":
            raise NotFound("upload_not_found")
        if self._clock.now() >= upload.expires_at:
            raise Conflict("upload_expired")
        stored = self._store.promote_verified_input(upload_id, declared_sha256, ctx)
        data = self._store.read_object(stored, ctx)
        try:
            header = self._inspect(data)
            policy.check_header(header, upload.media_type)
        except InvalidInput:
            self._store.delete_asset_versions(stored.asset_id, ctx)
            raise
        capture = CaptureRow(
            capture_id=self._ids.new_id("capture"), owner_id=owner_id, upload_id=upload_id,
            asset_id=stored.asset_id, media_type=header.media_type, width=header.width, height=header.height,
            exif_orientation=header.exif_orientation, sha256=stored.sha256, version_ref=stored.version_ref,
            size_bytes=stored.size_bytes)
        return self._repo.record_capture(capture, self._clock.now())

    def start_analysis(self, owner_id: str, capture_id: str) -> str:
        capture = self._repo.capture(owner_id, capture_id)
        if capture is None or capture.deleted:
            raise NotFound("capture_not_found")
        epoch = self._permissions.require(owner_id, SERVICE_PURPOSE, Scope("SPECIMEN", capture_id))
        if self._repo.count_active_jobs(owner_id) >= policy.MAX_ACTIVE_JOBS:
            raise RateLimited("too_many_active_analyses", retry_after_s=60)
        return self._repo.create_analysis(
            capture, run_id=self._ids.new_id("run"), job_id=self._ids.new_id("job"),
            dedupe_key=f"{ANALYSIS_KIND}:{capture_id}:{ANALYSIS_CONFIG_SHA256[:16]}", permission_epoch=epoch,
            at=self._clock.now())

    def status(self, owner_id: str, run_id: str) -> RunStatus:
        status = self._repo.run_status(owner_id, run_id)
        if status is None:
            raise NotFound("run_not_found")
        return status

    def cancel(self, owner_id: str, run_id: str) -> RunStatus:
        if not self._repo.cancel_run(owner_id, run_id, self._clock.now()):
            raise NotFound("run_not_found")
        return self.status(owner_id, run_id)

    def delete_capture(self, owner_id: str, capture_id: str) -> None:
        """Tombstone now (running work cannot publish); byte erasure is queued."""
        if self._repo.capture(owner_id, capture_id) is None:
            raise NotFound("capture_not_found")
        self._repo.delete_capture(owner_id, capture_id, self._clock.now())
