from __future__ import annotations

import httpx
from pydantic import ValidationError

from ..models import GeneratedChange
from ..prompt_contract import PromptContractOutput, SYSTEM_PROMPT, build_prompt_input
from .base import ProviderError, ProviderRequest
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
