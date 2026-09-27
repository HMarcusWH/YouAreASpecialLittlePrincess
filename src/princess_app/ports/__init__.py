"""Application-owned connector ports.

Each module defines internal DTOs, capability names and a ``Protocol``. No
module here imports a provider SDK, HTTP client, SQL library or adapter.
"""
from .base import (
    AmbiguousOutcome as AmbiguousOutcome,
    CallContext as CallContext,
    CapabilityProfile as CapabilityProfile,
    Clock as Clock,
    Conflict as Conflict,
    DeadlineExceeded as DeadlineExceeded,
    Environment as Environment,
    IdGenerator as IdGenerator,
    InvalidInput as InvalidInput,
    NotAuthorized as NotAuthorized,
    NotFound as NotFound,
    PermanentFailure as PermanentFailure,
    PortError as PortError,
    ProviderMode as ProviderMode,
    RateLimited as RateLimited,
    SystemClock as SystemClock,
    TransientUnavailable as TransientUnavailable,
    Unauthenticated as Unauthenticated,
    Unsupported as Unsupported,
    check_mode_allowed as check_mode_allowed,
    provider_errors as provider_errors,
)

PORT_NAMES = (
    "IdentityProvider", "ObjectStore", "PremiumModelProvider", "PaymentProvider",
    "NativePurchaseClient", "TransactionalMailer", "PushProvider",
    "AbuseChallengeProvider", "AnalyticsSink", "TelemetryExporter",
)
