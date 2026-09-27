"""Append-only JSONL tombstone log on a local or mounted filesystem (T24).

Each append is one line written with O_APPEND and fsync'd before returning.
A torn final line (a crash mid-write) is ignored on read; any other malformed
line is an integrity failure. Production places this log in storage that is
not restored with the database (an append-only bucket once ADR-004 selects a
provider).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Iterator

from ...application.tombstones import Tombstone
from ...ports.base import InvalidInput, PermanentFailure


class JsonlTombstoneLog:
    def __init__(self, directory: Path) -> None:
        self.path = Path(directory) / "tombstones.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, tombstone: Tombstone) -> None:
        line = json.dumps({"kind": tombstone.kind, "owner_id": tombstone.owner_id, "ref": tombstone.ref,
                           "recorded_at": tombstone.recorded_at.isoformat()}, sort_keys=True) + "\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)

    def entries(self) -> Iterator[Tombstone]:
        if not self.path.exists():
            return
        raw = self.path.read_bytes()
        lines = raw.split(b"\n")
        complete, torn = lines[:-1], lines[-1]  # the part after the last newline was never completed
        del torn
        for number, line in enumerate(complete, start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                yield Tombstone(data["kind"], data["owner_id"], data["ref"],
                                datetime.fromisoformat(data["recorded_at"]))
            except (ValueError, KeyError, TypeError, InvalidInput) as exc:
                raise PermanentFailure("tombstone_log_corrupt", detail=f"line {number}") from exc


__all__ = ["JsonlTombstoneLog"]
