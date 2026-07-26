from __future__ import annotations

from urllib.parse import quote
from typing import Any

import httpx
from pydantic import ValidationError

from ..models import GeneratedChange
from ..prompt_contract import PromptContractOutput, SYSTEM_PROMPT, build_prompt_input
from .base import ProviderError, ProviderRequest
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
