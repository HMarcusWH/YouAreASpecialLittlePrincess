"""OpenAI Responses API adapter for PremiumModelProvider (T15), disabled by default.

Plain HTTPS through ``httpx`` (already in the reviewed app lock) rather than a
new SDK dependency. One request per ``generate`` call, no retries, ``store``
false, strict JSON-schema output compiled per request, the image sent inline
as a data URL read through the ObjectStore port (the provider never receives
a storage URL or credential), and the system prompt from the application.

Constructing it requires ``spend_gate_approved=True``. That flag records the
``api_access_spend_before_live_calls`` owner gate (approved account, data
controls and spend cap); no composition sets it today, and tests only use it
against an in-process mock transport. No model alias is chosen here: the
model ID is configuration owned by that gate.

Nothing is logged. Errors carry codes only; request/response bodies, prompts,
images and provider messages never leave this module.
"""
from __future__ import annotations

import base64
import json
from datetime import timedelta
from typing import Any, Mapping

import httpx

from ...ports import model as port
from ...ports.base import (
    AmbiguousOutcome,
    CallContext,
    CapabilityProfile,
    Clock,
    Environment,
    InvalidInput,
    PermanentFailure,
    ProviderMode,
    RateLimited,
    TransientUnavailable,
    Unsupported,
    check_mode_allowed,
)
from ...ports.storage import ObjectStore

DEFAULT_BASE_URL = "https://api.openai.com/v1"
IMAGE_MEDIA = frozenset({"image/jpeg", "image/png"})


def _thaw(value: Any) -> Any:
    return json.loads(json.dumps(value, default=dict))


class OpenAIResponsesModel:
    port_name = port.PORT

    def __init__(self, *, api_key: str, model: str, system_prompt: str, store: ObjectStore, clock: Clock,
                 environment: Environment, mode: ProviderMode, spend_gate_approved: bool = False,
                 base_url: str = DEFAULT_BASE_URL, timeout_s: float = 45.0,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.environment = Environment.parse(environment)
        check_mode_allowed(self.environment, mode)
        if mode is ProviderMode.FAKE:
            raise InvalidInput("real_adapter_cannot_be_fake")
        if not spend_gate_approved:
            raise Unsupported("live_model_calls_not_approved")
        if not api_key or not model or not system_prompt:
            raise InvalidInput("model_adapter_misconfigured")
        if not base_url.startswith("https://") and transport is None:
            raise InvalidInput("provider_base_url_must_be_https")
        self.model = model
        self._prompt = system_prompt
        self._store = store
        self._clock = clock
        self._timeout_s = timeout_s
        self._client = httpx.Client(base_url=base_url.rstrip("/"), transport=transport, follow_redirects=False,
                                    headers={"Authorization": f"Bearer {api_key}"})
        self.profile = CapabilityProfile(port=port.PORT, provider="openai-responses", mode=mode,
                                         capabilities=frozenset({port.STRUCTURED_OUTPUT, port.IMAGE_INPUT,
                                                                 port.NO_PROVIDER_STORAGE}))

    def __repr__(self) -> str:  # never print the credential
        return f"OpenAIResponsesModel(model={self.model!r}, mode={self.profile.mode.value})"

    def _body(self, request: port.GenerationRequest, ctx: CallContext) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "input_text", "text": json.dumps(_thaw(request.packet),
                                                                                  sort_keys=True)}]
        if request.image is not None:
            if request.image.media_type not in IMAGE_MEDIA:
                raise InvalidInput("unsupported_image_media_type")
            data = self._store.read_object(request.image, ctx)
            encoded = base64.b64encode(data).decode("ascii")
            content.append({"type": "input_image", "image_url": f"data:{request.image.media_type};base64,{encoded}"})
        return {
            "model": self.model,
            "store": False,
            "input": [{"role": "system", "content": [{"type": "input_text", "text": self._prompt}]},
                      {"role": "user", "content": content}],
            "text": {"format": {"type": "json_schema", "name": "premium_output", "strict": True,
                                "schema": _thaw(request.output_schema)}},
            "max_output_tokens": request.max_output_tokens,
        }

    def generate(self, request: port.GenerationRequest, ctx: CallContext) -> port.ProviderGenerationResult:
        self.profile.require(port.STRUCTURED_OUTPUT)
        if ctx.environment is not self.environment:
            raise InvalidInput("environment_mismatch")
        ctx.check_deadline(self._clock)
        body = self._body(request, ctx)
        ctx.check_deadline(self._clock)  # reading the image may have used the budget: send nothing late
        remaining = ctx.remaining(self._clock)
        budget = max(0.1, min(self._timeout_s, remaining / timedelta(seconds=1)))
        timeout = httpx.Timeout(budget, connect=min(5.0, budget))
        try:
            response = self._client.post("/responses", json=body, timeout=timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise TransientUnavailable("provider_unreachable") from None  # nothing was sent
        except (httpx.TimeoutException, httpx.TransportError):
            # Sent (or partially sent): the provider may have executed and billed.
            raise AmbiguousOutcome("provider_outcome_unknown") from None
        return self._result(response)

    def _result(self, response: httpx.Response) -> port.ProviderGenerationResult:
        status = response.status_code
        if status == 429:
            retry = response.headers.get("retry-after")
            raise RateLimited("provider_rate_limited",
                              retry_after_s=float(retry) if retry and retry.replace(".", "", 1).isdigit() else None)
        if status in (500, 502, 503, 504):
            raise TransientUnavailable("provider_unavailable")
        if status in (401, 403):
            raise PermanentFailure("provider_credentials_rejected")
        if status != 200:
            raise PermanentFailure("provider_rejected_request", detail=str(status))
        try:
            payload = response.json()
        except ValueError:
            raise AmbiguousOutcome("provider_response_unreadable") from None
        usage = payload.get("usage") or {}
        meta = dict(provider_request_id=_safe_id(response.headers.get("x-request-id") or payload.get("id")),
                    model_requested=self.model, model_returned=_safe_id(payload.get("model")),
                    usage=port.ProviderUsage(_int(usage.get("input_tokens")), _int(usage.get("output_tokens"))))
        state = payload.get("status")
        if state == "incomplete":
            return port.ProviderGenerationResult(port.GenerationState.INCOMPLETE, None, **meta)
        if state != "completed":
            raise PermanentFailure("provider_generation_failed")
        texts, refused = [], False
        for item in payload.get("output") or ():
            if not isinstance(item, Mapping) or item.get("type") != "message":
                continue  # reasoning or other items carry no answer
            for part in item.get("content") or ():
                if isinstance(part, Mapping) and part.get("type") == "refusal":
                    refused = True
                elif isinstance(part, Mapping) and part.get("type") == "output_text":
                    texts.append(part.get("text") or "")
        if refused:
            return port.ProviderGenerationResult(port.GenerationState.REFUSED, None, **meta)
        try:
            parsed = json.loads("".join(texts)) if len(texts) == 1 else None
        except ValueError:
            parsed = None
        if not isinstance(parsed, dict):
            # Billed but unusable: report it as incomplete so usage is still settled.
            return port.ProviderGenerationResult(port.GenerationState.INCOMPLETE, None, **meta)
        return port.ProviderGenerationResult(port.GenerationState.COMPLETED, parsed, **meta)

    def close(self) -> None:
        self._client.close()


def _int(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _safe_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in "._:-")[:128]
    return cleaned or None


__all__ = ["DEFAULT_BASE_URL", "OpenAIResponsesModel"]
