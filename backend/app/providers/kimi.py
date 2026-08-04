from __future__ import annotations

import json
from typing import Literal

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


DEFAULT_KIMI_MODEL = "kimi-k3"
DEFAULT_KIMI_REASONING_EFFORT = "high"
KIMI_API_BASE = "https://api.moonshot.cn/v1/"
KimiReasoningEffort = Literal["low", "high", "max"]


class KimiProvider:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_KIMI_MODEL,
        *,
        reasoning_effort: KimiReasoningEffort = DEFAULT_KIMI_REASONING_EFFORT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.http = ProviderHttpClient("Kimi", api_key, KIMI_API_BASE, transport=transport)

    async def next_turn(self, request: ModelTurnRequest) -> ModelTurnResult:
        response = await self.http.request_json(
            "POST",
            "chat/completions",
            json=self._turn_payload(request, stream=False),
        )
        return self._parse_turn(response)

    async def next_turn_stream(
        self,
        request: ModelTurnRequest,
        on_commentary: ModelCommentaryCallback,
    ) -> ModelTurnResult:
        emitter = CommentaryEmitter(on_commentary)
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: dict[int, dict[str, str]] = {}
        usage: dict[str, object] = {}
        request_id: str | None = None
        finish_reason: str | None = None

        async for chunk in self.http.stream_sse_json(
            "POST",
            "chat/completions",
            json=self._turn_payload(request, stream=True),
        ):
            chunk_id = chunk.get("id")
            if isinstance(chunk_id, str):
                request_id = chunk_id
            chunk_usage = chunk.get("usage")
            if isinstance(chunk_usage, dict):
                usage = chunk_usage
            choices = chunk.get("choices", [])
            if not isinstance(choices, list):
                raise ProviderError("Kimi returned an invalid model stream")
            if not choices:
                continue
            choice = choices[0]
            if not isinstance(choice, dict):
                raise ProviderError("Kimi returned an invalid model stream")
            delta = choice.get("delta", {})
            if not isinstance(delta, dict):
                raise ProviderError("Kimi returned an invalid model stream")

            reasoning = delta.get("reasoning_content")
            if reasoning is not None:
                if not isinstance(reasoning, str):
                    raise ProviderError("Kimi returned invalid private reasoning")
                reasoning_parts.append(reasoning)
            content = delta.get("content")
            if content is not None:
                if not isinstance(content, str):
                    raise ProviderError("Kimi returned invalid public commentary")
                content_parts.append(content)
                await emitter.push(content)
            self._merge_stream_tool_calls(tool_calls, delta.get("tool_calls"))
            raw_finish_reason = choice.get("finish_reason")
            if raw_finish_reason is not None:
                if not isinstance(raw_finish_reason, str):
                    raise ProviderError("Kimi returned an invalid model stream")
                finish_reason = raw_finish_reason

        await emitter.flush()
        if finish_reason is None:
            raise ProviderError("Kimi returned an incomplete model turn", retryable=True)
        message_tool_calls = [
            {
                "id": item["id"],
                "type": "function",
                "function": {"name": item["name"], "arguments": item["arguments"]},
            }
            for _, item in sorted(tool_calls.items())
        ]
        return self._parse_turn(
            {
                "id": request_id,
                "usage": usage,
                "choices": [
                    {
                        "finish_reason": finish_reason,
                        "message": {
                            "content": "".join(content_parts),
                            "reasoning_content": "".join(reasoning_parts),
                            "tool_calls": message_tool_calls,
                        },
                    }
                ],
            }
        )

    async def test_connection(self) -> None:
        response = await self.http.request_json("GET", "models")
        models = {item.get("id") for item in response.get("data", []) if isinstance(item, dict)}
        if self.model not in models:
            raise ProviderError(f'Kimi model "{self.model}" is not available for this API key')

    def _turn_payload(self, request: ModelTurnRequest, *, stream: bool) -> dict[str, object]:
        if request.max_output_tokens == 0:
            raise ProviderError("Kimi model turn has no output token budget")
        payload: dict[str, object] = {
            "model": request.model,
            "messages": [self._turn_message(message) for message in request.messages],
            "reasoning_effort": self.reasoning_effort,
            "max_completion_tokens": request.max_output_tokens,
            "stream": stream,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        if request.tools:
            payload["tools"] = [self._tool_definition(tool) for tool in request.tools]
        return payload

    @staticmethod
    def _turn_message(message: AgentMessage) -> dict[str, object]:
        content: str | None = message.content
        if message.role == "assistant" and message.tool_calls and not content:
            content = None
        payload: dict[str, object] = {"role": message.role, "content": content}
        if message.role == "assistant" and message.reasoning_content is not None:
            payload["reasoning_content"] = message.reasoning_content
        if message.role == "assistant" and message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": json.dumps(tool_call.arguments, separators=(",", ":")),
                    },
                }
                for tool_call in message.tool_calls
            ]
        if message.role == "tool":
            payload["tool_call_id"] = message.tool_call_id
        return payload

    @staticmethod
    def _tool_definition(tool: ToolDefinition) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
                "strict": False,
            },
        }

    @staticmethod
    def _merge_stream_tool_calls(target: dict[int, dict[str, str]], raw_calls: object) -> None:
        if raw_calls is None:
            return
        if not isinstance(raw_calls, list):
            raise ProviderError("Kimi returned invalid tool calls")
        for position, raw_call in enumerate(raw_calls):
            if not isinstance(raw_call, dict):
                raise ProviderError("Kimi returned invalid tool calls")
            index = raw_call.get("index", position)
            if not isinstance(index, int) or index < 0:
                raise ProviderError("Kimi returned invalid tool calls")
            current = target.setdefault(index, {"id": "", "name": "", "arguments": ""})
            call_id = raw_call.get("id")
            if call_id is not None:
                if not isinstance(call_id, str):
                    raise ProviderError("Kimi returned invalid tool calls")
                current["id"] += call_id
            function = raw_call.get("function")
            if function is None:
                continue
            if not isinstance(function, dict):
                raise ProviderError("Kimi returned invalid tool calls")
            name = function.get("name")
            arguments = function.get("arguments")
            if name is not None:
                if not isinstance(name, str):
                    raise ProviderError("Kimi returned invalid tool calls")
                current["name"] += name
            if arguments is not None:
                if not isinstance(arguments, str):
                    raise ProviderError("Kimi returned invalid tool calls")
                current["arguments"] += arguments

    @staticmethod
    def _parse_turn(response: dict) -> ModelTurnResult:
        choices = response.get("choices", [])
        if not isinstance(choices, list) or not choices:
            raise ProviderError("Kimi returned an empty model turn")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise ProviderError("Kimi returned an invalid model turn")
        finish_reason = choice.get("finish_reason")
        if finish_reason == "length":
            raise ProviderError("Kimi model turn was truncated")
        if finish_reason == "content_filter":
            raise ProviderError("Kimi filtered the model turn")
        message = choice.get("message", {})
        if not isinstance(message, dict):
            raise ProviderError("Kimi returned an invalid model turn")
        content = message.get("content")
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise ProviderError("Kimi returned invalid model content")
        reasoning_content = message.get("reasoning_content")
        if reasoning_content is not None and not isinstance(reasoning_content, str):
            raise ProviderError("Kimi returned invalid private reasoning")

        tool_calls: list[ToolCall] = []
        raw_tool_calls = message.get("tool_calls", [])
        if raw_tool_calls is None:
            raw_tool_calls = []
        if not isinstance(raw_tool_calls, list):
            raise ProviderError("Kimi returned invalid tool calls")
        for raw_tool_call in raw_tool_calls:
            if not isinstance(raw_tool_call, dict):
                raise ProviderError("Kimi returned invalid tool calls")
            call_id = raw_tool_call.get("id")
            function = raw_tool_call.get("function")
            if not isinstance(call_id, str) or not call_id or not isinstance(function, dict):
                raise ProviderError("Kimi returned an invalid tool call")
            name = function.get("name")
            if not isinstance(name, str) or not name:
                raise ProviderError("Kimi returned an invalid tool call")
            tool_calls.append(
                ToolCall(
                    id=call_id,
                    name=name,
                    arguments=parse_tool_arguments(function.get("arguments"), provider_label="Kimi"),
                )
            )
        if not content and not tool_calls:
            raise ProviderError("Kimi returned an empty model turn")

        usage = response.get("usage")
        usage_data = usage if isinstance(usage, dict) else {}
        return ModelTurnResult(
            assistantMessage=AgentMessage(
                role="assistant",
                content=content,
                reasoningContent=reasoning_content,
                toolCalls=tool_calls,
            ),
            usage=ModelUsage(
                inputTokens=KimiProvider._token_count(usage_data.get("prompt_tokens")),
                outputTokens=KimiProvider._token_count(usage_data.get("completion_tokens")),
            ),
            providerRequestId=response.get("id") if isinstance(response.get("id"), str) else None,
        )

    @staticmethod
    def _token_count(value: object) -> int:
        return value if isinstance(value, int) and value >= 0 else 0
