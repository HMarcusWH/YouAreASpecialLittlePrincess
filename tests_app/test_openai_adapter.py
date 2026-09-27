"""OpenAI Responses adapter against an in-process transport (no network, no key)."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import timedelta

import httpx
import pytest

from princess_app.adapters.fakes import FakeClock, FakeObjectStore
from princess_app.adapters.openai import OpenAIResponsesModel
from princess_app.application.premium import SYSTEM_PROMPT
from princess_app.ports import model as port
from princess_app.ports.base import (
    AmbiguousOutcome,
    CallContext,
    Environment,
    InvalidInput,
    PermanentFailure,
    ProviderMode,
    RateLimited,
    TransientUnavailable,
    Unsupported,
)
from princess_app.ports.storage import UploadPolicy
from princess_contracts import canonical_digest

KEY = "sk-test-not-a-real-key"
PACKET = {"packet_id": "packet_1", "questions": [{"question_id": "Q_GLOBAL_COHERENCE"}]}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["packet_id"],
          "properties": {"packet_id": {"type": "string", "enum": ["packet_1"]}}}
PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-bytes"


def completed(text, **extra):
    return {"id": "resp_1", "model": "provider-model-2026", "status": "completed",
            "output": [{"type": "reasoning", "summary": []},
                       {"type": "message", "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": 1200, "output_tokens": 80}, **extra}


class Setup:
    def __init__(self, handler, environment=Environment.TEST):
        self.clock = FakeClock()
        self.store = FakeObjectStore(clock=self.clock, environment=environment)
        self.environment = environment
        self.seen = []

        def record(request):
            self.seen.append(request)
            return handler(request)

        self.model = OpenAIResponsesModel(api_key=KEY, model="configured-model", system_prompt=SYSTEM_PROMPT,
                                          store=self.store, clock=self.clock, environment=environment,
                                          mode=ProviderMode.SANDBOX, spend_gate_approved=True,
                                          transport=httpx.MockTransport(record))

    def ctx(self, environment=None):
        return CallContext("corr-1", environment or self.environment, self.clock.now() + timedelta(seconds=30))

    def image(self):
        ctx = self.ctx()
        policy = UploadPolicy(frozenset({"image/png"}), 10_000, 600)
        ticket = self.store.issue_upload_ticket("asset_1", "image/png", policy, ctx)
        self.store.client_put(ticket, PNG)
        return self.store.promote_verified_input(ticket.upload_id, hashlib.sha256(PNG).hexdigest(), ctx)

    def request(self, image=None):
        return port.GenerationRequest(attempt_id="attempt_1", packet=PACKET, packet_digest=canonical_digest(PACKET),
                                      output_schema=SCHEMA, policy_version="premium-policy-1", image=image,
                                      max_output_tokens=2000)


def test_construction_requires_the_spend_gate_and_a_real_mode():
    clock = FakeClock()
    common = dict(api_key=KEY, model="m", system_prompt="p", store=object(), clock=clock)
    with pytest.raises(Unsupported):
        OpenAIResponsesModel(**common, environment=Environment.STAGING, mode=ProviderMode.SANDBOX)
    with pytest.raises(InvalidInput):
        OpenAIResponsesModel(**common, environment=Environment.LOCAL, mode=ProviderMode.FAKE, spend_gate_approved=True)
    with pytest.raises(InvalidInput):
        OpenAIResponsesModel(**common, environment=Environment.PRODUCTION, mode=ProviderMode.SANDBOX,
                             spend_gate_approved=True)
    with pytest.raises(InvalidInput):
        OpenAIResponsesModel(**common, environment=Environment.STAGING, mode=ProviderMode.SANDBOX,
                             spend_gate_approved=True, base_url="http://insecure.invalid/v1")


def test_one_strict_stateless_request_with_inline_image():
    setup = Setup(lambda r: httpx.Response(200, json=completed(json.dumps({"packet_id": "packet_1"})),
                                           headers={"x-request-id": "req_abc"}))
    result = setup.model.generate(setup.request(setup.image()), setup.ctx())
    assert result.state is port.GenerationState.COMPLETED and result.output == {"packet_id": "packet_1"}
    assert (result.provider_request_id, result.model_returned) == ("req_abc", "provider-model-2026")
    assert (result.usage.input_tokens, result.usage.output_tokens) == (1200, 80)
    [sent] = setup.seen
    body = json.loads(sent.content)
    assert sent.url.path == "/v1/responses" and sent.headers["authorization"] == f"Bearer {KEY}"
    assert body["store"] is False and body["max_output_tokens"] == 2000 and body["model"] == "configured-model"
    assert "tools" not in body and "previous_response_id" not in body
    assert body["text"]["format"] == {"type": "json_schema", "name": "premium_output", "strict": True,
                                      "schema": SCHEMA}
    system, user = body["input"]
    assert system["content"][0]["text"] == SYSTEM_PROMPT
    assert json.loads(user["content"][0]["text"]) == PACKET
    image = user["content"][1]["image_url"]
    assert image == "data:image/png;base64," + base64.b64encode(PNG).decode()
    assert "http" not in image and "asset_1" not in json.dumps(body)


@pytest.mark.parametrize("payload,state", [
    ({**completed(""), "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]},
     port.GenerationState.REFUSED),
    ({**completed(""), "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}},
     port.GenerationState.INCOMPLETE),
    (completed("{not json"), port.GenerationState.INCOMPLETE),
    (completed("[1, 2]"), port.GenerationState.INCOMPLETE),
])
def test_refusal_truncation_and_unusable_text_keep_usage(payload, state):
    setup = Setup(lambda r: httpx.Response(200, json=payload))
    result = setup.model.generate(setup.request(), setup.ctx())
    assert result.state is state and result.output is None and result.usage.input_tokens == 1200


@pytest.mark.parametrize("response,error", [
    (httpx.Response(429, headers={"retry-after": "7"}, json={"error": {"message": "slow down"}}), RateLimited),
    (httpx.Response(503, json={"error": {"message": "overloaded"}}), TransientUnavailable),
    (httpx.Response(401, json={"error": {"message": "bad key sk-test"}}), PermanentFailure),
    (httpx.Response(400, json={"error": {"message": "schema invalid"}}), PermanentFailure),
    (httpx.Response(200, json={**completed("{}"), "status": "failed"}), PermanentFailure),
])
def test_http_failures_map_to_typed_redacted_errors(response, error):
    setup = Setup(lambda r: response)
    with pytest.raises(error) as err:
        setup.model.generate(setup.request(), setup.ctx())
    assert "sk-test" not in str(err.value) and "schema" not in str(err.value)
    if error is RateLimited:
        assert err.value.retry_after_s == 7


def test_timeouts_after_sending_are_ambiguous_but_connect_failures_are_not():
    def read_timeout(request):
        raise httpx.ReadTimeout("timed out", request=request)

    def refused(request):
        raise httpx.ConnectError("refused", request=request)

    timed_out = Setup(read_timeout)
    with pytest.raises(AmbiguousOutcome):
        timed_out.model.generate(timed_out.request(), timed_out.ctx())
    setup = Setup(refused)
    with pytest.raises(TransientUnavailable):
        setup.model.generate(setup.request(), setup.ctx())


def test_cross_environment_context_is_rejected_before_anything_is_sent():
    setup = Setup(lambda r: httpx.Response(200, json=completed("{}")))
    with pytest.raises(InvalidInput):
        setup.model.generate(setup.request(), setup.ctx(Environment.PRODUCTION))
    assert setup.seen == [] and KEY not in repr(setup.model)
