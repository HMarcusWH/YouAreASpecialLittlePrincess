"""One bounded Premium attempt: authorize → compile → call once → validate → publish.

The runner never retries on its own. It reports a typed outcome per attempt so
the job/commerce layer (T19) can decide on the single permitted automatic
retry, release or keep a credit reservation, and reconcile ambiguous
outcomes. A provider timeout after transmission is ``AMBIGUOUS``: the remote
side may have executed, so the budget reservation is kept for reconciliation.

Publication is a separate port so the durable implementation can re-check the
permission epoch and deletion fence in the same transaction as the write.
Nothing here is reachable from report read, export or share paths.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Mapping, Protocol

from princess_contracts import ValidatedDocument

from ...domain.permissions import Scope
from ...ports import model as port
from ...ports.base import (
    AmbiguousOutcome,
    CallContext,
    Clock,
    DeadlineExceeded,
    IdGenerator,
    PortError,
    RateLimited,
    TransientUnavailable,
)
from ...ports.storage import StoredObject
from ..permissions import PermissionService
from ..reports import ReportStore
from .database import InterpretationDatabase
from .packet import CandidateProducer, NotApplicable, Omission, PacketCompilation, compile_packet
from .prompt import POLICY_ID
from .validation import output_schema, validate_output

PURPOSE = "third_party_ai_processing"
MAX_ATTEMPTS = 2  # the first call plus at most one automated retry of a transient failure
MAX_OUTPUT_TOKENS = 4000


class Outcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    NOT_APPLICABLE = "NOT_APPLICABLE"      # nothing to ask; no provider call, nothing to charge
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"  # no provider call
    FENCED = "FENCED"                      # permission, deletion or report changed; not published
    REFUSED = "REFUSED"
    RETRYABLE = "RETRYABLE"                # transient failure before any provider execution is implied
    AMBIGUOUS = "AMBIGUOUS"                # sent; remote execution unknown
    FAILED = "FAILED"


@dataclass(frozen=True)
class PremiumJob:
    job_id: str
    owner_id: str
    report_id: str
    report_revision: int
    permission_epoch: int
    attempt_number: int = 1
    fencing_token: int = 0            # lease fence for durable publication
    reservation_id: str | None = None  # the credit this deliverable spends


@dataclass(frozen=True)
class PremiumOverlay:
    overlay_id: str
    job_id: str
    packet: ValidatedDocument
    output: ValidatedDocument
    omissions: tuple[Omission, ...]
    model_returned: str | None


@dataclass(frozen=True)
class AttemptRecord:
    attempt_id: str
    job_id: str
    outcome: Outcome
    error_code: str | None = None
    packet_digest: str | None = None
    provider_request_id: str | None = None
    model_requested: str | None = None
    model_returned: str | None = None
    usage: port.ProviderUsage = field(default_factory=port.ProviderUsage)
    issue_codes: tuple[str, ...] = ()
    revision: int | None = None  # published report revision on success


class Fenced(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ImageSource(Protocol):
    def authorized_image(self, owner_id: str, report: ValidatedDocument) -> StoredObject | None:
        """The report's source image if it still exists and may be processed, else None."""
        ...


class SpendBudget(Protocol):
    def reserve(self, attempt_id: str, max_output_tokens: int) -> bool: ...

    def settle(self, attempt_id: str, usage: port.ProviderUsage | None) -> None:
        """Replace a reservation with actual usage; ``None`` releases it."""
        ...


class OverlayPublisher(Protocol):
    def publish(self, job: PremiumJob, overlay: PremiumOverlay, now: datetime) -> int:
        """Atomically re-check permission epoch, deletion and report revision,
        then append the overlay revision. Returns it; raises ``Fenced``."""
        ...


class PremiumRunner:
    def __init__(self, *, reports: Callable[[str], ReportStore], permissions: PermissionService,
                 images: ImageSource, model: port.PremiumModelProvider, budget: SpendBudget,
                 publisher: OverlayPublisher, database: InterpretationDatabase, clock: Clock, ids: IdGenerator,
                 context: Callable[[], CallContext],
                 producers: Mapping[str, CandidateProducer] | None = None) -> None:
        self._reports = reports
        self._permissions = permissions
        self._images = images
        self._model = model
        self._budget = budget
        self._publisher = publisher
        self._db = database
        self._clock = clock
        self._ids = ids
        self._context = context
        self._producers = producers or {}

    def run(self, job: PremiumJob) -> AttemptRecord:
        attempt_id = self._ids.new_id("attempt")

        def record(outcome: Outcome, code: str | None = None, **extra) -> AttemptRecord:
            return AttemptRecord(attempt_id, job.job_id, outcome, code, **extra)

        check = self._permissions.check(job.owner_id, PURPOSE, Scope("REPORT", job.report_id))
        if not check.allowed or check.epoch != job.permission_epoch:
            return record(Outcome.FENCED, "permission_changed")
        latest = self._reports(job.owner_id).latest(job.report_id)
        if latest is None or latest[0] != job.owner_id:
            return record(Outcome.FENCED, "report_unavailable")
        report = latest[1]
        if report.data["revision"] != job.report_revision:
            return record(Outcome.FENCED, "report_revised")
        image = self._images.authorized_image(job.owner_id, report)
        try:
            compilation = compile_packet(report, self._db, packet_id=f"packet_{attempt_id}",
                                         created_at=self._clock.now(),
                                         image_asset_id=image.asset_id if image else None,
                                         producers=self._producers, owner_id=job.owner_id)
        except NotApplicable as na:
            return record(Outcome.NOT_APPLICABLE, na.reason)
        if not self._budget.reserve(attempt_id, MAX_OUTPUT_TOKENS):
            return record(Outcome.BUDGET_EXHAUSTED, "budget_exhausted")
        result = self._call(job, attempt_id, compilation, image, record)
        if isinstance(result, AttemptRecord):
            return result
        return self._finish(job, attempt_id, compilation, result, record)

    def _call(self, job, attempt_id, compilation: PacketCompilation, image, record):
        request = port.GenerationRequest(attempt_id=attempt_id, packet=compilation.model_input,
                                         packet_digest=compilation.model_input_digest,
                                         output_schema=output_schema(compilation), policy_version=POLICY_ID,
                                         image=image, max_output_tokens=MAX_OUTPUT_TOKENS)
        digest = compilation.model_input_digest
        try:
            return self._model.generate(request, self._context())
        except AmbiguousOutcome as exc:
            # Keep the reservation: the provider may have executed and billed.
            return record(Outcome.AMBIGUOUS, exc.code, packet_digest=digest)
        except (RateLimited, TransientUnavailable, DeadlineExceeded) as exc:
            self._budget.settle(attempt_id, None)
            outcome = Outcome.RETRYABLE if job.attempt_number < MAX_ATTEMPTS else Outcome.FAILED
            return record(outcome, exc.code, packet_digest=digest)
        except PortError as exc:
            self._budget.settle(attempt_id, None)
            return record(Outcome.FAILED, exc.code, packet_digest=digest)

    def _finish(self, job, attempt_id, compilation: PacketCompilation, result: port.ProviderGenerationResult,
                record) -> AttemptRecord:
        self._budget.settle(attempt_id, result.usage)
        meta = dict(packet_digest=compilation.model_input_digest, provider_request_id=result.provider_request_id,
                    model_requested=result.model_requested, model_returned=result.model_returned,
                    usage=result.usage)
        if result.state is port.GenerationState.REFUSED:
            return record(Outcome.REFUSED, "provider_refused", **meta)
        if result.state is port.GenerationState.INCOMPLETE:
            return record(Outcome.FAILED, "output_incomplete", **meta)
        validated = validate_output(compilation, result.output)
        if validated.value is None:
            return record(Outcome.FAILED, "output_rejected", issue_codes=tuple(sorted({i.code for i in validated.issues})),
                          **meta)
        overlay = PremiumOverlay(f"overlay_{attempt_id}", job.job_id, compilation.packet, validated.value,
                                 compilation.omissions, result.model_returned)
        try:
            revision = self._publisher.publish(job, overlay, self._clock.now())
        except Fenced as fenced:
            return record(Outcome.FENCED, fenced.reason, **meta)
        return record(Outcome.SUCCEEDED, revision=revision, **meta)


__all__ = ["AttemptRecord", "Fenced", "ImageSource", "MAX_ATTEMPTS", "Outcome", "OverlayPublisher",
           "PremiumJob", "PremiumOverlay", "PremiumRunner", "SpendBudget"]
