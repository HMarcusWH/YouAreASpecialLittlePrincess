"""PremiumModelProvider port (docs/connectors/premium-model.md).

The adapter owns wire format, image transfer and error normalization only.
Authorization, credit reservation, question/candidate selection and
validation of the output against the frozen packet belong to the application.
A :class:`ProviderGenerationResult` is not a published analysis.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol

from .base import CallContext, CapabilityProfile, InvalidInput, require_opaque_id
from .storage import StoredObject, require_sha256

PORT = "PremiumModelProvider"

# Capability names.
STRUCTURED_OUTPUT = "structured_output"
IMAGE_INPUT = "image_input"
NO_PROVIDER_STORAGE = "no_provider_storage"


class GenerationState(str, Enum):
    COMPLETED = "COMPLETED"
    REFUSED = "REFUSED"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True)
class GenerationRequest:
    attempt_id: str
    packet: Mapping[str, Any]
    packet_digest: str
    output_schema: Mapping[str, Any]
    policy_version: str
    image: StoredObject | None = None
    max_output_tokens: int = 4000

    def __post_init__(self) -> None:
        require_opaque_id(self.attempt_id, "attempt_id")
        require_sha256(self.packet_digest, "packet_digest")
        require_opaque_id(self.policy_version, "policy_version")
        if type(self.max_output_tokens) is not int or not 0 < self.max_output_tokens <= 32000:
            raise InvalidInput("invalid_generation_request", detail="max_output_tokens")

    def __repr__(self) -> str:  # never print packets or images
        return f"GenerationRequest(attempt_id={self.attempt_id!r}, packet_digest={self.packet_digest!r})"


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class ProviderGenerationResult:
    state: GenerationState
    output: Mapping[str, Any] | None
    provider_request_id: str | None
    model_requested: str
    model_returned: str | None
    usage: ProviderUsage = field(default_factory=ProviderUsage)

    def __post_init__(self) -> None:
        if self.state is GenerationState.COMPLETED and self.output is None:
            raise InvalidInput("completed_without_output")
        if self.state is not GenerationState.COMPLETED and self.output is not None:
            raise InvalidInput("non_completed_with_output")

    def __repr__(self) -> str:
        return (f"ProviderGenerationResult(state={self.state.value}, "
                f"provider_request_id={self.provider_request_id!r})")


class PremiumModelProvider(Protocol):
    profile: CapabilityProfile

    def generate(self, request: GenerationRequest, ctx: CallContext) -> ProviderGenerationResult:
        """One bounded provider request; no hidden retries.

        A timeout after transmission raises ``AmbiguousOutcome``.
        """
        ...
