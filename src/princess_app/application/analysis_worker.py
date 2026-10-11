"""Deterministic analysis worker (T04 → T05 → T09).

Work happens outside any database transaction: claim a leased job, read the
immutable capture, decode within limits, run the zero-AI engine, build the
evidence bundle and report, then publish in one short fenced transaction.
Publication is refused when the lease token is stale, the job was cancelled,
the capture was deleted, or the service-processing permission epoch moved.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Protocol

from princess_contracts import ValidatedDocument
from princess_graphology.preprocessing.grid import GridQualityError

from ..domain.analysis import analysis_reference
from ..domain.evidence import build_evidence_bundle
from ..domain.reports import assemble_report
from ..ports.base import CallContext, Clock, Conflict, InvalidInput, PortError
from ..ports.storage import ObjectStore
from .intake import CaptureRow, engine_config_sha256

MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class ClaimedJob:
    job_id: str
    owner_id: str
    run_id: str
    capture_id: str
    fencing_token: int
    attempts: int
    permission_epoch: int
    analysis_config: str  # engine settings the run was requested under


class Fenced(Exception):
    """Publication refused: this worker's claim is no longer authoritative."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class JobQueue(Protocol):
    def claim(self, worker_id: str, lease_seconds: int, now: datetime) -> ClaimedJob | None: ...

    def capture(self, job: ClaimedJob) -> CaptureRow | None: ...

    def fail(self, job: ClaimedJob, error_code: str, *, retry: bool, now: datetime) -> None: ...

    def publish(self, job: ClaimedJob, *, result: Mapping[str, Any], evidence: ValidatedDocument,
                report: ValidatedDocument, processed_sha256: str, now: datetime) -> None:
        """Commit run result, projections, evidence, report and job success
        atomically, after re-checking fence, cancellation, deletion and
        permission epoch under locks. Raises ``Fenced``."""
        ...


Decoder = Callable[[bytes, str], Any]  # returns an object with .pixels


@dataclass(frozen=True)
class WorkOutcome:
    job_id: str
    outcome: str  # SUCCEEDED | FAILED | RETRY | FENCED
    detail: str | None = None


class AnalysisWorker:
    def __init__(self, *, queue: JobQueue, store: ObjectStore, decode: Decoder, engine: Any, clock: Clock,
                 context: Callable[[], CallContext], worker_id: str, engine_version: str,
                 lease_seconds: int = 120) -> None:
        self._queue = queue
        self._store = store
        self._decode = decode
        self._engine = engine
        self._config = engine_config_sha256(engine)
        self._clock = clock
        self._context = context
        self._worker_id = worker_id
        self._engine_version = engine_version
        self._lease = lease_seconds

    def run_once(self) -> WorkOutcome | None:
        job = self._queue.claim(self._worker_id, self._lease, self._clock.now())
        if job is None:
            return None
        try:
            return self._process(job)
        except Fenced as fenced:
            return WorkOutcome(job.job_id, "FENCED", fenced.reason)
        except InvalidInput as bad:
            self._queue.fail(job, bad.code, retry=False, now=self._clock.now())
            return WorkOutcome(job.job_id, "FAILED", bad.code)
        except (PortError, OSError, RuntimeError, ValueError) as exc:
            code = exc.code if isinstance(exc, PortError) else "analysis_error"
            retry = job.attempts < MAX_ATTEMPTS
            self._queue.fail(job, code, retry=retry, now=self._clock.now())
            return WorkOutcome(job.job_id, "RETRY" if retry else "FAILED", code)

    def _process(self, job: ClaimedJob) -> WorkOutcome:
        if job.analysis_config != self._config:
            # Never publish results computed under settings other than the run's.
            raise InvalidInput("analysis_config_mismatch")
        capture = self._queue.capture(job)
        if capture is None or capture.deleted:
            raise Fenced("capture_deleted")
        data = self._store.read_object(capture.stored_object(), self._context())
        decoded = self._decode(data, capture.media_type)
        try:
            result_obj, payload = self._engine.analyze_with_evidence(decoded.pixels,
                                                                    source=f"capture:{capture.capture_id}")
        except GridQualityError as exc:
            raise InvalidInput(exc.code) from exc
        result = result_obj.to_dict()
        processed = result["metadata"]["input_pixels_sha256"]
        now = self._clock.now()
        reference = analysis_reference(
            analysis_id=f"analysis_{job.run_id}", run_id=job.run_id, owner_id=job.owner_id,
            input_asset_id=capture.asset_id, input_sha256=capture.sha256, processed_sha256=processed,
            created_at=now, engine_version=self._engine_version, analysis_config_sha256=self._config)
        evidence = build_evidence_bundle(payload, reference, f"evidence_{job.run_id}")
        if evidence.value is None:
            raise Conflict("evidence_contract_rejected")
        report = assemble_report(report_id=f"report_{job.run_id}", analysis=reference, result=result, created_at=now,
                                 locale="en", evidence=evidence.value)
        if report.value is None:
            raise Conflict("report_contract_rejected")
        self._queue.publish(job, result=result, evidence=evidence.value, report=report.value,
                            processed_sha256=processed, now=self._clock.now())
        return WorkOutcome(job.job_id, "SUCCEEDED")


__all__ = ["AnalysisWorker", "ClaimedJob", "Fenced", "JobQueue", "MAX_ATTEMPTS", "WorkOutcome"]
