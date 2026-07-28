from __future__ import annotations

import json
from typing import Any, Protocol

from ..models import ModelTurnRequest, ModelTurnResult


class AgentProvider(Protocol):
    async def next_turn(self, request: ModelTurnRequest) -> ModelTurnResult:
        """Run one normalized model turn for the Agent Runtime."""

    async def test_connection(self) -> None:
        """Raise ProviderError when the provider is not ready for requests."""


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def parse_tool_arguments(arguments: object, *, provider_label: str) -> dict[str, Any]:
    if not isinstance(arguments, str):
        raise ProviderError(f"{provider_label} returned invalid tool arguments")
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError as error:
        raise ProviderError(f"{provider_label} returned invalid tool arguments") from error
    if not isinstance(parsed, dict):
        raise ProviderError(f"{provider_label} returned invalid tool arguments")
    return parsed
