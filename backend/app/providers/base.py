from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..models import GeneratedChange, ModelTurnRequest, ModelTurnResult, ReconciliationContext


@dataclass(frozen=True)
class ProviderRequest:
    intent: str
    current_code: str
    reconciliation: ReconciliationContext | None = None


class OneShotAgentProvider(Protocol):
    async def create_change(self, request: ProviderRequest) -> GeneratedChange:
        """Transitional interface for the current one-shot generation path."""

    async def test_connection(self) -> None:
        """Raise ProviderError when the provider is not ready for requests."""


class AgentProvider(Protocol):
    async def next_turn(self, request: ModelTurnRequest) -> ModelTurnResult:
        """Run one normalized model turn for the Agent Runtime."""

    async def test_connection(self) -> None:
        """Raise ProviderError when the provider is not ready for requests."""


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
