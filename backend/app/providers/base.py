from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..models import GeneratedChange, ReconciliationContext


@dataclass(frozen=True)
class ProviderRequest:
    intent: str
    current_code: str
    reconciliation: ReconciliationContext | None = None


class AgentProvider(Protocol):
    async def create_change(self, request: ProviderRequest) -> GeneratedChange:
        """Generate a complete replacement for the current Strudel code."""

    async def test_connection(self) -> None:
        """Raise ProviderError when the provider is not ready for requests."""


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
