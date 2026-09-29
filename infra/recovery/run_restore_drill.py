#!/usr/bin/env python3
"""Run the destructive, synthetic T24 PostgreSQL backup/restore rehearsal."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from receipt import write as write_receipt

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "infra" / "recovery" / "compose.restore.yaml"
IMAGE = re.compile(r"^princess-backend:[0-9a-f]{40}$")


class DrillFailure(RuntimeError):
    pass


def checked_settings() -> tuple[dict[str, str], Path]:
    if os.environ.get("PRINCESS_RECOVERY_ALLOW_RESET") != "1":
        raise DrillFailure("PRINCESS_RECOVERY_ALLOW_RESET=1 is required")
    image = os.environ.get("PRINCESS_BACKEND_IMAGE", "")
    if not IMAGE.fullmatch(image):
        raise DrillFailure("PRINCESS_BACKEND_IMAGE must be the exact PR/main sha-tagged backend image")
    raw = os.environ.get("PRINCESS_RECOVERY_WORKDIR", "")
    if not raw:
        raise DrillFailure("PRINCESS_RECOVERY_WORKDIR is required")
    workdir = Path(raw).expanduser().resolve()
    if workdir == Path("/") or not workdir.name.startswith("princess-recovery"):
        raise DrillFailure("recovery workdir must be a dedicated princess-recovery* directory")
    workdir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PRINCESS_RECOVERY_WORKDIR"] = str(workdir)
    return env, workdir


def command(*args: str) -> list[str]:
    return ["docker", "compose", "-f", str(COMPOSE), *args]


def run(env: dict[str, str], *args: str, capture: bool = False, ok: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command(*args), cwd=ROOT, env=env, text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=False,
    )
    if ok and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise DrillFailure(detail[-1] if detail else f"command_failed:{args[0]}")
    if not ok and result.returncode == 0:
        raise DrillFailure("expected_failure_did_not_fail")
    return result


def run_json(env: dict[str, str], service: str, *argv: str) -> dict:
    result = run(env, "run", "--rm", service, *argv, capture=True)
    for line in reversed((result.stdout or "").splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise DrillFailure(f"missing_json_output:{service}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def revision(env: dict[str, str]) -> str:
    result = run(
        env, "exec", "-T", "db", "psql", "-U", "princess_admin", "-d", "princess_test",
        "-Atqc", "SELECT version_num FROM alembic_version", capture=True,
    )
    value = (result.stdout or "").strip()
    if not value or "\n" in value:
        raise DrillFailure("alembic_revision_unreadable")
    return value


def validate_backup(env: dict[str, str], path: Path, expected_sha: str) -> None:
    if not path.is_file() or path.stat().st_size <= 0 or sha256(path) != expected_sha:
        raise DrillFailure("backup_integrity_failed")
    run(env, "exec", "-T", "db", "pg_restore", "--list", "/recovery/backup.dump", capture=True)


def corrupt_backup_is_rejected(env: dict[str, str], backup: Path, expected_sha: str) -> bool:
    corrupt = backup.with_name("backup.corrupt.dump")
    shutil.copyfile(backup, corrupt)
    with corrupt.open("r+b") as handle:
        handle.seek(0)
        handle.write(b"BROKEN")
    hash_rejected = sha256(corrupt) != expected_sha
    result = run(env, "exec", "-T", "db", "pg_restore", "--list", "/recovery/backup.corrupt.dump",
                 capture=True, ok=False)
    return hash_rejected and result.returncode != 0


def main() -> int:
    env, workdir = checked_settings()
    started = time.monotonic()
    backup = workdir / "backup.dump"
    state = "/recovery/state.json"
    try:
        run(env, "up", "-d", "--wait", "db")
        run(env, "run", "--rm", "migrations")
        run(env, "run", "--rm", "role-bootstrap")
        run_json(env, "api-tool", "/recovery-tools/fixture.py", "seed", state)
        before = revision(env)

        run(env, "exec", "-T", "db", "pg_dump", "-U", "princess_admin", "--format=custom",
            "--no-owner", "--file=/recovery/backup.dump", "princess_test")
        backup_sha = sha256(backup)
        backup_size = backup.stat().st_size
        validate_backup(env, backup, backup_sha)
        corrupt_rejected = corrupt_backup_is_rejected(env, backup, backup_sha)

        run_json(env, "api-tool", "/recovery-tools/fixture.py", "mutate", state)
        run_json(env, "worker-tool", "/recovery-tools/fixture.py", "erase", state)
        current = run_json(env, "api-tool", "/recovery-tools/fixture.py", "assert-current", state)
        if current.get("object_erasure_verified") is not True:
            raise DrillFailure("object_erasure_not_verified_before_restore")

        restore_started = time.monotonic()
        run(env, "exec", "-T", "db", "psql", "-U", "princess_admin", "-d", "postgres",
            "-v", "ON_ERROR_STOP=1", "-c",
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = 'princess_test' AND pid <> pg_backend_pid();")
        run(env, "exec", "-T", "db", "dropdb", "-U", "princess_admin", "--if-exists", "princess_test")
        run(env, "exec", "-T", "db", "createdb", "-U", "princess_admin", "princess_test")
        run(env, "exec", "-T", "db", "pg_restore", "-U", "princess_admin", "--no-owner",
            "--exit-on-error", "-d", "princess_test", "/recovery/backup.dump")
        run(env, "run", "--rm", "role-bootstrap")
        restore_elapsed_ms = int((time.monotonic() - restore_started) * 1000)
        after = revision(env)
        if after != before:
            raise DrillFailure("alembic_revision_changed_across_restore")

        resurrected = run_json(env, "api-tool", "/recovery-tools/fixture.py", "assert-resurrected", state)
        first = run_json(env, "api-tool", "-m", "princess_api.ops", "replay-tombstones")
        run_json(env, "worker-tool", "/recovery-tools/fixture.py", "erase", state)
        reconciled = run_json(env, "api-tool", "/recovery-tools/fixture.py", "assert-reconciled", state)
        second = run_json(env, "api-tool", "-m", "princess_api.ops", "replay-tombstones")

        replay = {key: int(first[key]) for key in ("reapplied", "already", "unknown", "unreadable")}
        replay2 = {key: int(second[key]) for key in ("reapplied", "already", "unknown", "unreadable")}
        receipt = {
            "version": "recovery-receipt/1",
            "environment": "test",
            "synthetic_fixture": True,
            "production_claim": False,
            "database_backup_format": "postgres-custom",
            "backup_sha256": backup_sha,
            "backup_size_bytes": backup_size,
            "alembic_revision_before": before,
            "alembic_revision_after": after,
            "restore_elapsed_ms": restore_elapsed_ms,
            "recovery_elapsed_ms": int((time.monotonic() - started) * 1000),
            "resurrection_observed": {
                "capture": resurrected.get("capture") is True,
                "account": resurrected.get("account") is True,
                "permission": resurrected.get("permission") is True,
            },
            "tombstone_replay": replay,
            "second_replay": replay2,
            "object_erasure_verified": reconciled.get("object_erasure_verified") is True,
            "corrupt_backup_rejected": corrupt_rejected,
            "rpo_target": None,
            "rto_target": None,
            "result": "PASS",
        }
        write_receipt(workdir / "recovery-receipt.json", receipt)
        print(json.dumps(receipt, sort_keys=True))
        return 0
    finally:
        run(env, "down", "-v", "--remove-orphans", ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
