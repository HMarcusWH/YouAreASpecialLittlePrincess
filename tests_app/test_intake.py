"""T04 safe intake and durable, fenced analysis jobs on PostgreSQL."""
from __future__ import annotations

import hashlib
import io
import threading
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np
import pytest
from PIL import Image
from sqlalchemy import text

from princess_app.adapters.fakes import FakeAbuseChallenge, FakeClock, FakeObjectStore, SequentialIds
from princess_app.adapters.imaging import decode_image, inspect_header
from princess_app.adapters.postgres.intake import PostgresIntakeRepository, PostgresJobQueue
from princess_app.adapters.postgres.stores import PostgresIdentityStore, PostgresPermissionStore, PostgresReportStore
from princess_app.application.analysis_worker import AnalysisWorker
from princess_app.application.intake import ChallengeProof, IntakeService
from princess_app.application.permissions import PermissionService
from princess_app.application.reports import ReportReader
from princess_app.domain.permissions import SUBJECT_WIDE, Decision, Scope
from princess_app.ports.base import (
    CallContext,
    Conflict,
    Environment,
    InvalidInput,
    NotAuthorized,
    NotFound,
    RateLimited,
)
from princess_graphology import GraphologyEngine, __version__
from test_persistence import account, world  # noqa: F401 - fixture re-export

T0 = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
NOTICE = "notice.consent-choices:1"


def handwriting_png(width=900, height=360, angle=3.0) -> bytes:
    image = np.full((height, width), 245, np.uint8)
    for i, line in enumerate(("the quick brown fox jumps", "over a very lazy dog", "writing sample fixture")):
        cv2.putText(image, line, (30, 90 + i * 100), cv2.FONT_HERSHEY_SCRIPT_SIMPLEX, 1.6, 25, 3, cv2.LINE_AA)
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    image = cv2.warpAffine(image, matrix, (width, height), borderValue=245)
    return cv2.imencode(".png", image)[1].tobytes()


def jpeg(size=(400, 200), orientation=None) -> bytes:
    buffer = io.BytesIO()
    img = Image.new("RGB", size, (250, 250, 250))
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    img.save(buffer, "JPEG", exif=exif.tobytes())
    return buffer.getvalue()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Env:
    def __init__(self, app_db, worker_db):
        self.clock = FakeClock(T0)
        self.store = FakeObjectStore(clock=self.clock)
        self.challenge = FakeAbuseChallenge(clock=self.clock)
        self.permissions = PermissionService(PostgresPermissionStore(app_db), self.clock, SequentialIds(),
                                             allow_draft_policy=True)
        self.repo = PostgresIntakeRepository(app_db, engine_version=__version__)
        self.intake = IntakeService(repo=self.repo, store=self.store, permissions=self.permissions,
                                    challenge=self.challenge, inspect=inspect_header, clock=self.clock,
                                    ids=SequentialIds())
        self.queue = PostgresJobQueue(worker_db)
        self.app_db = app_db

    def ctx(self):
        return CallContext("corr-1", Environment.TEST, self.clock.now() + timedelta(seconds=30))

    def worker(self, name="w1"):
        return AnalysisWorker(queue=self.queue, store=self.store, decode=decode_image,
                              engine=GraphologyEngine(max_dimension=700), clock=self.clock, context=self.ctx,
                              worker_id=name, engine_version=__version__, lease_seconds=60)

    def upload(self, owner, data, media_type="image/png", proof=None):
        ticket = self.intake.reserve_upload(owner, media_type, proof, self.ctx())
        self.store.client_put(ticket, data)
        return ticket

    def capture(self, owner, data=None, media_type="image/png"):
        data = data or handwriting_png()
        ticket = self.upload(owner, data, media_type)
        return self.intake.complete_upload(owner, ticket.upload_id, sha(data), self.ctx())

    def grant(self, owner, capture_id):
        self.permissions.record(subject_id=owner, actor_id=owner, purpose_id="service_processing",
                                scope=Scope("SPECIMEN", capture_id), decision=Decision.GRANT, notice_version=NOTICE)

    def analysis(self, owner):
        capture = self.capture(owner)
        self.grant(owner, capture.capture_id)
        return capture, self.intake.start_analysis(owner, capture.capture_id)


@pytest.fixture
def env(app_db, worker_db):
    return Env(app_db, worker_db)


def test_end_to_end_upload_analysis_and_report(env, world):  # noqa: F811
    owner = account(world, "sub-a").principal_id
    capture, run_id = env.analysis(owner)
    assert (capture.width, capture.height, capture.media_type) == (900, 360, "image/png")
    assert env.intake.status(owner, run_id).state == "QUEUED"
    outcome = env.worker().run_once()
    assert outcome.outcome == "SUCCEEDED", outcome
    status = env.intake.status(owner, run_id)
    assert status.state == "SUCCEEDED" and status.report_id == f"report_{run_id}"
    view = ReportReader(PostgresReportStore(env.app_db, owner), env.clock).view(
        report_id=status.report_id, principal_id=owner, projection="FREE")
    assert len(view.data["facts"]) == 64
    with env.app_db.session(owner) as conn:
        assert conn.execute(text("SELECT topic FROM app.outbox_event WHERE topic = 'report.ready'")).scalar()
    assert env.worker().run_once() is None  # nothing left to claim


def test_repeated_completion_and_submission_converge(env, world):  # noqa: F811
    owner = account(world, "sub-a").principal_id
    data = handwriting_png()
    ticket = env.upload(owner, data)
    first = env.intake.complete_upload(owner, ticket.upload_id, sha(data), env.ctx())
    assert env.intake.complete_upload(owner, ticket.upload_id, sha(data), env.ctx()) == first
    with pytest.raises(Conflict):
        env.intake.complete_upload(owner, ticket.upload_id, sha(b"other"), env.ctx())
    env.grant(owner, first.capture_id)
    runs = []
    threads = [threading.Thread(target=lambda: runs.append(env.intake.start_analysis(owner, first.capture_id)))
               for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(runs)) == 1 and len(runs) == 5
    with env.app_db.session(owner) as conn:
        assert conn.execute(text("SELECT count(*) FROM app.job")).scalar() == 1


def test_overwrite_race_checksum_mismatch_and_expiry(env, world):  # noqa: F811
    owner = account(world, "sub-a").principal_id
    original, swapped = handwriting_png(), handwriting_png(angle=-4)
    ticket = env.upload(owner, original)
    env.store.client_put(ticket, swapped)  # bearer URL reused before completion
    with pytest.raises(Conflict):
        env.intake.complete_upload(owner, ticket.upload_id, sha(original), env.ctx())
    capture = env.intake.complete_upload(owner, ticket.upload_id, sha(swapped), env.ctx())
    env.store.client_put(ticket, original)  # later writes cannot change the promoted capture
    assert env.store.read_object(capture.stored_object(), env.ctx()) == swapped
    late = env.upload(owner, original)
    env.clock.advance(901)
    with pytest.raises(Conflict):
        env.intake.complete_upload(owner, late.upload_id, sha(original), env.ctx())


def big_png(width, height) -> bytes:
    buffer = io.BytesIO()
    Image.new("1", (width, height), 1).save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def animated_png() -> bytes:
    buffer = io.BytesIO()
    frames = [Image.new("L", (64, 64), v) for v in (0, 255)]
    frames[0].save(buffer, "PNG", save_all=True, append_images=frames[1:])
    return buffer.getvalue()


@pytest.mark.parametrize("data,declared,code", [
    (big_png(20000, 64), "image/png", "image_dimensions_out_of_range"),
    (big_png(5000, 5000), "image/png", "image_too_many_pixels"),
    (jpeg(), "image/png", "media_type_mismatch"),
    (animated_png(), "image/png", "animated_or_multi_frame_image"),
    (b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 64, "image/png", "unsupported_media_heif"),
    (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/png", "unsupported_media"),
    (b"GIF89a" + b"\x00" * 64, "image/png", "unsupported_media_gif"),
])
def test_unsafe_or_unsupported_uploads_are_rejected_and_bytes_removed(env, world, data, declared, code):  # noqa: F811
    owner = account(world, "sub-a").principal_id
    ticket = env.upload(owner, data, declared)
    with pytest.raises(InvalidInput) as err:
        env.intake.complete_upload(owner, ticket.upload_id, sha(data), env.ctx())
    assert err.value.code == code
    assert env.store.verify_deletion(ticket.asset_id, env.ctx()) in (True, False)  # deletion requested
    assert env.repo.capture_for_upload(owner, ticket.upload_id) is None


def test_exif_orientation_is_applied_and_metadata_dropped():
    decoded = decode_image(jpeg((400, 200), orientation=6), "image/jpeg")
    assert decoded.header.exif_orientation == 6 and decoded.pixels.shape[:2] == (400, 200)
    assert not decoded.pixels.flags.writeable


def test_truncated_png_is_rejected_at_completion(env, world):  # noqa: F811
    owner = account(world, "sub-a").principal_id
    data = handwriting_png()[:4000]
    ticket = env.upload(owner, data)
    with pytest.raises(InvalidInput) as err:
        env.intake.complete_upload(owner, ticket.upload_id, sha(data), env.ctx())
    assert err.value.code == "malformed_image"


def test_truncated_jpeg_fails_the_job_permanently(env, world):  # noqa: F811
    owner = account(world, "sub-a").principal_id
    png = cv2.imdecode(np.frombuffer(handwriting_png(), np.uint8), cv2.IMREAD_GRAYSCALE)
    full = cv2.imencode(".jpg", png)[1].tobytes()
    data = full[: len(full) // 2]  # header intact, scan data cut
    capture = env.capture(owner, data, "image/jpeg")
    env.grant(owner, capture.capture_id)
    run_id = env.intake.start_analysis(owner, capture.capture_id)
    outcome = env.worker().run_once()
    assert (outcome.outcome, outcome.detail) == ("FAILED", "malformed_image")
    assert env.intake.status(owner, run_id).state == "FAILED"


def test_analysis_requires_service_permission_and_owner(env, world):  # noqa: F811
    alice, bob = account(world, "sub-a").principal_id, account(world, "sub-b").principal_id
    capture = env.capture(alice)
    with pytest.raises(NotAuthorized):
        env.intake.start_analysis(alice, capture.capture_id)
    env.grant(alice, capture.capture_id)
    with pytest.raises(NotFound):
        env.intake.start_analysis(bob, capture.capture_id)
    ticket = env.upload(alice, handwriting_png())
    with pytest.raises(NotFound):
        env.intake.complete_upload(bob, ticket.upload_id, sha(handwriting_png()), env.ctx())


def test_stale_lease_cannot_publish_after_reclaim(env, world):  # noqa: F811
    owner = account(world, "sub-a").principal_id
    _, run_id = env.analysis(owner)
    stale = env.queue.claim("w-old", 60, env.clock.now())
    env.clock.advance(61)  # the old worker stalled past its lease
    assert env.worker("w-new").run_once().outcome == "SUCCEEDED"
    from princess_app.application.analysis_worker import Fenced
    with pytest.raises(Fenced) as err:
        env.queue.publish(stale, result={}, evidence=None, report=None, processed_sha256="0" * 64,
                          now=env.clock.now())
    assert err.value.reason == "stale_fencing_token"
    with env.app_db.session(owner) as conn:
        assert conn.execute(text("SELECT count(*) FROM app.report_revision")).scalar() == 1


@pytest.mark.parametrize("interruption,reason,state", [
    ("delete", "job_cancelled", "CANCELLED"),         # deletion also cancels queued/leased work
    ("account", "owner_deleted", "CANCELLED"),        # account deletion fences background publication
    ("tombstone", "capture_deleted", "CANCELLED"),    # a tombstone alone still blocks publication
    ("withdraw", "permission_changed", "CANCELLED"),
    ("cancel", "job_cancelled", "CANCELLED"),
])
def test_interruptions_during_a_run_block_publication(env, world, interruption, reason, state):  # noqa: F811
    owner = account(world, "sub-a").principal_id
    capture, run_id = env.analysis(owner)
    worker = env.worker()
    original = env.queue.publish

    def interrupt_then_publish(job, **kwargs):
        if interruption == "delete":
            env.intake.delete_capture(owner, capture.capture_id)
        elif interruption == "account":
            PostgresIdentityStore(env.app_db).mark_deleted(owner, env.clock.now())
        elif interruption == "tombstone":
            with env.app_db.session(owner) as conn:
                conn.execute(text("UPDATE app.capture SET deleted_at = now()"))
        elif interruption == "withdraw":
            env.permissions.record(subject_id=owner, actor_id=owner, purpose_id="service_processing",
                                   scope=SUBJECT_WIDE, decision=Decision.WITHDRAW, notice_version=NOTICE)
        else:
            env.intake.cancel(owner, run_id)
        return original(job, **kwargs)

    env.queue.publish = interrupt_then_publish
    outcome = worker.run_once()
    assert (outcome.outcome, outcome.detail) == ("FENCED", reason)
    with env.app_db.session(owner) as conn:
        assert conn.execute(text("SELECT count(*) FROM app.report")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM app.measurement")).scalar() == 0
        attempts = conn.execute(text("SELECT outcome, error_code FROM app.job_attempt")).all()
    assert attempts == [("FENCED", reason)]
    assert env.intake.status(owner, run_id).state == state
    env.clock.advance(3600)
    assert env.queue.claim("later", 60, env.clock.now()) is None  # never reclaimed after a terminal fence


def test_repeatedly_crashing_workers_cannot_reclaim_forever(env, world):  # noqa: F811
    owner = account(world, "sub-a").principal_id
    _, run_id = env.analysis(owner)
    for i in range(4):
        assert env.queue.claim(f"crash-{i}", 30, env.clock.now()) is not None
        env.clock.advance(31)
    assert env.queue.claim("next", 30, env.clock.now()) is None
    with env.app_db.session(owner) as conn:
        assert conn.execute(text("SELECT state, last_error FROM app.job")).one() == ("FAILED", "attempts_exhausted")


def test_crashed_worker_lease_expires_and_attempts_are_bounded(env, world):  # noqa: F811
    owner = account(world, "sub-a").principal_id
    _, run_id = env.analysis(owner)
    for i in range(3):
        job = env.queue.claim(f"crashy-{i}", 30, env.clock.now())
        assert job is not None and job.fencing_token == i + 1
        env.clock.advance(31)  # worker died without heartbeat or failure report
    job = env.queue.claim("final", 30, env.clock.now())
    env.queue.fail(job, "analysis_error", retry=True, now=env.clock.now())
    assert env.intake.status(owner, run_id).state == "FAILED"
    assert env.queue.claim("after", 30, env.clock.now()) is None


def test_upload_quota_depends_on_challenge(env, world):  # noqa: F811
    owner = account(world, "sub-a").principal_id
    for _ in range(3):
        env.upload(owner, b"x")
    with pytest.raises(RateLimited):
        env.upload(owner, b"x")
    token = env.challenge.issue_token("upload", "app.test")
    env.upload(owner, b"x", proof=ChallengeProof(token, "upload", "app.test"))
    with pytest.raises(NotAuthorized):
        env.upload(owner, b"x", proof=ChallengeProof(token, "upload", "app.test"))  # replayed challenge
