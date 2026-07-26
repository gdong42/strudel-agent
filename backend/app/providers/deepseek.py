from __future__ import annotations

import json

import httpx
from pydantic import ValidationError

from ..models import (
    AgentMessage,
    GeneratedChange,
    ModelTurnRequest,
    ModelTurnResult,
    ModelUsage,
    ToolCall,
    ToolDefinition,
)
from ..prompt_contract import PromptContractOutput, SYSTEM_PROMPT, build_prompt_input
from .base import ProviderError, ProviderRequest, parse_tool_arguments
from .http import ProviderHttpClient


DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-pro"
DEEPSEEK_API_BASE = "https://api.deepseek.com/"

class DeepSeekProvider:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_DEEPSEEK_MODEL,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self.http = ProviderHttpClient("DeepSeek", api_key, DEEPSEEK_API_BASE, transport=transport)

    async def create_change(self, request: ProviderRequest) -> GeneratedChange:
        response = await self.http.request_json(
            "POST",
            "chat/completions",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": self._input(request)},
                ],
                "thinking": {"type": "disabled"},
                "response_format": {"type": "json_object"},
                "max_tokens": 16_384,
                "stream": False,
            },
        )
        output = self._parse_output(response)
        return GeneratedChange(**output.model_dump())

    async def next_turn(self, request: ModelTurnRequest) -> ModelTurnResult:
        if request.remaining_token_budget == 0:
            raise ProviderError("DeepSeek model turn has no remaining token budget")
        payload: dict[str, object] = {
            "model": request.model,
            "messages": [self._turn_message(message) for message in request.messages],
            "thinking": {"type": "disabled"},
            "max_tokens": request.remaining_token_budget,
            "stream": False,
        }
        if request.tools:
            payload["tools"] = [self._tool_definition(tool) for tool in request.tools]
        response = await self.http.request_json(
            "POST",
            "chat/completions",
            json=payload,
        )
        return self._parse_turn(response)

    async def test_connection(self) -> None:
        response = await self.http.request_json("GET", "models")
        models = {item.get("id") for item in response.get("data", []) if isinstance(item, dict)}
        if self.model not in models:
            raise ProviderError(f'DeepSeek model "{self.model}" is not available for this API key')

    @staticmethod
    def _input(request: ProviderRequest) -> str:
        return build_prompt_input(
            intent=request.intent,
            current_code=request.current_code,
            reconciliation=request.reconciliation,
        )

    @staticmethod
    def _turn_message(message: AgentMessage) -> dict[str, object]:
        content: str | None = message.content
        if message.role == "assistant" and message.tool_calls and not content:
            content = None
        payload: dict[str, object] = {"role": message.role, "content": content}
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
            },
        }

    @staticmethod
    def _parse_output(response: dict) -> PromptContractOutput:
        choices = response.get("choices", [])
        if not choices:
            raise ProviderError("DeepSeek returned no generated change")
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise ProviderError("DeepSeek response was truncated")
        content = choice.get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("DeepSeek returned an empty generated change")
        try:
            return PromptContractOutput.model_validate_json(content)
        except ValidationError as error:
            raise ProviderError("DeepSeek returned an invalid structured change") from error

    @staticmethod
    def _parse_turn(response: dict) -> ModelTurnResult:
        choices = response.get("choices", [])
        if not isinstance(choices, list) or not choices:
            raise ProviderError("DeepSeek returned an empty model turn")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise ProviderError("DeepSeek returned an invalid model turn")
        if choice.get("finish_reason") == "length":
            raise ProviderError("DeepSeek model turn was truncated")
        message = choice.get("message", {})
        if not isinstance(message, dict):
            raise ProviderError("DeepSeek returned an invalid model turn")
        content = message.get("content")
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise ProviderError("DeepSeek returned invalid model content")
        tool_calls: list[ToolCall] = []
        raw_tool_calls = message.get("tool_calls", [])
        if raw_tool_calls is None:
            raw_tool_calls = []
        if not isinstance(raw_tool_calls, list):
            raise ProviderError("DeepSeek returned invalid tool calls")
        for raw_tool_call in raw_tool_calls:
            if not isinstance(raw_tool_call, dict):
                raise ProviderError("DeepSeek returned invalid tool calls")
            call_id = raw_tool_call.get("id")
            function = raw_tool_call.get("function")
            if not isinstance(call_id, str) or not call_id or not isinstance(function, dict):
                raise ProviderError("DeepSeek returned an invalid tool call")
            name = function.get("name")
            if not isinstance(name, str) or not name:
                raise ProviderError("DeepSeek returned an invalid tool call")
            tool_calls.append(
                ToolCall(
                    id=call_id,
                    name=name,
                    arguments=parse_tool_arguments(function.get("arguments"), provider_label="DeepSeek"),
                )
            )
        if not content and not tool_calls:
            raise ProviderError("DeepSeek returned an empty model turn")
        usage = response.get("usage")
        usage_data = usage if isinstance(usage, dict) else {}
        return ModelTurnResult(
            assistantMessage=AgentMessage(role="assistant", content=content, toolCalls=tool_calls),
            usage=ModelUsage(
                inputTokens=DeepSeekProvider._token_count(usage_data.get("prompt_tokens")),
                outputTokens=DeepSeekProvider._token_count(usage_data.get("completion_tokens")),
            ),
            providerRequestId=response.get("id") if isinstance(response.get("id"), str) else None,
        )

    @staticmethod
    def _token_count(value: object) -> int:
        return value if isinstance(value, int) and value >= 0 else 0
