from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import httpx

from ..models import (
    AgentMessage,
    ModelTurnRequest,
    ModelTurnResult,
    ModelUsage,
    ToolCall,
    ToolDefinition,
)
from .base import CommentaryEmitter, ModelCommentaryCallback, ProviderError, parse_tool_arguments
from .http import ProviderHttpClient


DEFAULT_OPENAI_MODEL = "gpt-5.6-terra"
OPENAI_API_BASE = "https://api.openai.com/v1/"

class OpenAIProvider:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_OPENAI_MODEL,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self.http = ProviderHttpClient("OpenAI", api_key, OPENAI_API_BASE, transport=transport)

    async def next_turn(self, request: ModelTurnRequest) -> ModelTurnResult:
        payload = self._turn_payload(request)
        response = await self.http.request_json(
            "POST",
            "responses",
            json=payload,
        )
        return self._parse_turn(response)

    async def next_turn_stream(
        self,
        request: ModelTurnRequest,
        on_commentary: ModelCommentaryCallback,
    ) -> ModelTurnResult:
        payload = self._turn_payload(request)
        payload["stream"] = True
        emitter = CommentaryEmitter(on_commentary)
        completed_response: dict[str, Any] | None = None

        async for event in self.http.stream_sse_json("POST", "responses", json=payload):
            event_type = event.get("type")
            if event_type == "response.output_text.delta":
                delta = event.get("delta")
                if not isinstance(delta, str):
                    raise ProviderError("OpenAI returned invalid public commentary")
                await emitter.push(delta)
            elif event_type == "response.completed":
                response = event.get("response")
                if not isinstance(response, dict):
                    raise ProviderError("OpenAI returned an invalid model turn")
                completed_response = response
            elif event_type in {"response.failed", "error"}:
                raise ProviderError("OpenAI could not complete the model turn", retryable=True)

        await emitter.flush()
        if completed_response is None:
            raise ProviderError("OpenAI returned an incomplete model turn", retryable=True)
        return self._parse_turn(completed_response)

    async def test_connection(self) -> None:
        await self.http.request_json("GET", f"models/{quote(self.model, safe='')}")

    def _turn_payload(self, request: ModelTurnRequest) -> dict[str, object]:
        if request.max_output_tokens == 0:
            raise ProviderError("OpenAI model turn has no output token budget")
        payload: dict[str, object] = {
            "model": request.model,
            "store": False,
            "input": self._turn_input(request.messages),
            "max_output_tokens": request.max_output_tokens,
        }
        instructions = self._instructions(request.messages)
        if instructions:
            payload["instructions"] = instructions
        if request.tools:
            payload["tools"] = [self._tool_definition(tool) for tool in request.tools]
        return payload

    @staticmethod
    def _instructions(messages: list[AgentMessage]) -> str | None:
        instructions = [message.content for message in messages if message.role == "system" and message.content]
        return "\n\n".join(instructions) or None

    @staticmethod
    def _turn_input(messages: list[AgentMessage]) -> list[dict[str, object]]:
        input_items: list[dict[str, object]] = []
        for message in messages:
            if message.role == "system":
                continue
            if message.role == "tool":
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.tool_call_id,
                        "output": message.content,
                    }
                )
                continue
            if message.role == "assistant" and message.tool_calls:
                if message.content:
                    input_items.append({"role": "assistant", "content": message.content})
                for tool_call in message.tool_calls:
                    input_items.append(
                        {
                            "type": "function_call",
                            "call_id": tool_call.id,
                            "name": tool_call.name,
                            "arguments": json.dumps(tool_call.arguments, separators=(",", ":")),
                        }
                    )
                continue
            input_items.append({"role": message.role, "content": message.content})
        return input_items

    @staticmethod
    def _tool_definition(tool: ToolDefinition) -> dict[str, object]:
        return {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
            "strict": True,
        }

    @staticmethod
    def _parse_turn(response: dict[str, Any]) -> ModelTurnResult:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        output = response.get("output", [])
        if not isinstance(output, list):
            raise ProviderError("OpenAI returned an invalid model turn")
        for item in output:
            if not isinstance(item, dict):
                raise ProviderError("OpenAI returned an invalid model turn")
            if item.get("type") == "function_call":
                call_id = item.get("call_id")
                name = item.get("name")
                if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
                    raise ProviderError("OpenAI returned an invalid tool call")
                tool_calls.append(
                    ToolCall(
                        id=call_id,
                        name=name,
                        arguments=parse_tool_arguments(item.get("arguments"), provider_label="OpenAI"),
                    )
                )
                continue
            if item.get("type") != "message":
                continue
            contents = item.get("content", [])
            if not isinstance(contents, list):
                raise ProviderError("OpenAI returned an invalid model turn")
            for content in contents:
                if not isinstance(content, dict):
                    raise ProviderError("OpenAI returned an invalid model turn")
                if content.get("type") == "refusal":
                    raise ProviderError("OpenAI refused the model turn")
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    text_parts.append(content["text"])
        if not text_parts and not tool_calls:
            raise ProviderError("OpenAI returned an empty model turn")
        usage = response.get("usage")
        usage_data = usage if isinstance(usage, dict) else {}
        return ModelTurnResult(
            assistantMessage=AgentMessage(role="assistant", content="".join(text_parts), toolCalls=tool_calls),
            usage=ModelUsage(
                inputTokens=OpenAIProvider._token_count(usage_data.get("input_tokens")),
                outputTokens=OpenAIProvider._token_count(usage_data.get("output_tokens")),
            ),
            providerRequestId=response.get("id") if isinstance(response.get("id"), str) else None,
        )

    @staticmethod
    def _token_count(value: object) -> int:
        return value if isinstance(value, int) and value >= 0 else 0
