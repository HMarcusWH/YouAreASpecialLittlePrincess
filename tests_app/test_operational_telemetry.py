"""T24 operational snapshot -> TelemetryExporter mapping."""
from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from princess_api import ops
from princess_app.adapters.fakes import FakeTelemetryExporter
from princess_app.application.operational_telemetry import (
    ALERT_METRIC,
    CAPABILITY_METRIC,
    COUNT_METRIC,
    MAX_ATTEMPTS_METRIC,
    OLDEST_AGE_METRIC,
    operational_records,
)
from princess_app.application.operations import (
    CAPABILITY_NAMES,
    VALID_KEYS,
    OperationalAlert,
    OperationalObservation,
    build_snapshot,
)
from princess_app.application.telemetry import BufferedTelemetry
from princess_app.ports.base import Environment, InvalidInput, ProviderMode, Unsupported
from princess_app.ports.telemetry import REDACTED
from test_persistence import T0


def snapshot():
    return build_snapshot(
        environment=Environment.TEST,
        observed_at=T0,
        schema_revision="0011_operational_snapshot",
        capabilities={
            "premium_generation": False,
            "commerce": False,
            "uploads": True,
            "sharing": True,
            "notifications": True,
        },
        database_observations=(
            OperationalObservation("jobs", "analysis", "queued", 2, 12, 1),
        ),
        tombstone_entries=0,
        tombstone_unreadable=0,
        tombstone_store_present=True,
    )


def test_mapping_emits_complete_zero_filled_operational_gauge_universe():
    records = operational_records(snapshot())
    counts = [record for record in records if record.name == COUNT_METRIC]
    assert len(counts) == len(VALID_KEYS) == 26

    by_operation = {record.attributes["operation"]: record.value for record in counts}
    assert by_operation["jobs.analysis.queued"] == 2.0
    assert by_operation["jobs.premium.queued"] == 0.0
    assert by_operation["notifications.mail.failed"] == 0.0
    assert by_operation["privacy.tombstone.missing"] == 0.0

    ages = [record for record in records if record.name == OLDEST_AGE_METRIC]
    attempts = [record for record in records if record.name == MAX_ATTEMPTS_METRIC]
    assert [(r.attributes["operation"], r.value) for r in ages] == [("jobs.analysis.queued", 12.0)]
    assert [(r.attributes["operation"], r.value) for r in attempts] == [("jobs.analysis.queued", 1.0)]

    capabilities = [record for record in records if record.name == CAPABILITY_METRIC]
    assert len(capabilities) == len(CAPABILITY_NAMES) == 5
    states = {r.attributes["operation"]: (r.attributes["outcome"], r.value) for r in capabilities}
    assert states["uploads"] == ("enabled", 1.0)
    assert states["commerce"] == ("disabled", 0.0)


def test_mapping_uses_only_existing_bounded_telemetry_attributes_and_no_redactions():
    records = operational_records(snapshot())
    for record in records:
        assert set(record.attributes) <= {"environment", "operation", "outcome", "error_code"}
        assert REDACTED not in record.attributes.values()


def test_reviewed_alert_maps_to_fixed_dimension_and_invalid_codes_fail_closed():
    alert = OperationalAlert(
        "test.analysis_queue_stale", "jobs", "analysis", "queued",
        "oldest_age_s", 120, 60,
    )
    [record] = [r for r in operational_records(snapshot(), (alert,)) if r.name == ALERT_METRIC]
    assert record.value == 1.0
    assert record.attributes == {
        "environment": "test",
        "operation": "jobs.analysis.queued",
        "outcome": "fired",
        "error_code": "test.analysis_queue_stale",
    }

    bad = OperationalAlert(
        "Bearer secret value", "jobs", "analysis", "queued",
        "oldest_age_s", 120, 60,
    )
    with pytest.raises(InvalidInput, match="operational_telemetry_code"):
        operational_records(snapshot(), (bad,))


def test_mapping_keeps_existing_buffer_failure_isolation():
    exporter = FakeTelemetryExporter()
    buffered = BufferedTelemetry(exporter, capacity=256, batch_size=256)
    records = operational_records(snapshot())
    for record in records:
        buffered.record(record.kind, record.name, record.attributes, record.value)

    exporter.outage = True
    assert buffered.flush() == 0
    assert buffered.export_failures == 1
    assert buffered.buffered == len(records)

    exporter.outage = False
    assert buffered.flush() == len(records)
    assert buffered.buffered == 0


def _ops_env(monkeypatch, app_url: str, storage_dir: str) -> None:
    for key, value in {
        "PRINCESS_ENV": "test",
        "PRINCESS_COMPONENT": "api",
        "PRINCESS_DATABASE_URL": app_url,
        "PRINCESS_SESSION_SECRET": "test-ops-session-0123456789",
        "PRINCESS_IDENTITY_AUDIENCE": "princess-test",
        "PRINCESS_STORAGE_SIGNING_KEY": "test-ops-storage-0123456789",
        "PRINCESS_LOCAL_STORAGE_DIR": storage_dir,
    }.items():
        monkeypatch.setenv(key, value)


def test_emit_telemetry_operator_uses_fake_exporter_and_full_snapshot(
        monkeypatch, capsys, app_url, tmp_path):
    _ops_env(monkeypatch, app_url, str(tmp_path))
    assert ops.main(["emit-telemetry"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["result"] == "PASS"
    assert result["alert_count"] == 0
    assert result["dropped"] == 0
    assert result["export_failures"] == 0
    assert result["metric_counts"][COUNT_METRIC] == len(VALID_KEYS)
    assert result["metric_counts"][CAPABILITY_METRIC] == len(CAPABILITY_NAMES)
    assert ALERT_METRIC not in result["metric_counts"]


def test_emit_telemetry_refuses_non_fake_provider_mode():
    config = SimpleNamespace(
        environment=Environment.PRODUCTION,
        provider_mode=lambda _: ProviderMode.LIVE,
    )
    with pytest.raises(Unsupported, match="telemetry_adapter_not_configured"):
        ops._fake_telemetry_exporter(config)


def test_empty_dimensions_really_change_from_nonzero_to_zero_between_snapshots():
    first = snapshot()
    later = build_snapshot(
        environment=Environment.TEST,
        observed_at=T0 + timedelta(seconds=30),
        schema_revision="0011_operational_snapshot",
        capabilities=first.capabilities,
        database_observations=(),
        tombstone_entries=0,
        tombstone_unreadable=0,
        tombstone_store_present=True,
    )
    def count_value(document, operation):
        return next(
            record.value for record in operational_records(document)
            if record.name == COUNT_METRIC and record.attributes["operation"] == operation
        )
    assert count_value(first, "jobs.analysis.queued") == 2.0
    assert count_value(later, "jobs.analysis.queued") == 0.0
