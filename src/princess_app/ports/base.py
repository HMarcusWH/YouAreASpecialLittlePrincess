"""Shared connector-port vocabulary: typed failures, call context and capabilities.

Provider exceptions and raw payloads never cross a port. Adapters translate
them with :func:`provider_errors` into the typed failures below. Every call
carries a :class:`CallContext` with a correlation ID, explicit environment and
an absolute deadline.
"""
from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable, Iterator, Mapping, Protocol

_SAFE_CODE = re.compile(r"^[a-z0-9_.:-]{1,64}$")
_SAFE_DETAIL = re.compile(r"^[A-Za-z0-9_.:=!,/ -]{0,120}$")
REDACTED_DETAIL = "[redacted]"
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class PortError(Exception):
    """Base class for typed connector failures.

    ``code`` is a short, safe, low-cardinality reason. ``detail`` is kept only
    when it is a short identifier-like string; anything else (quotes, URLs with
    queries, payload fragments, long text) is replaced by ``[redacted]`` so an
    exception message cannot carry credentials or user content.
    """

    retryable = False

    def __init__(self, code: str, *, detail: str | None = None) -> None:
        if not _SAFE_CODE.match(code):
            raise ValueError(f"unsafe port error code: {code!r}")
        if detail is not None and (not isinstance(detail, str) or not _SAFE_DETAIL.match(detail)):
            detail = REDACTED_DETAIL
        self.code = code
        self.detail = detail
        super().__init__(code if detail is None else f"{code}: {detail}")


class InvalidInput(PortError):
    """The request is malformed for this port; retrying the same input fails again."""


class Unauthenticated(PortError):
    """A credential, token, proof or signature did not verify."""


class NotAuthorized(PortError):
    """The caller is authenticated but lacks authority for this object/operation."""


class NotFound(PortError):
    """The referenced provider object does not exist (or is not visible)."""


class Conflict(PortError):
    """The request conflicts with existing state (for example changed bytes)."""


class Unsupported(PortError):
    """The provider/profile does not implement the requested capability."""


class PermanentFailure(PortError):
    """The provider rejected the operation; do not retry automatically."""


class TransientUnavailable(PortError):
    """The operation was not performed and may be retried later."""

    retryable = True


class DeadlineExceeded(TransientUnavailable):
    """The deadline passed before the request was sent; no remote effect occurred."""


class RateLimited(TransientUnavailable):
    """Throttled; ``retry_after_s`` is the provider hint when one was supplied."""

    def __init__(self, code: str = "rate_limited", *, retry_after_s: float | None = None,
                 detail: str | None = None) -> None:
        super().__init__(code, detail=detail)
        if retry_after_s is not None and not (retry_after_s >= 0):
            raise ValueError("retry_after_s must be non-negative")
        self.retry_after_s = retry_after_s


class AmbiguousOutcome(PortError):
    """The request may or may not have executed remotely (timeout after send).

    Callers must reconcile (or retry with the same semantic dedupe key where the
    provider supports one). It never proves that no execution happened.
    """


class Environment(str, Enum):
    LOCAL = "local"
    TEST = "test"
    PREVIEW = "preview"
    STAGING = "staging"
    PRODUCTION = "production"

    @classmethod
    def parse(cls, value: object) -> "Environment":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            for member in cls:
                if member.value == value:
                    return member
        raise InvalidInput("unknown_environment", detail=repr(value)[:64])


class ProviderMode(str, Enum):
    """How an adapter reaches its provider."""

    FAKE = "fake"
    SANDBOX = "sandbox"
    LIVE = "live"


# Which adapter modes each environment may compose. Production must use live
# providers; live providers are never composed into local/test/preview.
ALLOWED_MODES: Mapping[Environment, frozenset[ProviderMode]] = {
    Environment.LOCAL: frozenset({ProviderMode.FAKE}),
    Environment.TEST: frozenset({ProviderMode.FAKE, ProviderMode.SANDBOX}),
    Environment.PREVIEW: frozenset({ProviderMode.FAKE, ProviderMode.SANDBOX}),
    Environment.STAGING: frozenset({ProviderMode.SANDBOX, ProviderMode.LIVE}),
    Environment.PRODUCTION: frozenset({ProviderMode.LIVE}),
}


def check_mode_allowed(environment: Environment, mode: ProviderMode) -> None:
    if mode not in ALLOWED_MODES[environment]:
        raise InvalidInput("mode_not_allowed_in_environment",
                           detail=f"{mode.value} in {environment.value}")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def require_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise InvalidInput("naive_or_non_utc_time", detail=name)
    return value


def require_opaque_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not _OPAQUE_ID.match(value):
        raise InvalidInput("invalid_identifier", detail=name)
    return value


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return utc_now()


class IdGenerator(Protocol):
    def new_id(self, prefix: str) -> str: ...


@dataclass(frozen=True)
class CallContext:
    """Per-call envelope. ``deadline`` is absolute UTC; ``operation_key`` is a
    semantic dedupe key only where the port documents one."""

    correlation_id: str
    environment: Environment
    deadline: datetime
    operation_key: str | None = None

    def __post_init__(self) -> None:
        require_opaque_id(self.correlation_id, "correlation_id")
        object.__setattr__(self, "environment", Environment.parse(self.environment))
        require_utc(self.deadline, "deadline")
        if self.operation_key is not None:
            require_opaque_id(self.operation_key, "operation_key")

    def remaining(self, clock: Clock) -> timedelta:
        return self.deadline - clock.now()

    def check_deadline(self, clock: Clock) -> None:
        if self.remaining(clock) <= timedelta(0):
            raise DeadlineExceeded("deadline_exceeded")


@dataclass(frozen=True)
class CapabilityProfile:
    """Verified capabilities of one adapter configuration.

    Capabilities are explicit strings owned by each port module. An operation
    outside the profile raises :class:`Unsupported`; it never degrades silently.
    """

    port: str
    provider: str
    mode: ProviderMode
    capabilities: frozenset[str]
    retry_owner: str = "application"
    notes: tuple[str, ...] = field(default_factory=tuple)

    def require(self, capability: str) -> None:
        if capability not in self.capabilities:
            raise Unsupported("capability_not_supported", detail=f"{self.provider}:{capability}")

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities


ErrorMapper = Callable[[BaseException], PortError | None]


@contextlib.contextmanager
def provider_errors(mapper: ErrorMapper | None = None) -> Iterator[None]:
    """Translate any non-port exception into a typed, redacted port failure.

    The original exception is dropped from the chain (``from None``) so SDK
    messages, request bodies and headers cannot leak through tracebacks.
    ``mapper`` may classify known provider errors; unknown errors become a
    generic :class:`PermanentFailure`.
    """
    try:
        yield
    except PortError:
        raise
    except Exception as exc:  # noqa: BLE001 - boundary translation is the purpose
        mapped = mapper(exc) if mapper is not None else None
        if mapped is None:
            mapped = PermanentFailure("provider_error", detail=type(exc).__name__)
        raise mapped from None
