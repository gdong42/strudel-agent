from __future__ import annotations

from collections import deque

from app.models import ModelTurnRequest, ModelTurnResult
from app.providers.base import ProviderError


class ScriptedAgentProvider:
    """Deterministic multi-turn provider for Agent Runtime tests."""

    def __init__(self, responses: list[ModelTurnResult | Exception]) -> None:
        self._responses = deque(responses)
        self.requests: list[ModelTurnRequest] = []

    async def next_turn(self, request: ModelTurnRequest) -> ModelTurnResult:
        self.requests.append(request.model_copy(deep=True))
        if not self._responses:
            raise ProviderError("Scripted provider has no remaining response")
        response = self._responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response.model_copy(deep=True)

    async def test_connection(self) -> None:
        return None
