from __future__ import annotations

import json

import httpx
import pytest

from app.models import AgentMessage, ChangeRequest, ModelTurnRequest, ToolCall, ToolDefinition
from app.providers.base import ProviderError, ProviderRequest
from app.providers.openai import OpenAIProvider


@pytest.mark.anyio
async def test_openai_provider_sends_strict_schema_and_parses_change() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["store"] is False
        assert payload["text"]["format"]["type"] == "json_schema"
        assert payload["text"]["format"]["strict"] is True
        assert payload["text"]["format"]["schema"]["additionalProperties"] is False
        assert set(payload["text"]["format"]["schema"]["required"]) == {"code", "explanation", "action", "warnings"}
        assert set(payload["text"]["format"]["schema"]["properties"]["action"]["enum"]) == {"apply", "noop"}
        assert payload["model"] == "test-model"
        assert json.loads(payload["input"])["user_intent"] == "make it groovy"
        return httpx.Response(
            200,
            json={
                "output": [{
                    "type": "message",
                    "content": [{
                        "type": "output_text",
                        "text": json.dumps({
                            "code": 's("bd*4")',
                            "explanation": "Added a steady kick.",
                            "action": "apply",
                            "warnings": [],
                        }),
                    }],
                }]
            },
        )

    provider = OpenAIProvider("test-key", "test-model", transport=httpx.MockTransport(handler))
    result = await provider.create_change(ProviderRequest(intent="make it groovy", current_code='s("bd")'))

    assert result.code == 's("bd*4")'
    assert result.explanation == "Added a steady kick."


@pytest.mark.anyio
async def test_openai_provider_includes_reconciliation_context() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(json.loads(request.content)["input"])
        assert prompt["current_strudel_code"] == 's("hh")'
        assert prompt["reconciliation"] == {
            "base_strudel_code": 's("bd")',
            "previous_agent_code": 's("bd*4")',
            "user_edit_diff": '+ s("hh")',
            "attempt": 1,
        }
        return httpx.Response(200, json={"output": [{"content": [{"type": "output_text", "text": '{"code":"s(\\"hh\\")","explanation":"Kept hats.","action":"noop","warnings":[]}'}]}]})

    request = ProviderRequest(
        intent="keep the hats",
        current_code='s("hh")',
        reconciliation=ChangeRequest(
            intent="keep the hats",
            currentCode='s("hh")',
            reconciliation={
                "baseCode": 's("bd")',
                "previousAgentCode": 's("bd*4")',
                "userEditDiff": '+ s("hh")',
                "attempt": 1,
            },
        ).reconciliation,
    )
    result = await OpenAIProvider("test-key", transport=httpx.MockTransport(handler)).create_change(request)

    assert result.action == "noop"


@pytest.mark.anyio
async def test_openai_provider_normalizes_a_model_turn_and_tool_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/v1/responses"
        assert payload["model"] == "runtime-model"
        assert payload["store"] is False
        assert payload["instructions"] == "You are a Strudel agent."
        assert payload["max_output_tokens"] == 2048
        assert payload["tools"] == [{
            "type": "function",
            "name": "inspect_diff",
            "description": "Inspect the candidate diff.",
            "parameters": {"type": "object", "additionalProperties": False},
            "strict": True,
        }]
        assert payload["input"] == [
            {"role": "user", "content": "Make it groovier."},
            {"role": "assistant", "content": "I will inspect the candidate."},
            {
                "type": "function_call",
                "call_id": "call-1",
                "name": "inspect_diff",
                "arguments": '{"candidate":"first"}',
            },
            {"type": "function_call_output", "call_id": "call-1", "output": '{"valid":true}'},
        ]
        return httpx.Response(
            200,
            json={
                "id": "resp-1",
                "usage": {"input_tokens": 120, "output_tokens": 30},
                "output": [
                    {"type": "reasoning", "encrypted_content": "not persisted"},
                    {"type": "message", "content": [{"type": "output_text", "text": "I will validate it."}]},
                    {
                        "type": "function_call",
                        "call_id": "call-2",
                        "name": "validate_candidate",
                        "arguments": '{"candidate":"second"}',
                    },
                ],
            },
        )

    result = await OpenAIProvider("test-key", transport=httpx.MockTransport(handler)).next_turn(
        ModelTurnRequest(
            messages=[
                AgentMessage(role="system", content="You are a Strudel agent."),
                AgentMessage(role="user", content="Make it groovier."),
                AgentMessage(
                    role="assistant",
                    content="I will inspect the candidate.",
                    toolCalls=[ToolCall(id="call-1", name="inspect_diff", arguments={"candidate": "first"})],
                ),
                AgentMessage(role="tool", content='{"valid":true}', toolCallId="call-1"),
            ],
            tools=[
                ToolDefinition(
                    name="inspect_diff",
                    description="Inspect the candidate diff.",
                    inputSchema={"type": "object", "additionalProperties": False},
                )
            ],
            model="runtime-model",
            remainingTokenBudget=2048,
        )
    )

    assert result.assistant_message.content == "I will validate it."
    assert result.assistant_message.tool_calls == [
        ToolCall(id="call-2", name="validate_candidate", arguments={"candidate": "second"})
    ]
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 30
    assert result.provider_request_id == "resp-1"


@pytest.mark.anyio
async def test_openai_provider_rejects_invalid_tool_arguments() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call-1",
                        "name": "inspect_diff",
                        "arguments": "not-json",
                    }
                ]
            },
        )
    )

    with pytest.raises(ProviderError, match="invalid tool arguments"):
        await OpenAIProvider("test-key", transport=transport).next_turn(
            ModelTurnRequest(messages=[], tools=[], model="runtime-model", remainingTokenBudget=1)
        )


@pytest.mark.anyio
async def test_openai_connection_checks_selected_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models/test-model"
        return httpx.Response(200, json={"id": "test-model"})

    provider = OpenAIProvider("test-key", "test-model", transport=httpx.MockTransport(handler))

    await provider.test_connection()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "message", "retryable"),
    [
        (401, "rejected the API key", False),
        (429, "rate limit", True),
        (500, "unavailable", True),
    ],
)
async def test_openai_maps_http_errors(status: int, message: str, retryable: bool) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json={"error": {"message": "raw"}}))
    provider = OpenAIProvider("test-key", transport=transport)

    with pytest.raises(ProviderError, match=message) as captured:
        await provider.test_connection()

    assert captured.value.retryable is retryable


@pytest.mark.anyio
async def test_openai_maps_timeout_without_leaking_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    provider = OpenAIProvider("super-secret", transport=httpx.MockTransport(handler))

    with pytest.raises(ProviderError, match="timed out") as captured:
        await provider.test_connection()

    assert "super-secret" not in str(captured.value)
