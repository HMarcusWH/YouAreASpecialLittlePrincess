"""Deterministic fake infrastructure: injected clock, IDs and scripted faults.

A fake is not an always-success stub. Tests script failures per operation,
including the ambiguous case where the remote effect happened but the caller
saw a timeout (``after_effect=True``).
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, TypeVar

from ...ports.base import (
    AmbiguousOutcome,
    CallContext,
    CapabilityProfile,
    Environment,
    InvalidInput,
    PortError,
    ProviderMode,
    check_mode_allowed,
)

T = TypeVar("T")
EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, start: datetime = EPOCH) -> None:
        if start.tzinfo is None:
            raise ValueError("FakeClock needs an aware UTC start time")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> datetime:
        if seconds < 0:
            raise ValueError("time does not go backwards")
        self._now += timedelta(seconds=seconds)
        return self._now

    def set(self, value: datetime) -> None:
        if value < self._now:
            raise ValueError("time does not go backwards")
        self._now = value


class SequentialIds:
    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)

    def new_id(self, prefix: str) -> str:
        self._counters[prefix] += 1
        return f"{prefix}_{self._counters[prefix]:06d}"


@dataclass(frozen=True)
class Fault:
    error: PortError
    after_effect: bool = False


class FaultPlan:
    """Per-operation FIFO of scripted failures."""

    def __init__(self) -> None:
        self._queue: dict[str, deque[Fault]] = defaultdict(deque)

    def inject(self, operation: str, error: PortError, *, after_effect: bool = False, times: int = 1) -> None:
        for _ in range(times):
            self._queue[operation].append(Fault(error, after_effect))

    def take(self, operation: str) -> Fault | None:
        queue = self._queue.get(operation)
        return queue.popleft() if queue else None

    def pending(self) -> int:
        return sum(len(q) for q in self._queue.values())


class FakeAdapter:
    """Common behaviour: environment/mode guard, deadlines, faults and latency."""

    port_name = "unset"
    provider = "fake"
    default_capabilities: frozenset[str] = frozenset()

    def __init__(self, *, clock: FakeClock | None = None, environment: Environment = Environment.TEST,
                 capabilities: Iterable[str] | None = None, latency_s: float = 0.0) -> None:
        environment = Environment.parse(environment)
        # A fake can never be composed into production.
        check_mode_allowed(environment, ProviderMode.FAKE)
        self.clock = clock or FakeClock()
        self.environment = environment
        self.latency_s = latency_s
        self.faults = FaultPlan()
        self.calls: list[str] = []
        caps = self.default_capabilities if capabilities is None else frozenset(capabilities)
        self.profile = CapabilityProfile(port=self.port_name, provider=self.provider, mode=ProviderMode.FAKE,
                                         capabilities=frozenset(caps))

    def _run(self, operation: str, ctx: CallContext, effect: Callable[[], T]) -> T:
        if ctx.environment is not self.environment:
            raise InvalidInput("environment_mismatch", detail=f"{ctx.environment.value}!={self.environment.value}")
        ctx.check_deadline(self.clock)
        self.calls.append(operation)
        fault = self.faults.take(operation)
        if fault is not None and not fault.after_effect:
            raise fault.error
        result = effect()
        if self.latency_s:
            self.clock.advance(self.latency_s)
        if fault is not None:
            raise fault.error
        if self.clock.now() > ctx.deadline:
            raise AmbiguousOutcome("timeout_after_send")
        return result
