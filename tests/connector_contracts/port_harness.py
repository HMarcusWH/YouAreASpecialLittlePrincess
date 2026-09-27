"""Shared helpers for connector contract tests (fakes today, sandboxes later)."""
from __future__ import annotations

from datetime import timedelta

from princess_app.adapters.fakes import FakeClock
from princess_app.ports.base import CallContext, Environment

ENV = Environment.TEST


def ctx(clock: FakeClock, *, seconds: float = 30, environment: Environment = ENV,
        key: str | None = None) -> CallContext:
    return CallContext(correlation_id="corr-1", environment=environment,
                       deadline=clock.now() + timedelta(seconds=seconds), operation_key=key)
