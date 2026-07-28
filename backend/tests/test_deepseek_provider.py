from __future__ import annotations

import json

import httpx
import pytest

from app.models import AgentMessage, ModelTurnRequest, ToolCall, ToolDefinition
from app.providers.base import ProviderError
from app.providers.deepseek import DeepSeekProvider


@pytest.mark.anyio
async def test_deepseek_provider_normalizes_a_model_turn_and_tool_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/chat/completions"
        assert payload["model"] == "runtime-model"
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["max_tokens"] == 2048
        assert payload["tools"] == [{
            "type": "function",
            "function": {
                "name": "inspect_diff",
                "description": "Inspect the candidate diff.",
                "parameters": {"type": "object", "additionalProperties": False},
            },
        }]
        assert payload["messages"] == [
            {"role": "system", "content": "You are a Strudel agent."},
            {"role": "user", "content": "Make it groovier."},
            {
                "role": "assistant",
                "content": "I will inspect the candidate.",
                "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "inspect_diff", "arguments": '{"candidate":"first"}'},
                }],
            },
            {"role": "tool", "content": '{"valid":true}', "tool_call_id": "call-1"},
        ]
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "usage": {"prompt_tokens": 140, "completion_tokens": 35},
                "choices": [{
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": "I will validate it.",
                        "tool_calls": [{
                            "id": "call-2",
                            "type": "function",
                            "function": {"name": "validate_candidate", "arguments": '{"candidate":"second"}'},
                        }],
                    },
                }],
            },
        )

    result = await DeepSeekProvider("test-key", transport=httpx.MockTransport(handler)).next_turn(
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
    assert result.usage.input_tokens == 140
    assert result.usage.output_tokens == 35
    assert result.provider_request_id == "chatcmpl-1"


@pytest.mark.anyio
async def test_deepseek_connection_checks_model_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/models"
        return httpx.Response(200, json={"data": [{"id": "deepseek-v4-pro"}]})

    provider = DeepSeekProvider("test-key", transport=httpx.MockTransport(handler))

    await provider.test_connection()


@pytest.mark.anyio
async def test_deepseek_connection_rejects_unavailable_model() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"data": [{"id": "deepseek-v4-flash"}]})
    )
    provider = DeepSeekProvider("test-key", transport=transport)

    with pytest.raises(ProviderError, match="not available"):
        await provider.test_connection()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("choice", "message"),
    [
        ({"finish_reason": "stop", "message": {"content": ""}}, "empty model turn"),
        ({"finish_reason": "length", "message": {"content": "ignored"}}, "truncated"),
        ({"finish_reason": "stop", "message": {"content": 1}}, "invalid model content"),
    ],
)
async def test_deepseek_rejects_unusable_model_turn(choice: dict, message: str) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": [choice]}))

    with pytest.raises(ProviderError, match=message):
        await DeepSeekProvider("test-key", transport=transport).next_turn(
            ModelTurnRequest(messages=[], tools=[], model="runtime-model", remainingTokenBudget=1)
        )
