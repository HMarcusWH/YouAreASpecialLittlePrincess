"""Buffered, failure-isolated telemetry.

Telemetry must never block a ledger commit, deletion or Free report: records
go into a bounded buffer, oldest records are dropped under pressure, and
exporter failures are counted rather than raised.
"""
from __future__ import annotations

from collections import deque
from typing import Mapping

from ..ports.base import PortError
from ..ports.telemetry import AttrValue, RecordKind, TelemetryExporter, TelemetryRecord


class BufferedTelemetry:
    def __init__(self, exporter: TelemetryExporter, *, capacity: int = 1000, batch_size: int = 100) -> None:
        if capacity < 1 or batch_size < 1:
            raise ValueError("capacity and batch_size must be positive")
        self._exporter = exporter
        self._buffer: deque[TelemetryRecord] = deque()
        self._capacity = capacity
        self._batch = batch_size
        self.dropped = 0
        self.export_failures = 0

    def record(self, kind: RecordKind, name: str, attributes: Mapping[str, AttrValue] | None = None,
               value: float | None = None) -> None:
        try:
            item = TelemetryRecord(kind, name, dict(attributes or {}), value)
        except PortError:
            self.dropped += 1
            return
        if len(self._buffer) >= self._capacity:
            self._buffer.popleft()
            self.dropped += 1
        self._buffer.append(item)

    def flush(self) -> int:
        """Export up to one batch; returns the number exported. Never raises."""
        batch = [self._buffer[i] for i in range(min(self._batch, len(self._buffer)))]
        if not batch:
            return 0
        try:
            self._exporter.export(batch)
        except Exception:  # noqa: BLE001 - telemetry must not propagate failures
            self.export_failures += 1
            return 0
        for _ in batch:
            self._buffer.popleft()
        return len(batch)

    @property
    def buffered(self) -> int:
        return len(self._buffer)
