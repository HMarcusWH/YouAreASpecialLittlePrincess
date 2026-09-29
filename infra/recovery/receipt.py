#!/usr/bin/env python3
"""Build and validate privacy-safe recovery-receipt/1 documents."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

VERSION = "recovery-receipt/1"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
TOP_LEVEL = {
    "version", "environment", "synthetic_fixture", "production_claim",
    "database_backup_format", "backup_sha256", "backup_size_bytes",
    "alembic_revision_before", "alembic_revision_after", "restore_elapsed_ms",
    "recovery_elapsed_ms", "resurrection_observed", "tombstone_replay",
    "second_replay", "object_erasure_verified", "corrupt_backup_rejected",
    "rpo_target", "rto_target", "result",
}
COUNT_KEYS = {"reapplied", "already", "unknown", "unreadable"}


def validate(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(data) != TOP_LEVEL:
        errors.append("receipt_top_level_shape")
    if data.get("version") != VERSION or data.get("environment") != "test":
        errors.append("receipt_authority")
    if data.get("synthetic_fixture") is not True or data.get("production_claim") is not False:
        errors.append("receipt_scope")
    if data.get("database_backup_format") != "postgres-custom":
        errors.append("receipt_backup_format")
    if not isinstance(data.get("backup_sha256"), str) or not SHA256.fullmatch(data["backup_sha256"]):
        errors.append("receipt_backup_sha256")
    for name in ("backup_size_bytes", "restore_elapsed_ms", "recovery_elapsed_ms"):
        minimum = 1 if name == "backup_size_bytes" else 0
        if not isinstance(data.get(name), int) or data[name] < minimum:
            errors.append(f"receipt_{name}")
    for name in ("alembic_revision_before", "alembic_revision_after"):
        if not isinstance(data.get(name), str) or not data[name] or len(data[name]) > 128:
            errors.append(f"receipt_{name}")
    if data.get("alembic_revision_before") != data.get("alembic_revision_after"):
        errors.append("receipt_alembic_revision_changed")
    if isinstance(data.get("restore_elapsed_ms"), int) and isinstance(data.get("recovery_elapsed_ms"), int):
        if data["recovery_elapsed_ms"] < data["restore_elapsed_ms"]:
            errors.append("receipt_elapsed_order")
    resurrection = data.get("resurrection_observed")
    if resurrection != {"capture": True, "account": True, "permission": True}:
        errors.append("receipt_resurrection")
    for field in ("tombstone_replay", "second_replay"):
        counts = data.get(field)
        if not isinstance(counts, dict) or set(counts) != COUNT_KEYS:
            errors.append(f"receipt_{field}_shape")
            continue
        if any(not isinstance(value, int) or value < 0 for value in counts.values()):
            errors.append(f"receipt_{field}_counts")
    if isinstance(data.get("tombstone_replay"), dict):
        if data["tombstone_replay"].get("reapplied", 0) < 3 or data["tombstone_replay"].get("unreadable") != 0:
            errors.append("receipt_first_replay")
    if isinstance(data.get("second_replay"), dict):
        if data["second_replay"].get("reapplied") != 0 or data["second_replay"].get("unreadable") != 0:
            errors.append("receipt_second_replay")
    for name in ("object_erasure_verified", "corrupt_backup_rejected"):
        if data.get(name) is not True:
            errors.append(f"receipt_{name}")
    if data.get("rpo_target") is not None or data.get("rto_target") is not None:
        errors.append("receipt_targets_are_owner_pending")
    if data.get("result") != "PASS":
        errors.append("receipt_result")
    return errors


def write(path: Path, data: dict[str, Any]) -> None:
    errors = validate(data)
    if errors:
        raise ValueError(",".join(errors))
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate",))
    parser.add_argument("path")
    args = parser.parse_args()
    data = json.loads(Path(args.path).read_text(encoding="utf-8"))
    errors = validate(data)
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"PASS {VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
