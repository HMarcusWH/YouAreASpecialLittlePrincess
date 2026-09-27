"""Deterministic fakes for every connector port (standard library only)."""
from .admission import FakeAbuseChallenge, FakeAnalyticsSink, FakeTelemetryExporter
from .base import FakeClock, FaultPlan, SequentialIds
from .identity import FakeIdentityProvider
from .messaging import FakeMailer, FakePushProvider
from .model import FakePremiumModel
from .payments import FakeNativePurchaseClient, FakePaymentProvider
from .storage import FakeObjectStore

__all__ = [
    "FakeAbuseChallenge", "FakeAnalyticsSink", "FakeClock", "FakeIdentityProvider", "FakeMailer",
    "FakeNativePurchaseClient", "FakeObjectStore", "FakePaymentProvider", "FakePremiumModel",
    "FakePushProvider", "FakeTelemetryExporter", "FaultPlan", "SequentialIds",
]
