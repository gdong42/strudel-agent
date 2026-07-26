from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

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

    async def create_change(self, request: ProviderRequest) -> GeneratedChange:
        response = await self.http.request_json(
            "POST",
            "responses",
            json={
                "model": self.model,
                "store": False,
                "reasoning": {"effort": "low"},
                "instructions": SYSTEM_PROMPT,
                "input": self._input(request),
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "strudel_change",
                        "strict": True,
                        "schema": PromptContractOutput.model_json_schema(),
                    }
                },
            },
        )
        output = self._parse_output(response)
        return GeneratedChange(**output.model_dump())

    async def next_turn(self, request: ModelTurnRequest) -> ModelTurnResult:
        if request.remaining_token_budget == 0:
            raise ProviderError("OpenAI model turn has no remaining token budget")
        payload: dict[str, object] = {
            "model": request.model,
            "store": False,
            "input": self._turn_input(request.messages),
            "max_output_tokens": request.remaining_token_budget,
        }
        instructions = self._instructions(request.messages)
        if instructions:
            payload["instructions"] = instructions
        if request.tools:
            payload["tools"] = [self._tool_definition(tool) for tool in request.tools]
        response = await self.http.request_json(
            "POST",
            "responses",
            json=payload,
        )
        return self._parse_turn(response)

    async def test_connection(self) -> None:
        await self.http.request_json("GET", f"models/{quote(self.model, safe='')}")

    @staticmethod
    def _input(request: ProviderRequest) -> str:
        return build_prompt_input(
            intent=request.intent,
            current_code=request.current_code,
            reconciliation=request.reconciliation,
        )

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
    def _parse_output(response: dict[str, Any]) -> PromptContractOutput:
        texts: list[str] = []
        for item in response.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "refusal":
                    raise ProviderError("OpenAI refused to generate this change")
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    texts.append(content["text"])
        if not texts:
            raise ProviderError("OpenAI returned no generated change")
        try:
            return PromptContractOutput.model_validate_json("".join(texts))
        except ValidationError as error:
            raise ProviderError("OpenAI returned an invalid structured change") from error

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
