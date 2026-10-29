"""Deterministic analysis worker (T04 → T05 → T09).

Work happens outside any database transaction: claim a leased job, read the
immutable capture, decode within limits, run the zero-AI engine, build the
evidence bundle and report, then publish in one short fenced transaction.
Publication is refused when the lease token is stale, the job was cancelled,
the capture was deleted, or the service-processing permission epoch moved.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from datetime import datetime
from typing import Any, Callable, Mapping, Protocol

from princess_contracts import ValidatedDocument
from princess_graphology.preprocessing.grid import GridQualityError

from ..domain.analysis import analysis_reference
from ..domain.evidence import build_evidence_bundle
from ..domain.reports import assemble_report
from ..domain.reports.story import STORY_TEMPLATE_VERSION, StoryPolicy
from ..domain.reports.template import EVIDENCE_SUPPORT_TEMPLATE_VERSION, TEMPLATE_VERSION
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
    report_template: str  # saved at admission; NEVER selected by a later deployment
    story_source_sha256: str | None = None  # /4 immutable authored source at admission
    report_locale: str | None = None  # /4 explicit user-admitted EN/SV locale


class Fenced(Exception):
    """Publication refused: this worker's claim is no longer authoritative."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class JobQueue(Protocol):
    def claim(self, worker_id: str, lease_seconds: int, now: datetime, *,
              report_template: str, analysis_config: str,
              story_source_sha256: str | None = None) -> ClaimedJob | None: ...

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
                 lease_seconds: int = 120,
                 writer_template: str = TEMPLATE_VERSION,
                 story_policy: StoryPolicy | None = None,
                 story_source_sha256: str | None = None,
                 private_qualified_story_candidate: bool = False) -> None:
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
        # The composition layer resolves strict deployment flags and approved
        # source authority. This application service accepts only the resulting
        # version, not config/env objects or HTTP-controlled values.
        if writer_template not in (TEMPLATE_VERSION, STORY_TEMPLATE_VERSION):
            raise InvalidInput("report_writer_template_unknown")
        if type(private_qualified_story_candidate) is not bool or (
                private_qualified_story_candidate and writer_template != STORY_TEMPLATE_VERSION):
            raise InvalidInput("report_story_candidate_invalid")
        if writer_template == STORY_TEMPLATE_VERSION:
            if not isinstance(story_policy, StoryPolicy):
                raise InvalidInput("report_story_source_not_installed")
            if (not isinstance(story_source_sha256, str)
                    or re.fullmatch(r"[0-9a-f]{64}", story_source_sha256) is None):
                raise InvalidInput("report_story_source_pin_missing")
            if getattr(engine, "evidence_guard_enabled", False):
                if not (private_qualified_story_candidate
                        and getattr(engine, "grid_profile", None) == "qualified-v2"):
                    raise InvalidInput("report_story_research_guard_conflict")
            elif private_qualified_story_candidate:
                raise InvalidInput("report_story_candidate_invalid")
        elif story_policy is not None or story_source_sha256 is not None:
            raise InvalidInput("report_story_policy_without_writer")
        self._writer_template = writer_template
        self._story_policy = story_policy
        self._story_source_sha256 = story_source_sha256
        self._private_qualified_story_candidate = private_qualified_story_candidate

    def run_once(self) -> WorkOutcome | None:
        # Select only jobs pinned to the writer this process can execute.
        # Old queued /2 work must stay QUEUED during a /4-only rollout;
        # it may be resumed by a compatible /2 worker after rollback.
        report_template = (EVIDENCE_SUPPORT_TEMPLATE_VERSION
                           if (getattr(self._engine, "evidence_guard_enabled", False)
                               and not self._private_qualified_story_candidate)
                           else self._writer_template)
        job = self._queue.claim(self._worker_id, self._lease, self._clock.now(),
                                report_template=report_template, analysis_config=self._config,
                                story_source_sha256=self._story_source_sha256)
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
        expected_template = (EVIDENCE_SUPPORT_TEMPLATE_VERSION
                             if (getattr(self._engine, "evidence_guard_enabled", False)
                                 and not self._private_qualified_story_candidate)
                             else self._writer_template)
        if job.report_template != expected_template:
            raise InvalidInput("report_writer_template_mismatch")
        if job.report_template == STORY_TEMPLATE_VERSION:
            if job.story_source_sha256 != self._story_source_sha256:
                raise InvalidInput("report_story_source_pin_mismatch")
            if job.report_locale not in ("en", "sv"):
                raise InvalidInput("report_story_locale_invalid")
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
            created_at=now, engine_version=self._engine_version, analysis_config_sha256=self._config,
            quality_policy=("quality-policy/2" if getattr(self._engine, "grid_profile", "") == "qualified-v2"
                            else "quality-policy/1"),
            template=job.report_template)
        evidence = build_evidence_bundle(payload, reference, f"evidence_{job.run_id}")
        if evidence.value is None:
            raise Conflict("evidence_contract_rejected")
        report = assemble_report(report_id=f"report_{job.run_id}", analysis=reference, result=result, created_at=now,
                                 locale=job.report_locale if job.report_template == STORY_TEMPLATE_VERSION else "en",
                                 evidence=evidence.value, story_policy=self._story_policy)
        if report.value is None:
            raise Conflict("report_contract_rejected")
        self._queue.publish(job, result=result, evidence=evidence.value, report=report.value,
                            processed_sha256=processed, now=self._clock.now())
        return WorkOutcome(job.job_id, "SUCCEEDED")


__all__ = ["AnalysisWorker", "ClaimedJob", "Fenced", "JobQueue", "MAX_ATTEMPTS", "WorkOutcome"]
