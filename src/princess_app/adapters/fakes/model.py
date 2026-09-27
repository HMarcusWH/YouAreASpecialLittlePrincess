"""Fake PremiumModelProvider driven by an explicit responder.

There is no default "success" output: tests and local composition supply a
responder that returns an output mapping, a non-completed state, or raises a
typed port failure. Every call is counted so read/export paths can prove they
never reach the model.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Union

from ...ports import model as port
from ...ports.base import CallContext, InvalidInput
from .base import FakeAdapter, SequentialIds

Response = Union[Mapping[str, Any], port.GenerationState, port.ProviderGenerationResult]
Responder = Callable[[port.GenerationRequest], Response]


class FakePremiumModel(FakeAdapter):
    port_name = port.PORT
    provider = "fake-model"
    default_capabilities = frozenset({port.STRUCTURED_OUTPUT, port.IMAGE_INPUT, port.NO_PROVIDER_STORAGE})

    def __init__(self, responder: Responder, *, model: str = "fake-vision-model", **kwargs) -> None:
        super().__init__(**kwargs)
        self._responder = responder
        self.model = model
        self._ids = SequentialIds()
        self.requests: list[port.GenerationRequest] = []

    def generate(self, request: port.GenerationRequest, ctx: CallContext) -> port.ProviderGenerationResult:
        self.profile.require(port.STRUCTURED_OUTPUT)
        if request.image is not None:
            self.profile.require(port.IMAGE_INPUT)

        def effect() -> port.ProviderGenerationResult:
            self.requests.append(request)
            response = self._responder(request)
            request_id = self._ids.new_id("req")
            if isinstance(response, port.ProviderGenerationResult):
                return response
            if isinstance(response, port.GenerationState):
                if response is port.GenerationState.COMPLETED:
                    raise InvalidInput("completed_state_needs_output")
                return port.ProviderGenerationResult(response, None, request_id, self.model, self.model,
                                                     port.ProviderUsage(100, 0))
            return port.ProviderGenerationResult(port.GenerationState.COMPLETED, dict(response), request_id,
                                                 self.model, self.model, port.ProviderUsage(100, 50))

        return self._run("generate", ctx, effect)
