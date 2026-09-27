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
from ..domain.permissions import Decision, Scope
from ..ports.abuse import AbuseChallengeProvider, Verdict
from ..ports.base import (
    CallContext,
    Clock,
    Conflict,
    IdGenerator,
    InvalidInput,
    NotAuthorized,
    NotFound,
    PortError,
    Unsupported,
)
from ..ports.storage import ObjectStore, StoredObject, UploadPolicy, UploadTicket
from .permissions import PermissionService

ANALYSIS_KIND = "analysis"
SERVICE_PURPOSE = "service_processing"
RETENTION_PURPOSE = "image_retention"
CHALLENGE_ACTION = "upload"
ENGINE_MAX_DIMENSION = 2200


def analysis_config_sha256(max_dimension: int = ENGINE_MAX_DIMENSION, deskew: bool = True) -> str:
    """Digest of the engine settings a run is requested and executed under."""
    return hashlib.sha256(f"engine:max_dimension={max_dimension};deskew={'true' if deskew else 'false'};"
                          f"{policy.INTAKE_POLICY_VERSION}".encode()).hexdigest()


def engine_config_sha256(engine: object) -> str:
    return analysis_config_sha256(getattr(engine, "max_dimension"), getattr(engine, "deskew_enabled"))


ANALYSIS_CONFIG_SHA256 = analysis_config_sha256()


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
    original_erased: bool = False  # the retention policy already erased the source bytes

    def stored_object(self) -> StoredObject:
        return StoredObject(self.asset_id, self.version_ref, self.sha256, self.size_bytes, self.media_type)


@dataclass(frozen=True)
class RunStatus:
    run_id: str
    state: str  # QUEUED | RUNNING | SUCCEEDED | FAILED | CANCELLED
    report_id: str | None
    error_code: str | None


class IntakeRepository(Protocol):
    def admit_upload(self, owner_id: str, *, since: datetime, limit: int, created_at: datetime,
                     issue: Callable[[], UploadRow]) -> UploadRow:
        """Serialize per owner: count reservations since ``since``, refuse at
        ``limit`` (RateLimited), otherwise ``issue`` a slot and record it."""
        ...

    def begin_completion(self, owner_id: str, upload_id: str) -> bool:
        """RESERVED -> COMPLETING; False if another completion holds it."""
        ...

    def release_completion(self, owner_id: str, upload_id: str) -> None:
        """COMPLETING -> RESERVED after a retryable completion failure."""
        ...

    def reject_upload(self, owner_id: str, upload_id: str, asset_id: str, at: datetime) -> None:
        """COMPLETING -> REJECTED and queue erasure of the promoted bytes, atomically."""
        ...

    def upload(self, owner_id: str, upload_id: str) -> UploadRow | None: ...

    def capture_for_upload(self, owner_id: str, upload_id: str) -> CaptureRow | None: ...

    def record_capture(self, capture: CaptureRow, at: datetime) -> CaptureRow:
        """Atomically add the asset and capture rows and complete the upload.
        A concurrent duplicate returns the already recorded capture."""
        ...

    def capture(self, owner_id: str, capture_id: str) -> CaptureRow | None: ...

    def find_analysis(self, owner_id: str, dedupe_key: str) -> str | None: ...

    def create_analysis(self, capture: CaptureRow, *, run_id: str, job_id: str, dedupe_key: str,
                        permission_epoch: int, analysis_config: str, at: datetime, max_active: int) -> str:
        """Create the QUEUED run and job, or return the existing run for ``dedupe_key``.
        Counting active jobs and creating one is atomic per owner; raises
        ``RateLimited("too_many_active_analyses")`` at capacity."""
        ...

    def run_status(self, owner_id: str, run_id: str) -> RunStatus | None: ...

    def cancel_run(self, owner_id: str, run_id: str, at: datetime) -> bool: ...

    def delete_capture(self, owner_id: str, capture_id: str, at: datetime) -> None: ...

    def captures(self, owner_id: str) -> list[str]:
        """IDs of the owner's live captures."""
        ...

    def request_retention_review(self, owner_id: str, capture_id: str, at: datetime) -> None:
        """Queue a check that erases the original unless image retention is granted."""
        ...


@dataclass(frozen=True)
class ChallengeProof:
    """Only the client's token: the expected action and site are server-owned."""

    token: str


def propagate_withdrawal(repo: IntakeRepository, owner_id: str, purpose_id: str, scope: Scope,
                         decision: Decision, at: datetime) -> None:
    """Idempotent effects of a service-processing or image-retention
    withdrawal. The API applies them at once; the durable
    ``permission.withdrawn`` outbox event (queued with the decision) re-applies
    them if the process died in between."""
    if decision is Decision.GRANT or purpose_id not in (SERVICE_PURPOSE, RETENTION_PURPOSE):
        return
    if scope.kind == "SUBJECT_WIDE":
        targets = repo.captures(owner_id)
    elif scope.kind == "SPECIMEN" and scope.ref is not None:
        targets = [scope.ref] if repo.capture(owner_id, scope.ref) is not None else []
    else:
        return
    for capture_id in targets:
        if purpose_id == SERVICE_PURPOSE:
            repo.delete_capture(owner_id, capture_id, at)
        else:
            repo.request_retention_review(owner_id, capture_id, at)


class IntakeService:
    def __init__(self, *, repo: IntakeRepository, store: ObjectStore, permissions: PermissionService,
                 challenge: AbuseChallengeProvider, inspect: Callable[[bytes], ImageHeader], clock: Clock,
                 ids: IdGenerator, challenge_site: str, uploads_enabled: Callable[[], bool] = lambda: True,
                 analysis_config: str = ANALYSIS_CONFIG_SHA256) -> None:
        self._repo = repo
        self._site = challenge_site
        self._config = analysis_config
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
            verdict = self._challenge.verify(proof.token, CHALLENGE_ACTION, self._site, ctx).verdict
            if verdict is Verdict.REJECTED:
                raise NotAuthorized("challenge_rejected")
            if verdict is Verdict.ACCEPTED:
                limit = policy.UPLOADS_PER_DAY
        now = self._clock.now()
        issued: list[UploadTicket] = []

        def issue() -> UploadRow:
            asset_id = self._ids.new_id("asset")
            ticket = self._store.issue_upload_ticket(
                asset_id, media_type,
                UploadPolicy(frozenset({media_type}), policy.MAX_UPLOAD_BYTES, policy.UPLOAD_TICKET_SECONDS), ctx)
            issued.append(ticket)
            return UploadRow(ticket.upload_id, owner_id, asset_id, media_type, policy.MAX_UPLOAD_BYTES, "RESERVED",
                             ticket.expires_at)

        self._repo.admit_upload(owner_id, since=now - timedelta(days=1), limit=limit, created_at=now, issue=issue)
        return issued[0]

    def complete_upload(self, owner_id: str, upload_id: str, declared_sha256: str, ctx: CallContext) -> CaptureRow:
        existing = self._repo.capture_for_upload(owner_id, upload_id)
        if existing is not None:
            if existing.sha256 != declared_sha256:
                raise Conflict("upload_completed_with_different_bytes")
            return existing
        upload = self._repo.upload(owner_id, upload_id)
        if upload is None or upload.state not in ("RESERVED", "COMPLETING"):
            raise NotFound("upload_not_found")
        if self._clock.now() >= upload.expires_at:
            raise Conflict("upload_expired")
        if not self._repo.begin_completion(owner_id, upload_id):
            # Another completion won: converge only if it recorded the same bytes.
            existing = self._repo.capture_for_upload(owner_id, upload_id)
            if existing is None:
                raise Conflict("completion_in_progress")
            if existing.sha256 != declared_sha256:
                raise Conflict("upload_completed_with_different_bytes")
            return existing
        try:
            stored = self._store.promote_verified_input(upload_id, declared_sha256, ctx)
            header = self._inspect(self._store.read_object(stored, ctx))
            policy.check_header(header, upload.media_type)
        except InvalidInput:
            # Leave COMPLETING and queue durable erasure first, so a failed
            # delete below is retried by the erasure worker, not stranded.
            self._repo.reject_upload(owner_id, upload_id, upload.asset_id, self._clock.now())
            try:
                self._store.delete_asset_versions(upload.asset_id, ctx)
            except PortError:
                pass
            raise
        except PortError:
            # Wrong digest, missing bytes or a transient store failure: the slot stays usable.
            self._repo.release_completion(owner_id, upload_id)
            raise
        width, height = header.oriented_size  # the frame the analysis runs in, after EXIF rotation
        capture = CaptureRow(
            capture_id=self._ids.new_id("capture"), owner_id=owner_id, upload_id=upload_id,
            asset_id=stored.asset_id, media_type=header.media_type, width=width, height=height,
            exif_orientation=header.exif_orientation, sha256=stored.sha256, version_ref=stored.version_ref,
            size_bytes=stored.size_bytes)
        return self._repo.record_capture(capture, self._clock.now())

    def start_analysis(self, owner_id: str, capture_id: str) -> str:
        capture = self._repo.capture(owner_id, capture_id)
        if capture is None or capture.deleted:
            raise NotFound("capture_not_found")
        if capture.original_erased:
            raise Conflict("original_not_retained")
        epoch = self._permissions.require(owner_id, SERVICE_PURPOSE, Scope("SPECIMEN", capture_id))
        dedupe_key = f"{ANALYSIS_KIND}:{capture_id}:{self._config[:16]}"
        existing = self._repo.find_analysis(owner_id, dedupe_key)
        if existing is not None:
            return existing  # a retried submission recovers its run even at capacity
        return self._repo.create_analysis(
            capture, run_id=self._ids.new_id("run"), job_id=self._ids.new_id("job"), dedupe_key=dedupe_key,
            permission_epoch=epoch, analysis_config=self._config, at=self._clock.now(),
            max_active=policy.MAX_ACTIVE_JOBS)

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

    def apply_permission_change(self, owner_id: str, purpose_id: str, scope: Scope, decision: Decision) -> None:
        """T03 withdrawal propagation for intake-owned retention classes.

        Withdrawing service processing ends the capture's upload original and
        analysis record (the report is tombstoned and bytes are erased).
        Withdrawing image retention queues erasure of the original only.
        """
        propagate_withdrawal(self._repo, owner_id, purpose_id, scope, decision, self._clock.now())
