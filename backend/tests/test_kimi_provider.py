from __future__ import annotations

import json

import httpx
import pytest

from app.models import AgentMessage, ModelTurnRequest, ToolCall, ToolDefinition
from app.providers.base import ProviderError
from app.providers.kimi import KimiProvider


def stream_response(events: list[dict]) -> httpx.Response:
    body = "\n\n".join([*(f"data: {json.dumps(event)}" for event in events), "data: [DONE]"])
    return httpx.Response(200, text=f"{body}\n\n", headers={"content-type": "text/event-stream"})


@pytest.mark.anyio
async def test_kimi_preserves_reasoning_and_tool_history_across_turns() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        assert payload["model"] == "kimi-k3"
        assert payload["reasoning_effort"] == "high"
        assert payload["max_completion_tokens"] == 131_072
        assert payload["stream"] is False
        assert payload["messages"] == [
            {"role": "system", "content": "You are a Strudel agent."},
            {
                "role": "assistant",
                "content": None,
                "reasoning_content": "I should inspect the candidate first.",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "inspect_diff", "arguments": '{"candidate":"first"}'},
                    }
                ],
            },
            {"role": "tool", "content": '{"valid":true}', "tool_call_id": "call-1"},
        ]
        assert payload["tools"][0]["function"]["strict"] is False
        return httpx.Response(
            200,
            json={
                "id": "cmpl-kimi-1",
                "usage": {"prompt_tokens": 300, "completion_tokens": 80},
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": "I will validate the result.",
                            "reasoning_content": "The diff looks relevant, so validation is next.",
                            "tool_calls": [
                                {
                                    "id": "call-2",
                                    "type": "function",
                                    "function": {
                                        "name": "validate_candidate",
                                        "arguments": '{"candidateCode":"s(\\"bd*4\\")"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
        )

    provider = KimiProvider("test-key", transport=httpx.MockTransport(handler))
    result = await provider.next_turn(
        ModelTurnRequest(
            messages=[
                AgentMessage(role="system", content="You are a Strudel agent."),
                AgentMessage(
                    role="assistant",
                    reasoningContent="I should inspect the candidate first.",
                    toolCalls=[ToolCall(id="call-1", name="inspect_diff", arguments={"candidate": "first"})],
                ),
                AgentMessage(role="tool", content='{"valid":true}', toolCallId="call-1"),
            ],
            tools=[
                ToolDefinition(
                    name="validate_candidate",
                    description="Validate candidate Strudel code.",
                    inputSchema={"type": "object", "additionalProperties": False},
                )
            ],
            model="kimi-k3",
            maxOutputTokens=131_072,
        )
    )

    assert result.assistant_message.content == "I will validate the result."
    assert result.assistant_message.reasoning_content == "The diff looks relevant, so validation is next."
    assert result.assistant_message.tool_calls == [
        ToolCall(id="call-2", name="validate_candidate", arguments={"candidateCode": 's("bd*4")'})
    ]
    assert result.usage.input_tokens == 300
    assert result.usage.output_tokens == 80
    assert result.provider_request_id == "cmpl-kimi-1"


@pytest.mark.anyio
async def test_kimi_streams_content_without_exposing_reasoning_or_tool_arguments() -> None:
    private_arguments = json.dumps({"candidateCode": 's("private")'}, separators=(",", ":"))
    split_at = len(private_arguments) // 2

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["stream"] is True
        assert payload["stream_options"] == {"include_usage": True}
        return stream_response(
            [
                {
                    "id": "cmpl-kimi-stream",
                    "choices": [
                        {
                            "delta": {"reasoning_content": "PRIVATE reasoning ", "content": "Checking the groove "},
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "cmpl-kimi-stream",
                    "choices": [
                        {
                            "delta": {
                                "reasoning_content": "before the tool call.",
                                "content": "before validation.",
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-kimi-1",
                                        "function": {
                                            "name": "validate_",
                                            "arguments": private_arguments[:split_at],
                                        },
                                    }
                                ],
                            },
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "cmpl-kimi-stream",
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {
                                            "name": "candidate",
                                            "arguments": private_arguments[split_at:],
                                        },
                                    }
                                ]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                },
                {
                    "id": "cmpl-kimi-stream",
                    "choices": [],
                    "usage": {"prompt_tokens": 200, "completion_tokens": 60},
                },
            ]
        )

    snapshots: list[str] = []

    async def record_commentary(commentary: str) -> None:
        snapshots.append(commentary)

    result = await KimiProvider("test-key", transport=httpx.MockTransport(handler)).next_turn_stream(
        ModelTurnRequest(messages=[], tools=[], model="kimi-k3", maxOutputTokens=1000),
        record_commentary,
    )

    assert snapshots[-1] == "Checking the groove before validation."
    assert "PRIVATE" not in "".join(snapshots)
    assert "candidateCode" not in "".join(snapshots)
    assert result.assistant_message.reasoning_content == "PRIVATE reasoning before the tool call."
    assert result.assistant_message.tool_calls == [
        ToolCall(id="call-kimi-1", name="validate_candidate", arguments={"candidateCode": 's("private")'})
    ]
    assert result.usage.total_tokens == 260


@pytest.mark.anyio
async def test_kimi_connection_checks_model_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "kimi-k3"}]})

    provider = KimiProvider("test-key", transport=httpx.MockTransport(handler))

    await provider.test_connection()


@pytest.mark.anyio
async def test_kimi_connection_rejects_an_unavailable_model() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [{"id": "kimi-k2.6"}]}))

    with pytest.raises(ProviderError, match="not available"):
        await KimiProvider("test-key", transport=transport).test_connection()


@pytest.mark.anyio
async def test_kimi_rejects_invalid_private_reasoning() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "Done", "reasoning_content": {"private": True}},
                    }
                ]
            },
        )
    )

    with pytest.raises(ProviderError, match="invalid private reasoning"):
        await KimiProvider("test-key", transport=transport).next_turn(
            ModelTurnRequest(messages=[], tools=[], model="kimi-k3", maxOutputTokens=100)
        )
