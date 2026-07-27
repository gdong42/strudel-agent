from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .agent_runtime import (
    AgentRunCancellation,
    cancel_agent_run,
    create_agent_run,
    execute_model_turn,
    fail_agent_run,
)
from .models import AgentRun, AgentRunBudget, AgentRunFailure, AgentRunPublic, EditorVersion
from .providers.base import AgentProvider
from .tools import ToolRegistry


RunUpdateListener = Callable[[AgentRunPublic], Awaitable[None]]


@dataclass
class _RunEntry:
    run: AgentRun
    cancellation: AgentRunCancellation = field(default_factory=AgentRunCancellation)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    task: asyncio.Task[None] | None = None


class AgentRunManager:
    """Own in-memory Agent Runs while provider credentials stay inside active tasks."""

    def __init__(
        self,
        tools: ToolRegistry | None = None,
        on_update: RunUpdateListener | None = None,
    ) -> None:
        self._tools = tools or ToolRegistry()
        self._on_update = on_update
        self._entries: dict[str, _RunEntry] = {}
        self._entries_lock = asyncio.Lock()

    async def start(
        self,
        *,
        intent: str,
        editor_version: EditorVersion,
        apply_mode: str,
        budget: AgentRunBudget,
        provider_name: str,
        model: str,
        provider: AgentProvider,
    ) -> AgentRun:
        run = create_agent_run(
            intent=intent,
            editor_version=editor_version,
            apply_mode=apply_mode,
            budget=budget,
            provider=provider_name,
            model=model,
        )
        entry = _RunEntry(run=run)
        async with self._entries_lock:
            self._entries[run.id] = entry
        await self._publish(run)
        entry.task = asyncio.create_task(self._drive(entry, provider), name=f"agent-run-{run.id}")
        return run.model_copy(deep=True)

    async def get(self, run_id: str) -> AgentRun | None:
        entry = await self._entry(run_id)
        if not entry:
            return None
        async with entry.lock:
            return entry.run.model_copy(deep=True)

    async def get_public(self, run_id: str) -> AgentRunPublic | None:
        run = await self.get(run_id)
        return run.to_public() if run else None

    async def wait(self, run_id: str) -> AgentRun | None:
        entry = await self._entry(run_id)
        if not entry:
            return None
        async with entry.lock:
            task = entry.task
        if task:
            await asyncio.shield(task)
        return await self.get(run_id)

    async def cancel(self, run_id: str) -> AgentRun | None:
        entry = await self._entry(run_id)
        if not entry:
            return None

        published: AgentRun | None = None
        async with entry.lock:
            if entry.run.status == "needs_input":
                entry.run = cancel_agent_run(entry.run)
                task = entry.task
                published = entry.run.model_copy(deep=True)
            elif entry.run.status != "running":
                return entry.run.model_copy(deep=True)
            else:
                entry.cancellation.cancel()
                task = entry.task

        if published:
            await self._publish(published)
        if task:
            await asyncio.shield(task)
        else:
            direct_cancelled: AgentRun | None = None
            async with entry.lock:
                if entry.run.status == "running":
                    entry.run = cancel_agent_run(entry.run)
                    direct_cancelled = entry.run.model_copy(deep=True)
            if direct_cancelled:
                await self._publish(direct_cancelled)
        return await self.get(run_id)

    async def close(self) -> None:
        async with self._entries_lock:
            run_ids = list(self._entries)
        await asyncio.gather(*(self.cancel(run_id) for run_id in run_ids))

    async def _entry(self, run_id: str) -> _RunEntry | None:
        async with self._entries_lock:
            return self._entries.get(run_id)

    async def _drive(self, entry: _RunEntry, provider: AgentProvider) -> None:
        try:
            while True:
                async with entry.lock:
                    run = entry.run
                if run.status != "running":
                    return

                updated = await execute_model_turn(
                    run,
                    provider,
                    self._tools,
                    cancellation=entry.cancellation,
                )
                async with entry.lock:
                    if entry.cancellation.is_cancelled and entry.run.status == "running":
                        updated = cancel_agent_run(entry.run)
                    entry.run = updated
                if updated.to_public() != run.to_public():
                    await self._publish(updated)
                if updated.status != "running":
                    return
        except asyncio.CancelledError:
            entry.cancellation.cancel()
            cancelled: AgentRun | None = None
            async with entry.lock:
                if entry.run.status == "running":
                    entry.run = cancel_agent_run(entry.run)
                    cancelled = entry.run.model_copy(deep=True)
            if cancelled:
                await self._publish(cancelled)
        except Exception:
            failed: AgentRun | None = None
            async with entry.lock:
                if entry.run.status == "running":
                    entry.run = fail_agent_run(
                        entry.run,
                        AgentRunFailure(
                            code="internal_error",
                            message="The agent run could not complete.",
                            retryable=False,
                        ),
                    )
                    failed = entry.run.model_copy(deep=True)
            if failed:
                await self._publish(failed)
        finally:
            async with entry.lock:
                if entry.task is asyncio.current_task():
                    entry.task = None

    async def _publish(self, run: AgentRun) -> None:
        if not self._on_update:
            return
        try:
            await self._on_update(run.to_public())
        except Exception:
            return
