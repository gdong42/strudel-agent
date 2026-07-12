from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..models import GeneratedChange


@dataclass(frozen=True)
class ProviderRequest:
    intent: str
    current_code: str
    scope: str | None = None
    intensity: str | None = None
    timing: str | None = None
    avoid: str | None = None


class AgentProvider(Protocol):
    async def create_change(self, request: ProviderRequest) -> GeneratedChange:
        """Generate a complete replacement for the current Strudel code."""


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
