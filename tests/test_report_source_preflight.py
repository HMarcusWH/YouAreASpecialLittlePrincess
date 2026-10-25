"""Synthetic hostile R1 ZIP preflight: no original approved content is shipped."""
from __future__ import annotations

import copy
import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest

import check_report_source_bundle as preflight


def _source_files() -> dict[str, bytes]:
    baseline = json.loads(preflight.LOCAL_BASELINE.read_text(encoding="utf-8"))
    proposed = copy.deepcopy(baseline)
    proposed["version"] = "presentation/2"
    proposed["policy_version"] = "highlight-policy/2"

    def versioned(value: str) -> str:
        assert value.startswith("content.highlight.v1.")
        return value.replace("content.highlight.v1.", "content.highlight.v2.", 1)

    proposed["content"] = {versioned(k): v for k, v in baseline["content"].items()}
    proposed["fallback_content_id"] = versioned(baseline["fallback_content_id"])
    for row in proposed["candidates"]:
        row["content_id"] = versioned(row["content_id"])

    files = {p: b"{}" for p in preflight.REQUIRED}
    files[preflight.CONTENT[0]] = json.dumps(proposed, ensure_ascii=False).encode("utf-8")
    for path in preflight.SCHEMAS:
        name = Path(path).name
        files[path] = json.dumps({
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": name,
        }).encode("utf-8")

    # Test-only manifest with 127 operations and exact required R1 targets.
    # This tests archive reconciliation, NOT authorship approval or real specs.
    operations = [
        {"path": name.removeprefix("proposed/"),
         "action": "MODIFY" if name.endswith("/common.schema.json") else "CREATE"}
        for name in (*preflight.CONTENT, *preflight.SCHEMAS)
    ]
    operations += [
        {"path": f"synthetic/unrelated-path-{i:03d}.md", "action": "MODIFY"}
        for i in range(127 - len(operations))
    ]
    files["FILE_MANIFEST.json"] = json.dumps({
        "spec_version": preflight.VERSION,
        "baseline": "0c50c577231ae633c6910114f1dad731ffc7a978",
        "operations": operations,
    }).encode("utf-8")
    return files


def _zip(path: Path, files: dict[str, bytes], *, wrapper: str = "") -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, value in files.items():
            zf.writestr(wrapper + name, value)


def test_valid_synthetic_handover_is_only_a_structural_receipt(tmp_path):
    archive = tmp_path / "source.zip"
    originals = _source_files()
    _zip(archive, originals)
    before = archive.read_bytes()
    digest = hashlib.sha256(before).hexdigest()
    outcome = preflight.inspect_bundle(archive, expected_sha256=digest)
    assert outcome["status"] == "STRUCTURAL_PREFLIGHT_ONLY_NOT_APPROVED"
    assert outcome["review_required"] is True
    assert outcome["archive_sha256_pinned"] is True
    assert outcome["archive_sha256"] == digest
    assert outcome["candidate_count"] == 54 and outcome["feature_label_count"] == 64
    assert outcome["required_members_checked"] == len(preflight.REQUIRED)
    assert outcome["member_sha256"][preflight.CONTENT[0]] == hashlib.sha256(
        originals[preflight.CONTENT[0]]).hexdigest()
    assert archive.read_bytes() == before
    assert {p.name for p in tmp_path.iterdir()} == {"source.zip"}


def test_one_uniform_wrapper_is_accepted_without_extraction(tmp_path):
    archive = tmp_path / "wrapped.zip"
    _zip(archive, _source_files(), wrapper="handover/")
    receipt = preflight.inspect_bundle(archive)
    assert receipt["archive_sha256_pinned"] is False
    assert receipt["review_required"] is True


def test_mutated_candidate_rules_or_copy_fail_closed(tmp_path):
    raw = _source_files()
    key = preflight.CONTENT[0]
    for mutation in ("threshold", "candidate", "swedish_copy", "copy_id"):
        files = dict(raw)
        proposed = json.loads(files[key])
        if mutation == "threshold":
            proposed["candidates"][0]["clauses"][0]["max"] += 0.5
        elif mutation == "candidate":
            proposed["candidates"].pop()
        elif mutation == "swedish_copy":
            proposed["content"][next(iter(proposed["content"]))].pop("sv")
        else:
            row = proposed["candidates"][0]
            row["content_id"] = row["content_id"].replace(".v2.", ".v1.")
        files[key] = json.dumps(proposed).encode()
        archive = tmp_path / f"{mutation}.zip"
        _zip(archive, files)
        with pytest.raises(preflight.SourceBundleError):
            preflight.inspect_bundle(archive)


def test_unsafe_zip_paths_links_and_case_collisions_are_rejected(tmp_path):
    files = _source_files()
    for name in ("../escape", "/absolute/path", "bad\\backslash", "./dot"):
        archive = tmp_path / ("invalid-" + str(len(list(tmp_path.iterdir()))) + ".zip")
        _zip(archive, {**files, name: b"{}"})
        with pytest.raises(preflight.SourceBundleError, match="unsafe ZIP path"):
            preflight.inspect_bundle(archive)

    archive = tmp_path / "case-collision.zip"
    _zip(archive, {**files, preflight.CONTENT[0].upper(): b"{}"})
    with pytest.raises(preflight.SourceBundleError, match="colliding"):
        preflight.inspect_bundle(archive)

    archive = tmp_path / "symlink.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, value in files.items():
            zf.writestr(name, value)
        link = zipfile.ZipInfo("unrelated/linked.txt")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(link, "../../outside")
    with pytest.raises(preflight.SourceBundleError, match="symlink"):
        preflight.inspect_bundle(archive)


def test_missing_or_oversized_or_corrupt_sources_fail_closed(tmp_path):
    files = _source_files()
    missing = dict(files)
    missing.pop(preflight.CONTENT[0])
    archive = tmp_path / "missing.zip"
    _zip(archive, missing)
    with pytest.raises(preflight.SourceBundleError, match="missing R1 source"):
        preflight.inspect_bundle(archive)

    oversized = dict(files)
    oversized["unrelated/huge.bin"] = b"x" * (preflight.MAX_MEMBER_BYTES + 1)
    archive = tmp_path / "oversized.zip"
    _zip(archive, oversized)
    with pytest.raises(preflight.SourceBundleError, match="oversized"):
        preflight.inspect_bundle(archive)

    archive = tmp_path / "corrupt.zip"
    archive.write_bytes(b"not a ZIP")
    with pytest.raises(preflight.SourceBundleError, match="invalid/corrupt"):
        preflight.inspect_bundle(archive)


def test_digest_json_and_manifest_tampering_cannot_pass(tmp_path):
    files = _source_files()
    archive = tmp_path / "valid.zip"
    _zip(archive, files)
    with pytest.raises(preflight.SourceBundleError, match="SHA256"):
        preflight.inspect_bundle(archive, expected_sha256="0" * 64)
    with pytest.raises(preflight.SourceBundleError, match="SHA256"):
        preflight.inspect_bundle(archive, expected_sha256="unknown")

    json_duplicate = dict(files)
    json_duplicate[preflight.CONTENT[1]] = b'{"value":1,"value":2}'
    archive = tmp_path / "duplicate-json.zip"
    _zip(archive, json_duplicate)
    with pytest.raises(preflight.SourceBundleError, match="duplicate JSON key"):
        preflight.inspect_bundle(archive)

    manifest_change = dict(files)
    data = json.loads(files["FILE_MANIFEST.json"])
    data["operations"][0]["action"] = "MODIFY"
    manifest_change["FILE_MANIFEST.json"] = json.dumps(data).encode()
    archive = tmp_path / "changed-manifest.zip"
    _zip(archive, manifest_change)
    with pytest.raises(preflight.SourceBundleError, match="manifest operation"):
        preflight.inspect_bundle(archive)


def test_symlink_input_is_rejected(tmp_path):
    archive = tmp_path / "actual.zip"
    _zip(archive, _source_files())
    link = tmp_path / "linked.zip"
    try:
        link.symlink_to(archive)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(preflight.SourceBundleError, match="not a symlink"):
        preflight.inspect_bundle(link)


def test_verified_source_staging_is_private_unapproved_and_outside_repo(tmp_path):
    from stage_report_source_bundle import RECEIPT, stage_archive

    files = _source_files()
    files["unapproved/extra.py"] = b"raise RuntimeError('must never stage or run')"
    archive = tmp_path / "original-synthetic.zip"
    _zip(archive, files)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    destination = tmp_path / "source-review"
    receipt = stage_archive(archive, destination, expected_sha256=digest)
    assert receipt["status"] == "STAGED_UNREVIEWED_NOT_APPROVED"
    assert receipt["archive_sha256"] == digest
    assert receipt["required_members"] == len(preflight.REQUIRED)
    assert (destination / RECEIPT).is_file()
    assert {path.relative_to(destination).as_posix() for path in destination.rglob("*")
            if path.is_file()} == {*preflight.REQUIRED, RECEIPT}
    assert not (destination / "unapproved/extra.py").exists()
    for name in preflight.REQUIRED:
        staged = destination / name
        assert staged.read_bytes() == files[name]
        assert staged.stat().st_mode & 0o077 == 0  # no group/other read/write
    marker = json.loads((destination / RECEIPT).read_text(encoding="utf-8"))
    assert marker["member_sha256"] == receipt["member_sha256"]
    assert "NOT_APPROVED" in marker["status"]
    assert archive.is_file()

    # Never silently replace staged source with another archive.
    with pytest.raises(preflight.SourceBundleError, match="already exists"):
        stage_archive(archive, destination, expected_sha256=digest)


def test_source_staging_does_not_trust_unpinned_or_drifted_archives(tmp_path):
    from stage_report_source_bundle import stage_archive

    archive = tmp_path / "original.zip"
    _zip(archive, _source_files())
    destination = tmp_path / "unapproved"
    for pin in ("", "X" * 64, "0" * 64):
        with pytest.raises(preflight.SourceBundleError):
            stage_archive(archive, destination, expected_sha256=pin)
        assert not destination.exists()

    corrupted = tmp_path / "corrupt.zip"
    corrupted.write_bytes(b"not a zip")
    with pytest.raises(preflight.SourceBundleError):
        stage_archive(corrupted, destination, expected_sha256=hashlib.sha256(
            corrupted.read_bytes()).hexdigest())
    assert not destination.exists()

    # No reviewed content may be written directly into the checkout.
    with pytest.raises(preflight.SourceBundleError, match="outside the repository"):
        stage_archive(archive, preflight.ROOT / "unapproved-source-staging",
                      expected_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
    assert not (preflight.ROOT / "unapproved-source-staging").exists()
