from __future__ import annotations

import json

import httpx
import pytest

from app.models import AgentMessage, ChangeRequest, ModelTurnRequest, ToolCall, ToolDefinition
from app.providers.base import ProviderError, ProviderRequest
from app.providers.deepseek import DeepSeekProvider


@pytest.mark.anyio
async def test_deepseek_provider_uses_json_output_and_parses_change() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-v4-pro"
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["response_format"] == {"type": "json_object"}
        assert "JSON" in payload["messages"][0]["content"]
        assert json.loads(payload["messages"][1]["content"])["user_intent"] == "add a break"
        return httpx.Response(
            200,
            json={
                "choices": [{
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps({
                            "code": 's("bd ~ ~ ~")',
                            "explanation": "Opened space for a break.",
                            "action": "apply",
                            "warnings": [],
                        })
                    },
                }]
            },
        )

    provider = DeepSeekProvider("test-key", transport=httpx.MockTransport(handler))
    result = await provider.create_change(ProviderRequest(intent="add a break", current_code='s("bd*4")'))

    assert result.code == 's("bd ~ ~ ~")'
    assert result.explanation == "Opened space for a break."


@pytest.mark.anyio
async def test_deepseek_provider_includes_reconciliation_context() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        prompt = json.loads(payload["messages"][1]["content"])
        assert prompt["reconciliation"]["user_edit_diff"] == '+ s("hh")'
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": '{"code":"s(\\"hh\\")","explanation":"Kept hats.","action":"noop","warnings":[]}'}}]})

    reconciliation = ChangeRequest(
        intent="keep the hats",
        currentCode='s("hh")',
        reconciliation={
            "baseCode": 's("bd")',
            "previousAgentCode": 's("bd*4")',
            "userEditDiff": '+ s("hh")',
            "attempt": 1,
        },
    ).reconciliation
    result = await DeepSeekProvider("test-key", transport=httpx.MockTransport(handler)).create_change(
        ProviderRequest(intent="keep the hats", current_code='s("hh")', reconciliation=reconciliation)
    )

    assert result.action == "noop"


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
        ({"finish_reason": "stop", "message": {"content": ""}}, "empty"),
        ({"finish_reason": "length", "message": {"content": "{}"}}, "truncated"),
        ({"finish_reason": "stop", "message": {"content": '{"code":"x"}'}}, "invalid structured"),
    ],
)
async def test_deepseek_rejects_unusable_output(choice: dict, message: str) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": [choice]}))
    provider = DeepSeekProvider("test-key", transport=transport)

    with pytest.raises(ProviderError, match=message):
        await provider.create_change(ProviderRequest(intent="change it", current_code='s("bd")'))
