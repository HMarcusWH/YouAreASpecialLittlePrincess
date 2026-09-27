"""T24 report feedback: owner-bound, redacted, idempotent, erasable, support-only."""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from princess_app.adapters.postgres.feedback import PostgresFeedbackRepository
from princess_app.adapters.postgres.stores import Database, PostgresReportStore, make_engine
from princess_app.application.feedback import FeedbackService
from princess_app.domain.feedback import MAX_PER_REPORT, FeedbackSubmission
from princess_app.ports.base import Conflict, InvalidInput, NotFound, RateLimited
from test_intake import Env, erasure
from test_persistence import account, world  # noqa: F401 - fixture re-export

SUPPORT_ROLE, SUPPORT_PASSWORD = "princess_support_test", "test-only-support-role"


class Shop:
    def __init__(self, app_db, worker_db, world):  # noqa: F811
        self.env = env = Env(app_db, worker_db)
        self.owner = account(world, "sub-f").principal_id
        self.capture, run_id = env.analysis(self.owner)
        assert env.worker().run_once().outcome == "SUCCEEDED"
        self.report_id = env.intake.status(self.owner, run_id).report_id
        self.repo = PostgresFeedbackRepository(app_db)
        self.service = FeedbackService(reports=lambda owner: PostgresReportStore(app_db, owner), repo=self.repo,
                                       clock=env.clock)
        self.fact = PostgresReportStore(app_db, self.owner).latest(self.report_id)[1].data["facts"][0]["fact_id"]

    def submit(self, owner=None, request_id="req_00000001", comment="The slant looks off", **kw):
        return self.service.submit(owner or self.owner, FeedbackSubmission(
            report_id=kw.get("report_id", self.report_id), category=kw.get("category", "MEASUREMENT_LOOKS_WRONG"),
            target_kind=kw.get("kind", "FACT"), target_ref=kw.get("ref", self.fact), comment=comment,
            request_id=request_id))


@pytest.fixture
def fb(app_db, worker_db, world):  # noqa: F811
    return Shop(app_db, worker_db, world)


def test_feedback_is_owner_bound_redacted_and_idempotent(fb, world):  # noqa: F811
    record = fb.submit(comment="wrong! reach me at me@example.org")
    assert record.comment == "wrong! reach me at [email removed]" and record.revision == 1
    assert fb.submit(comment="wrong! reach me at me@example.org") == record  # a retry converges
    with pytest.raises(Conflict):
        fb.submit(comment="something else")  # same request ID, different feedback
    stranger = account(world, "sub-x").principal_id
    with pytest.raises(NotFound):
        fb.submit(owner=stranger, request_id="req_00000002")  # another owner's report does not exist for them
    with pytest.raises(InvalidInput):
        fb.submit(request_id="req_00000003", ref="fact.INVENTED")
    with pytest.raises(InvalidInput):
        fb.submit(request_id="req_00000004", comment='{"facts": [{"value": 1}]}')
    with fb.env.app_db.session(stranger) as conn:
        assert conn.execute(text("SELECT count(*) FROM app.report_feedback")).scalar() == 0


def test_feedback_is_capped_withdrawable_and_expires(fb):
    for i in range(MAX_PER_REPORT):
        fb.submit(request_id=f"req_{i:08d}")
    with pytest.raises(RateLimited):
        fb.submit(request_id="req_overflow")
    fb.service.withdraw(fb.owner, fb.submit(request_id="req_00000000").feedback_id)
    with pytest.raises(NotFound):
        fb.service.withdraw(fb.owner, "fb_missing")
    assert fb.repo.expire(fb.env.clock.now() + timedelta(days=181)) == MAX_PER_REPORT - 1
    with fb.env.app_db.session(fb.owner) as conn:
        assert conn.execute(text("SELECT count(*) FROM app.report_feedback")).scalar() == 0


def test_feedback_goes_with_its_report_when_the_capture_is_erased(fb):
    fb.submit()
    fb.env.intake.delete_capture(fb.owner, fb.capture.capture_id)
    assert "ERASED" in {o.action for o in erasure(fb.env).run_once()}
    with fb.env.app_db.session(fb.owner) as conn:
        assert conn.execute(text("SELECT count(*) FROM app.report_feedback")).scalar() == 0


def test_support_reads_feedback_columns_only(fb, admin_engine, database_url):
    fb.submit()
    with admin_engine.begin() as conn:
        conn.execute(text(f"DROP ROLE IF EXISTS {SUPPORT_ROLE}"))
        conn.execute(text(f"CREATE ROLE {SUPPORT_ROLE} LOGIN PASSWORD '{SUPPORT_PASSWORD}' NOSUPERUSER "
                          "NOBYPASSRLS IN ROLE princess_support"))
    parts = make_engine(database_url).url.set(username=SUPPORT_ROLE, password=SUPPORT_PASSWORD)
    support = Database(make_engine(parts.render_as_string(hide_password=False)))
    with support.session() as conn:
        row = conn.execute(text("SELECT category, target_kind, comment FROM app.report_feedback")).one()
        assert row == ("MEASUREMENT_LOOKS_WRONG", "FACT", "The slant looks off")
    for forbidden in ("SELECT owner_id FROM app.report_feedback", "SELECT count(*) FROM app.report",
                      "SELECT count(*) FROM app.measurement", "SELECT count(*) FROM app.asset",
                      "DELETE FROM app.report_feedback"):
        with pytest.raises(ProgrammingError):
            with support.session() as conn:
                conn.execute(text(forbidden))
