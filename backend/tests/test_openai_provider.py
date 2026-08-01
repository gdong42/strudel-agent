from __future__ import annotations

import json

import httpx
import pytest

from app.models import AgentMessage, ModelTurnRequest, ToolCall, ToolDefinition
from app.providers.base import ProviderError
from app.providers.openai import OpenAIProvider


def stream_response(events: list[dict]) -> httpx.Response:
    body = "\n\n".join([*(f"data: {json.dumps(event)}" for event in events), "data: [DONE]"])
    return httpx.Response(200, text=f"{body}\n\n", headers={"content-type": "text/event-stream"})


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
async def test_openai_provider_streams_only_public_text_and_rebuilds_the_final_turn() -> None:
    private_arguments = json.dumps({"candidateCode": 's("private")'})

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["stream"] is True
        return stream_response([
            {"type": "response.output_text.delta", "delta": "Reviewing the arrangement "},
            {"type": "response.reasoning_text.delta", "delta": "PRIVATE reasoning"},
            {"type": "response.function_call_arguments.delta", "delta": private_arguments},
            {"type": "response.output_text.delta", "delta": "before validation."},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-stream-1",
                    "usage": {"input_tokens": 80, "output_tokens": 20},
                    "output": [
                        {
                            "type": "message",
                            "content": [{
                                "type": "output_text",
                                "text": "Reviewing the arrangement before validation.",
                            }],
                        },
                        {
                            "type": "function_call",
                            "call_id": "call-stream-1",
                            "name": "validate_candidate",
                            "arguments": private_arguments,
                        },
                    ],
                },
            },
        ])

    snapshots: list[str] = []

    async def record_commentary(commentary: str) -> None:
        snapshots.append(commentary)

    result = await OpenAIProvider("test-key", transport=httpx.MockTransport(handler)).next_turn_stream(
        ModelTurnRequest(messages=[], tools=[], model="runtime-model", remainingTokenBudget=200),
        record_commentary,
    )

    assert snapshots[-1] == "Reviewing the arrangement before validation."
    assert "PRIVATE" not in "".join(snapshots)
    assert "candidateCode" not in "".join(snapshots)
    assert result.assistant_message.tool_calls == [
        ToolCall(
            id="call-stream-1",
            name="validate_candidate",
            arguments={"candidateCode": 's("private")'},
        )
    ]
    assert result.provider_request_id == "resp-stream-1"
    assert result.usage.total_tokens == 100


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
async def test_openai_provider_rejects_an_empty_model_turn() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"output": []}))

    with pytest.raises(ProviderError, match="empty model turn"):
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
