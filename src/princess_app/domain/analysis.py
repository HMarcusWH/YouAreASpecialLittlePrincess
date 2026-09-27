"""AnalysisReference construction: the version pins every report and evidence
bundle carries."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from princess_contracts import generated as g
from princess_contracts import ValidatedDocument, ValidationResult, compile_document

QUALITY_POLICY_VERSION = "quality-policy/1"


def rfc3339(value: datetime) -> str:
    """UTC RFC3339 with ``Z``; microseconds only when present."""
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamps must be timezone-aware UTC")
    text = value.strftime("%Y-%m-%dT%H:%M:%S")
    if value.microsecond:
        text += f".{value.microsecond:06d}"
    return text + "Z"


def method_versions() -> dict[str, str]:
    return {m["method_id"]: m["method_version"] for m in g.METHOD_CAPABILITIES["methods"]}


def analysis_reference(*, analysis_id: str, run_id: str, owner_id: str, input_asset_id: str, input_sha256: str,
                       processed_sha256: str, created_at: datetime, engine_version: str,
                       analysis_config_sha256: str, quality_policy: str = QUALITY_POLICY_VERSION,
                       normalization: str | None = None, feature_set: str | None = None,
                       benchmark_release: str | None = None, template: str | None = None) -> dict[str, Any]:
    return {
        "contract_version": g.CONTRACT_VERSION,
        "analysis_id": analysis_id,
        "run_id": run_id,
        "owner_id": owner_id,
        "input_asset_id": input_asset_id,
        "input_sha256": input_sha256,
        "processed_sha256": processed_sha256,
        "created_at": rfc3339(created_at),
        "versions": {
            "feature_schema": g.FEATURE_SCHEMA_VERSION,
            "engine": engine_version,
            "method_manifest": g.METHOD_MANIFEST_SHA256,
            "analysis_config": analysis_config_sha256,
            "quality_policy": quality_policy,
            "normalization": normalization,
            "feature_set": feature_set,
            "benchmark_release": benchmark_release,
            "content_schema": g.CONTRACT_VERSION,
            "template": template,
        },
    }


def compile_analysis_reference(**kwargs: Any) -> ValidationResult[ValidatedDocument]:
    return compile_document("AnalysisReference", analysis_reference(**kwargs))
