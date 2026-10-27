"""Native Anthropic count/generate/receipt path over an in-process HTTP transport."""
import asyncio
from datetime import datetime, timezone
import json
from types import MethodType
from uuid import uuid4

from anthropic import AsyncAnthropic
import httpx
import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.usage import RunUsage

from agents import _providers
from agents.assessment_guide import assessment_guide_agent
from agents.topic_checklist import CHECKLIST_LIMITS
from agents.topic_checklist_model import wrap_topic_checklist_model
from services.usage_receipts import prepare_checklist_usage_receipt

_LOCAL_SEND = AsyncAnthropic.request


@pytest.mark.parametrize("token_count", [1000, 0])
def test_native_anthropic_schema_usage_and_receipt_without_api_key(monkeypatch, token_count):
    payload = {"overview": "Review recursion.", "topics": [{
        "name": "Recursion", "description": "Base cases", "importance": .9,
        "source_ids": ["notes"], "study_points": ["Explain why recursion needs a base case."],
    }]}
    requests = []

    def transport(request):
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        assert body["model"] == "claude-haiku-5-5"
        assert body["output_config"]["format"]["type"] == "json_schema"
        assert body["output_config"]["format"]["schema"]["additionalProperties"] is False
        if request.url.path.endswith("/count_tokens"):
            return httpx.Response(200, json={"input_tokens": token_count})
        assert request.url.path.endswith("/messages")
        return httpx.Response(200, json={
            "id": "msg_local", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
            "content": [{"type": "text", "text": json.dumps(payload)}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1000, "output_tokens": 500,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        })

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http_client:
            client = AsyncAnthropic(api_key="local-test-only", http_client=http_client, max_retries=0)
            # Restore SDK request ONLY on this instance; its transport cannot leave process.
            client.request = MethodType(_LOCAL_SEND, client)
            provider = AnthropicProvider(anthropic_client=client)
            monkeypatch.setattr(_providers, "_new_anthropic_provider", lambda: provider)
            monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
            monkeypatch.delenv("SAPLING_MODEL_ASSESSMENT_GUIDE", raising=False)
            model = wrap_topic_checklist_model(_providers.model_for("assessment_guide"))
            with assessment_guide_agent.override(model=model):
                usage = RunUsage()
                result = await assessment_guide_agent.run("Generate from notes", deps={
                    "sources": [{"id": "notes"}], "assessments": [],
                }, usage=usage, usage_limits=CHECKLIST_LIMITS)
                return result, usage

    if token_count == 0:
        with pytest.raises(UnexpectedModelBehavior, match="valid token count"):
            asyncio.run(run())
        assert len(requests) == 1
        return
    result, usage = asyncio.run(run())
    assert result.output.overview == payload["overview"]
    assert len(requests) == 2  # one preflight and one generation, no retries
    response = result.all_messages()[-1]
    receipt = prepare_checklist_usage_receipt(operation_id=uuid4(), user_id="local-student",
        approved_model="claude-haiku-5-5", responses=(response,), dispatched_requests=1,
        usage=usage, completed=True, dispatched_at=datetime.now(timezone.utc))
    assert receipt.to_row()["cost_usd"] == .00035
    assert receipt.to_row()["provider"] == "anthropic"
