"""Shared integrity helpers for the graphology interpretation database."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

EXPECTED_BASELINE_COMMIT = "f96aa6b54cfaf91f0a8243e7c7e266baa053eedc"
EXPECTED_IMPORT_MANIFEST_BLOB = "00c2fe4d0ba6ca4d95fb5fd9441de066937b2f2c"

DOMAINS = [
    "01-context","02-global","03-space","04-size","05-direction","06-connection",
    "07-form","08-stroke","09-movement","10-detail","11-signature","12-hierarchy",
    "13-interpretation","14-reference","15-pair","16-history",
]

def load(path: Path):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError(f"Duplicate JSON key in {path}: {key}")
            out[key] = value
        return out
    def constant(value):
        raise ValueError(f"Non-finite JSON constant in {path}: {value}")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=constant)

def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def verify_research_baseline(repo: Path) -> list[str]:
    errors = []
    lock = load(repo / "schema/graphology_interpretation/v1/traceability/research_baseline_lock.json")
    tree_lock = load(repo / lock["snapshot_tree_lock_path"])
    manifest = load(repo / lock["import_manifest_path"])

    if lock["research_baseline_commit"] != EXPECTED_BASELINE_COMMIT:
        errors.append("research baseline commit differs from pinned immutable baseline")
    if tree_lock["research_baseline_commit"] != EXPECTED_BASELINE_COMMIT:
        errors.append("snapshot tree lock baseline differs from pinned immutable baseline")
    if lock["import_manifest_git_blob_sha"] != EXPECTED_IMPORT_MANIFEST_BLOB:
        errors.append("baseline lock import-manifest blob differs from pinned value")

    snapshot_root = repo / lock["research_snapshot"]
    locked = {x["path"]: x for x in tree_lock["files"]}
    actual_paths = {
        p.relative_to(snapshot_root).as_posix()
        for p in snapshot_root.rglob("*")
        if p.is_file()
    }
    if actual_paths != set(locked):
        missing = sorted(set(locked) - actual_paths)
        extra = sorted(actual_paths - set(locked))
        if missing:
            errors.append("frozen research files missing: " + ", ".join(missing))
        if extra:
            errors.append("unexpected files added to frozen research snapshot: " + ", ".join(extra))
    if tree_lock.get("file_count") != len(locked) or len(locked) != 28:
        errors.append("snapshot tree lock file count invalid")
    for rel, record in locked.items():
        path = snapshot_root / rel
        if not path.exists():
            continue
        data = path.read_bytes()
        if len(data) != record["size"]:
            errors.append(f"frozen research size mismatch: {rel}")
        if git_blob_sha(data) != record["git_blob_sha"]:
            errors.append(f"frozen research Git blob mismatch: {rel}")

    raw = (repo / lock["import_manifest_path"]).read_bytes()
    if git_blob_sha(raw) != EXPECTED_IMPORT_MANIFEST_BLOB:
        errors.append("research import manifest bytes differ from frozen baseline")
    if manifest.get("source_archive_sha256") != lock["source_archive_sha256"]:
        errors.append("research source archive hash differs from baseline lock")
    if manifest.get("source_blueprint_sha256") != lock["source_blueprint_sha256"]:
        errors.append("research blueprint hash differs from baseline lock")

    # Preserve the original import package SHA-256 guarantees as a second independent check.
    for record in manifest.get("files", []):
        path = snapshot_root / record["path"]
        if not path.exists():
            errors.append(f"frozen research import file missing: {record['path']}")
            continue
        if sha256(path.read_bytes()) != record["sha256"]:
            errors.append(f"frozen research SHA-256 mismatch: {record['path']}")
    return errors

def concat(root: Path, relative: str):
    return [item for name in DOMAINS for item in load(root / relative / f"{name}.json")]
