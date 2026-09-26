"""T01 generation and external-authority drift are reproducible and reviewable."""
from __future__ import annotations

import json
from pathlib import Path

import generate_product_contracts as generator
import product_contract_common as common
from princess_contracts.generated import CONTRACT_BUNDLE_SHA256, CONTRACT_MANIFEST, METHOD_CAPABILITIES

ROOT = Path(__file__).resolve().parents[1]


def test_all_generated_artifacts_match_sources_byte_for_byte():
    for path, expected in generator.build().items():
        assert path.is_file(), path
        assert path.read_text(encoding="utf-8") == expected, path


def test_manifest_binds_every_source_schema_and_external_authority():
    entries = {item["schema_id"]: item for item in CONTRACT_MANIFEST["schemas"]}
    schemas = common.load_schemas()
    assert set(entries) == set(schemas)
    for name in schemas:
        path = ROOT / "contracts" / "product" / "v1" / entries[name]["path"]
        assert entries[name]["sha256"] == common.file_sha256(path)
    assert CONTRACT_MANIFEST["authorities"]["feature_database"]["sha256"] == common.file_sha256(common.FEATURE_SOURCE)
    assert CONTRACT_MANIFEST["authorities"]["premium_interpretation_database"]["sha256"] == common.file_sha256(common.T26_SOURCE)
    assert CONTRACT_MANIFEST["authorities"]["consent_purpose_registry"]["sha256"] == common.file_sha256(common.PURPOSE_SOURCE)
    copy = dict(CONTRACT_MANIFEST)
    digest = copy.pop("bundle_sha256")
    assert digest == CONTRACT_BUNDLE_SHA256 == common.sha256_bytes(common.canonical_bytes(copy))


def test_openapi_components_are_derived_from_same_root_types():
    data = json.loads((ROOT / "contracts" / "http" / "openapi-components.json").read_text())
    assert data["openapi"] == "3.1.0" and data["paths"] == {}
    components = data["components"]["schemas"]
    assert set(CONTRACT_MANIFEST["root_schemas"]) <= set(components)
    assert "Fact" in components and "CoordinateFrame" in components and "PremiumQuestion" in components
    text = json.dumps(data)
    assert "common.schema.json" not in text and "../" not in text


def test_python_and_typescript_exports_share_contract_names_and_wire_fields():
    py_text = (ROOT / "src" / "princess_contracts" / "generated.py").read_text()
    ts_text = (ROOT / "packages" / "contracts" / "src" / "generated.ts").read_text()
    for name in CONTRACT_MANIFEST["root_schemas"]:
        assert f"{name} = TypedDict" in py_text
        assert f"export interface {name}" in ts_text
    # Reserved words stay exact on the wire rather than being renamed per language.
    assert "'class':" in py_text and "readonly class:" in ts_text
    assert "GENERATED" in py_text and "GENERATED" in ts_text


def test_method_capability_resolver_ignores_legacy_free_compute_flag_and_resolves_closure():
    feature_authority = common.feature_authority()
    resolved = common.resolve_method_capabilities(feature_authority["features"])
    assert resolved == METHOD_CAPABILITIES
    sig = next(m for m in resolved["methods"] if m["method_id"] == "sigver_representation_v1")
    assert sig["requires_learned_inference"] is True and sig["free_eligible"] is False
    # The canonical feature database currently says free_compute=True for SIG_EMBEDDING;
    # T01 deliberately refuses to use that presentation flag as runtime authority.
    source = common.load_json(common.FEATURE_SOURCE)
    canonical = next(f for f in source["features"] if f["id"] == "SIG_EMBEDDING")
    assert canonical["free_compute"] is True
    assert resolved["features"]["SIG_EMBEDDING"]["free_available"] is False


def test_schema_source_subset_forbids_open_objects_unbounded_arrays_and_external_refs(tmp_path, monkeypatch):
    # Exercise the build-time policy itself rather than trusting comments about it.
    schema = {
        "$schema": common.DRAFT_2020_12, "$id":"bad.schema.json", "title":"Bad", "type":"object",
        "properties":{"x":{"type":"array","items":{"type":"string","maxLength":2}}},
        "required":["x"], "additionalProperties":False,
    }
    root = tmp_path / "schemas"
    root.mkdir()
    (root / "bad.schema.json").write_text(json.dumps(schema))
    monkeypatch.setattr(common, "SCHEMA_ROOT", root)
    try:
        common.load_schemas()
    except common.ContractSourceError as exc:
        assert "maxItems" in str(exc)
    else:
        raise AssertionError("unbounded array schema was accepted")



def test_t26_soft_field_authority_preserves_reviewed_bounds():
    authority = common.t26_authority()
    portrait = authority["soft_fields"]["SOFT_GRAPHIC_PORTRAIT"]
    assert portrait == {"max_characters": 500, "max_sentences": 3, "allow_new_numbers": False}
    selected = authority["question_packs"]["PREMIUM_INDIVIDUAL_GRAPHIC_V1"]["soft_field_ids"]
    assert set(selected) <= set(authority["soft_fields"])
