"""AbuseChallengeProvider port (docs/connectors/abuse-challenge.md).

A verdict is an admission signal only. ``ACCEPTED`` never authorizes an
account, purchase or report; ``UNAVAILABLE`` is not evidence of abuse.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .base import CallContext, CapabilityProfile

PORT = "AbuseChallengeProvider"

WEB_CHALLENGE = "web_challenge"
APP_ATTESTATION = "app_attestation"


class Verdict(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class ChallengeVerdict:
    verdict: Verdict
    reason: str | None = None


class AbuseChallengeProvider(Protocol):
    profile: CapabilityProfile

    def verify(self, token: str, expected_action: str, expected_site: str,
               ctx: CallContext) -> ChallengeVerdict: ...
