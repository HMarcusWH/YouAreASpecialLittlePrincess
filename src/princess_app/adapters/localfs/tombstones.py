"""Append-only JSONL tombstone log on a local or mounted filesystem (T24).

Each record is written as one ``write`` of ``"\\n" + json + "\\n"`` with
O_APPEND and fsync'd before returning. The leading newline keeps a record
separate from a torn predecessor (a crash mid-write), so one torn write costs
exactly one unreadable line and never corrupts the records after it. On read,
an incomplete final line is ignored; any other line that does not parse is
counted as unreadable and reported, and every readable record still replays.
Production places this log in storage that is not restored with the database
(an append-only bucket once ADR-004 selects a provider).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ...application.tombstones import LogContents, Tombstone
from ...ports.base import InvalidInput


class JsonlTombstoneLog:
    def __init__(self, directory: Path) -> None:
        self.path = Path(directory) / "tombstones.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, tombstone: Tombstone) -> None:
        data = ("\n" + json.dumps(tombstone.to_json(), sort_keys=True) + "\n").encode("utf-8")
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            written = 0
            while written < len(data):
                written += os.write(fd, data[written:])
            os.fsync(fd)
        finally:
            os.close(fd)

    def read(self) -> LogContents:
        if not self.path.exists():
            return LogContents((), 0)
        *complete, _torn = self.path.read_bytes().split(b"\n")  # text after the last newline never finished
        tombstones: list[Tombstone] = []
        unreadable = 0
        for line in complete:
            if not line.strip():
                continue
            try:
                tombstones.append(Tombstone.from_json(json.loads(line)))
            except (ValueError, KeyError, TypeError, AttributeError, InvalidInput):
                unreadable += 1
        return LogContents(tuple(tombstones), unreadable)

    def entries(self) -> tuple[Tombstone, ...]:
        return self.read().tombstones


__all__ = ["JsonlTombstoneLog"]
