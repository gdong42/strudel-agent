from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from ..models import ModelTurnRequest, ModelTurnResult


ModelCommentaryCallback = Callable[[str], Awaitable[None]]


class AgentProvider(Protocol):
    async def next_turn(self, request: ModelTurnRequest) -> ModelTurnResult:
        """Run one normalized model turn for the Agent Runtime."""

    async def test_connection(self) -> None:
        """Raise ProviderError when the provider is not ready for requests."""


class StreamingAgentProvider(Protocol):
    async def next_turn_stream(
        self,
        request: ModelTurnRequest,
        on_commentary: ModelCommentaryCallback,
    ) -> ModelTurnResult:
        """Run one turn while emitting cumulative, explicitly public text snapshots."""


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class CommentaryEmitter:
    """Batch provider text deltas so public SSE updates do not fire per token."""

    def __init__(self, callback: ModelCommentaryCallback) -> None:
        self._callback: ModelCommentaryCallback | None = callback
        self._pending = ""
        self._content = ""
        self._last_emit = time.monotonic()

    async def push(self, delta: str) -> None:
        if not delta or self._callback is None:
            return
        self._pending += delta
        elapsed = time.monotonic() - self._last_emit
        if len(self._pending) >= 32 or elapsed >= 0.15 or delta.endswith((".", "!", "?", "。", "！", "？", "\n")):
            await self.flush()

    async def flush(self) -> None:
        if not self._pending or self._callback is None:
            return
        pending, self._pending = self._pending, ""
        self._content += pending
        try:
            await self._callback(self._content)
        except Exception:
            self._callback = None
        self._last_emit = time.monotonic()


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
