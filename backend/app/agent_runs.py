from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .agent_runtime import (
    AgentRunCancellation,
    AgentRuntimeTransitionError,
    cancel_agent_run,
    create_agent_run,
    execute_model_turn,
    fail_agent_run,
    resume_agent_run,
    update_agent_run_editor_version,
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
    revision: int = 0
    cancel_requested: bool = False
    active_turn_revision: int | None = None


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
        await self._start_worker(entry, provider, run)
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

    async def resume(
        self,
        run_id: str,
        *,
        question_id: str,
        answer: str,
        provider_name: str,
        model: str,
        provider: AgentProvider,
    ) -> AgentRun | None:
        entry = await self._entry(run_id)
        if not entry:
            return None

        start_gate = asyncio.Event()
        async with entry.lock:
            if entry.run.provider != provider_name or entry.run.model != model:
                raise AgentRuntimeTransitionError("Agent Run must resume with its original provider and model")
            entry.run = resume_agent_run(entry.run, question_id=question_id, answer=answer)
            entry.revision += 1
            entry.cancel_requested = False
            entry.cancellation = AgentRunCancellation()
            resumed = entry.run.model_copy(deep=True)
            self._create_worker(entry, provider, resumed, start_gate)

        try:
            await self._publish(resumed)
        finally:
            start_gate.set()
        return resumed

    async def update_editor(
        self,
        run_id: str,
        *,
        base_hash: str,
        editor_version: EditorVersion,
    ) -> AgentRun | None:
        entry = await self._entry(run_id)
        if not entry:
            return None

        async with entry.lock:
            updated = update_agent_run_editor_version(
                entry.run,
                base_hash=base_hash,
                editor_version=editor_version,
            )
            if updated == entry.run:
                return updated.model_copy(deep=True)
            entry.run = updated
            entry.revision += 1
            if updated.status == "running" and entry.active_turn_revision is not None:
                entry.cancellation.cancel()
            return updated.model_copy(deep=True)

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
                entry.cancel_requested = True
                task = entry.task
                published = entry.run.model_copy(deep=True)
            elif entry.run.status != "running":
                return entry.run.model_copy(deep=True)
            else:
                entry.cancel_requested = True
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

    async def _start_worker(self, entry: _RunEntry, provider: AgentProvider, run: AgentRun) -> None:
        start_gate = asyncio.Event()
        async with entry.lock:
            if entry.run != run or entry.run.status != "running":
                return
            self._create_worker(entry, provider, run, start_gate)
        try:
            await self._publish(run)
        finally:
            start_gate.set()

    def _create_worker(
        self,
        entry: _RunEntry,
        provider: AgentProvider,
        run: AgentRun,
        start_gate: asyncio.Event,
    ) -> None:
        entry.task = asyncio.create_task(
            self._drive(entry, provider, start_gate),
            name=f"agent-run-{run.id}",
        )

    async def _drive(
        self,
        entry: _RunEntry,
        provider: AgentProvider,
        start_gate: asyncio.Event,
    ) -> None:
        await start_gate.wait()
        try:
            while True:
                async with entry.lock:
                    run = entry.run
                    if run.status != "running":
                        return
                    revision = entry.revision
                    cancellation = entry.cancellation
                    entry.active_turn_revision = revision

                updated = await execute_model_turn(
                    run,
                    provider,
                    self._tools,
                    cancellation=cancellation,
                )
                async with entry.lock:
                    if entry.active_turn_revision == revision:
                        entry.active_turn_revision = None
                    if entry.cancel_requested and entry.run.status == "running":
                        updated = cancel_agent_run(entry.run)
                    elif entry.revision != revision:
                        if entry.cancellation is cancellation:
                            entry.cancellation = AgentRunCancellation()
                        continue
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
                    entry.cancel_requested = True
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
                    entry.active_turn_revision = None

    async def _publish(self, run: AgentRun) -> None:
        if not self._on_update:
            return
        try:
            await self._on_update(run.to_public())
        except Exception:
            return
