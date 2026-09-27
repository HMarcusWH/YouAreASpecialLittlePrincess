"""Adversarial cursor decoding, including the actual HTTP error boundary."""
from __future__ import annotations

import base64
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from princess_app.application.reports import decode_report_cursor, encode_report_cursor
from princess_app.ports.base import InvalidInput
from test_api import client as client, login


def cursor_for(payload: str) -> str:
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


INVALID_PAYLOADS = [
    pytest.param("2026-09-27T12:00:00\nreport_1", id="naive-timestamp"),
    pytest.param("2026-09-27\nreport_1", id="date-without-timezone"),
    pytest.param("0001-01-01T00:00:00+01:00\nreport_1", id="utc-underflow"),
    pytest.param("9999-12-31T23:59:59-01:00\nreport_1", id="utc-overflow"),
    pytest.param("2026-02-30T12:00:00Z\nreport_1", id="impossible-date"),
    pytest.param("not-a-timestamp\nreport_1", id="invalid-timestamp"),
    pytest.param("2026-09-27T12:00:00Z", id="missing-separator"),
    pytest.param("2026-09-27T12:00:00Z\n", id="empty-id"),
    pytest.param("2026-09-27T12:00:00Z\n" + "a" * 129, id="overlong-id"),
    pytest.param("2026-09-27T12:00:00Z\n_report", id="nonalphanumeric-start"),
    pytest.param("2026-09-27T12:00:00Z\nreport/1", id="slash-in-id"),
    pytest.param("2026-09-27T12:00:00Z\nreport 1", id="space-in-id"),
    pytest.param("2026-09-27T12:00:00Z\nreport_\u00e5", id="nonascii-id"),
    pytest.param("2026-09-27T12:00:00Z\nreport_1\x00", id="nul-in-id"),
    pytest.param("2026-09-27T12:00:00Z\nreport_1\nextra", id="extra-field"),
    pytest.param("2026-09-27T12:00:00Z\nreport_1\n", id="trailing-newline"),
]


@pytest.mark.parametrize("payload", INVALID_PAYLOADS)
def test_malformed_cursor_payloads_fail_closed(payload):
    with pytest.raises(InvalidInput, match="^invalid_report_cursor$"):
        decode_report_cursor(cursor_for(payload))


@pytest.mark.parametrize("cursor", [
    "", "a" * 513, "not-base64", "\u00e5", "_w",  # _w decodes to invalid UTF-8.
    cursor_for("2026-09-27T12:00:00Z\nreport_1") + "%",
])
def test_malformed_cursor_encodings_fail_closed(cursor):
    with pytest.raises(InvalidInput, match="^invalid_report_cursor$"):
        decode_report_cursor(cursor)


@pytest.mark.parametrize("report_id", ["a", "0", "report_1", "Report.v1:part-2", "a" * 128])
@pytest.mark.parametrize("offset", [-7, 0, 2])
def test_generated_cursors_round_trip_with_utc_and_canonical_ids(report_id, offset):
    created_at = datetime(2026, 9, 27, 12, 0, 0, 123456, tzinfo=timezone(timedelta(hours=offset)))
    decoded = decode_report_cursor(encode_report_cursor(created_at, report_id))
    assert decoded == (created_at.astimezone(timezone.utc), report_id)
    assert decoded[0].tzinfo is timezone.utc


def test_explicit_offset_payload_is_normalized_to_utc():
    assert decode_report_cursor(cursor_for("2026-09-27T14:00:00+02:00\nreport_1")) == (
        datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc), "report_1")


def test_absent_cursor_is_the_first_page():
    assert decode_report_cursor(None) is None


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="requires timezone switching")
@pytest.mark.parametrize("server_timezone", ["UTC0", "EST5EDT", "JST-9"])
def test_cursor_decoding_does_not_depend_on_server_timezone(server_timezone):
    previous = os.environ.get("TZ")
    try:
        os.environ["TZ"] = server_timezone
        time.tzset()
        with pytest.raises(InvalidInput, match="^invalid_report_cursor$"):
            decode_report_cursor(cursor_for("2026-09-27T12:00:00\nreport_1"))
        test_explicit_offset_payload_is_normalized_to_utc()
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


@pytest.mark.parametrize("payload", INVALID_PAYLOADS)
def test_invalid_report_cursors_return_typed_422(client, payload):
    api, _ = client
    response = api.get("/v1/reports", params={"cursor": cursor_for(payload)}, headers=login(api, "cursor-user"))
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_report_cursor"}
