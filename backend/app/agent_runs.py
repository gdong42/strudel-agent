from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .agent_runtime import (
    AgentRunCancellation,
    AgentRuntimeTransitionError,
    cancel_agent_run,
    create_agent_run,
    discard_unstaged_completed_agent_run,
    execute_model_turn,
    fail_agent_run,
    reopen_completed_agent_run,
    resume_agent_run,
    update_agent_run_editor_version,
)
from .changes import create_change_from_agent_run, read_change
from .models import (
    AgentActivity,
    AgentRun,
    AgentRunBudget,
    AgentRunFailure,
    AgentRunPublic,
    ChangeRecord,
    EditorVersion,
    ToolResult,
)
from .providers.base import AgentProvider
from .run_audit import AgentAuditLog
from .session_conversation import SessionConversation
from .tools import ToolRegistry


RunUpdateListener = Callable[[AgentRunPublic], Awaitable[None]]
_MAX_PUBLIC_ACTIVITIES = 48
_MAX_PUBLIC_COMMENTARY_CHARS = 280
_PUBLIC_TOOL_NAMES = frozenset(
    {
        "inspect_diff",
        "validate_candidate",
        "lookup_samples",
        "inspect_sample_usage",
        "finalize_change",
        "request_user_input",
    }
)


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
        conversation: SessionConversation | None = None,
        audit_log: AgentAuditLog | None = None,
    ) -> None:
        self._tools = tools or ToolRegistry()
        self._on_update = on_update
        self._conversation = conversation or SessionConversation()
        self._audit_log = audit_log
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
        project_context: str | None = None,
    ) -> AgentRun:
        conversation_context = self._conversation.model_context()
        run = create_agent_run(
            intent=intent,
            editor_version=editor_version,
            apply_mode=apply_mode,
            budget=budget,
            provider=provider_name,
            model=model,
            project_context=project_context,
            conversation_context=conversation_context,
        )
        entry = _RunEntry(run=run)
        async with self._entries_lock:
            self._entries[run.id] = entry
        self._conversation.record_started(run)
        if self._audit_log:
            self._audit_log.record_started(run)
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
            entry.run = _append_completed_activity(
                resume_agent_run(entry.run, question_id=question_id, answer=answer),
                "user_input",
            )
            entry.revision += 1
            entry.cancel_requested = False
            entry.cancellation = AgentRunCancellation()
            resumed = entry.run.model_copy(deep=True)
            self._conversation.record_answer(run_id, question_id, answer)
            if self._audit_log:
                self._audit_log.record_answer(resumed, question_id, answer.strip())
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

        published: AgentRun | None = None
        async with entry.lock:
            updated = update_agent_run_editor_version(
                entry.run,
                base_hash=base_hash,
                editor_version=editor_version,
            )
            if updated == entry.run:
                return updated.model_copy(deep=True)
            if entry.active_turn_revision is not None:
                updated = _finish_active_provider_activities(updated, "cancelled")
            updated = _append_completed_activity(updated, "editor_update")
            entry.run = updated
            entry.revision += 1
            if updated.status == "running" and entry.active_turn_revision is not None:
                entry.cancellation.cancel()
            published = updated.model_copy(deep=True)
        await self._publish(published)
        return published

    async def reopen_completed(
        self,
        run_id: str,
        *,
        base_hash: str,
        editor_version: EditorVersion,
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
                raise AgentRuntimeTransitionError("Agent Run must reopen with its original provider and model")
            entry.run = _append_completed_activity(
                reopen_completed_agent_run(
                    entry.run,
                    base_hash=base_hash,
                    editor_version=editor_version,
                ),
                "editor_update",
            )
            entry.revision += 1
            entry.cancel_requested = False
            entry.cancellation = AgentRunCancellation()
            reopened = entry.run.model_copy(deep=True)
            self._create_worker(entry, provider, reopened, start_gate)

        try:
            await self._publish(reopened)
        finally:
            start_gate.set()
        return reopened

    async def acknowledge_stage(
        self,
        run_id: str,
        *,
        base_hash: str,
        editor_version: EditorVersion,
    ) -> ChangeRecord | None:
        entry = await self._entry(run_id)
        if not entry:
            return None

        async with entry.lock:
            run = entry.run
            if run.status != "completed" or not run.final_change:
                raise AgentRuntimeTransitionError("Only completed Agent Runs may be staged")
            if run.final_change.action != "apply":
                raise AgentRuntimeTransitionError("Only completed apply Agent Runs may be staged")
            if run.editor_version.hash != base_hash:
                raise AgentRuntimeTransitionError("Agent Run stage acknowledgement is stale")
            if run.final_change.code != editor_version.code:
                raise AgentRuntimeTransitionError("Agent Run stage acknowledgement does not match the final change")
            if _code_hash(editor_version.code) != editor_version.hash:
                raise AgentRuntimeTransitionError("Agent Run stage acknowledgement hash does not match its code")
            if run.staged_change_id:
                change = read_change(run.staged_change_id)
                if not change:
                    raise AgentRuntimeTransitionError("Persisted Agent Run change is unavailable")
                return change

            change = create_change_from_agent_run(run)
            entry.run = run.model_copy(update={"staged_change_id": change.id})
            self._conversation.record_staged_change(run_id, change.id)
            if self._audit_log:
                self._audit_log.record_staged_change(entry.run, change.id)
            return change

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
                entry.run = _finish_active_provider_activities(cancel_agent_run(entry.run), "cancelled")
                entry.cancel_requested = True
                task = entry.task
                published = entry.run.model_copy(deep=True)
            elif entry.run.status == "completed" and not entry.run.staged_change_id:
                entry.run = discard_unstaged_completed_agent_run(entry.run)
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
                    entry.run = _finish_active_provider_activities(cancel_agent_run(entry.run), "cancelled")
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
                    if entry.run.status != "running":
                        return
                    run = _begin_model_activity(entry.run)
                    entry.run = run
                    revision = entry.revision
                    cancellation = entry.cancellation
                    entry.active_turn_revision = revision

                await self._publish(run)

                async def report_commentary(commentary: str) -> None:
                    await self._record_commentary(entry, revision, cancellation, commentary)

                updated = await execute_model_turn(
                    run,
                    provider,
                    self._tools,
                    cancellation=cancellation,
                    on_commentary=report_commentary,
                )
                async with entry.lock:
                    if entry.active_turn_revision == revision:
                        entry.active_turn_revision = None
                    if entry.cancel_requested and entry.run.status == "running":
                        updated = _finish_active_provider_activities(cancel_agent_run(entry.run), "cancelled")
                    elif entry.revision != revision:
                        if entry.cancellation is cancellation:
                            entry.cancellation = AgentRunCancellation()
                        continue
                    else:
                        updated = updated.model_copy(
                            update={
                                "activities": [
                                    activity.model_copy(deep=True) for activity in entry.run.activities
                                ]
                            },
                            deep=True,
                        )
                        activity_status = "cancelled" if updated.status == "cancelled" else "completed"
                        updated = _finish_active_provider_activities(updated, activity_status)
                        updated = _append_tool_activities(
                            updated,
                            updated.tool_results[len(run.tool_results) :],
                        )
                    entry.run = updated
                await self._publish(updated)
                if updated.status != "running":
                    return
        except asyncio.CancelledError:
            entry.cancellation.cancel()
            cancelled: AgentRun | None = None
            async with entry.lock:
                if entry.run.status == "running":
                    entry.cancel_requested = True
                    entry.run = _finish_active_provider_activities(cancel_agent_run(entry.run), "cancelled")
                    cancelled = entry.run.model_copy(deep=True)
            if cancelled:
                await self._publish(cancelled)
        except Exception:
            failed: AgentRun | None = None
            async with entry.lock:
                if entry.run.status == "running":
                    entry.run = _finish_active_provider_activities(
                        fail_agent_run(
                            entry.run,
                            AgentRunFailure(
                                code="internal_error",
                                message="The agent run could not complete.",
                                retryable=False,
                            ),
                        ),
                        "completed",
                    )
                    failed = entry.run.model_copy(deep=True)
            if failed:
                await self._publish(failed)
        finally:
            async with entry.lock:
                if entry.task is asyncio.current_task():
                    entry.task = None
                    entry.active_turn_revision = None

    async def _record_commentary(
        self,
        entry: _RunEntry,
        revision: int,
        cancellation: AgentRunCancellation,
        commentary: str,
    ) -> None:
        published: AgentRun | None = None
        async with entry.lock:
            if (
                entry.run.status != "running"
                or entry.revision != revision
                or entry.active_turn_revision != revision
                or entry.cancellation is not cancellation
                or cancellation.is_cancelled
            ):
                return
            updated = _set_commentary(entry.run, commentary)
            if updated == entry.run:
                return
            entry.run = updated
            published = updated.model_copy(deep=True)
        await self._publish(published)

    async def _publish(self, run: AgentRun) -> None:
        self._conversation.record_state(run)
        if self._audit_log:
            self._audit_log.record_state(run)
        if not self._on_update:
            return
        try:
            await self._on_update(run.to_public())
        except Exception:
            return


def _code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _begin_model_activity(run: AgentRun) -> AgentRun:
    return _append_activity(
        run,
        AgentActivity(
            sequence=_next_activity_sequence(run),
            kind="model_turn",
            status="running",
            startedAt=_timestamp(),
            turn=run.usage.turns + 1,
        ),
    )


def _append_completed_activity(run: AgentRun, kind: str) -> AgentRun:
    timestamp = _timestamp()
    return _append_activity(
        run,
        AgentActivity(
            sequence=_next_activity_sequence(run),
            kind=kind,
            status="completed",
            startedAt=timestamp,
            completedAt=timestamp,
        ),
    )


def _append_tool_activities(run: AgentRun, results: list[ToolResult]) -> AgentRun:
    updated = run
    for result in results:
        timestamp = _timestamp()
        updated = _append_activity(
            updated,
            AgentActivity(
                sequence=_next_activity_sequence(updated),
                kind="tool",
                status="completed",
                startedAt=timestamp,
                completedAt=timestamp,
                tool=result.name if result.name in _PUBLIC_TOOL_NAMES else "agent_tool",
            ),
        )
    return updated


def _set_commentary(run: AgentRun, commentary: str) -> AgentRun:
    message = _normalize_public_commentary(commentary)
    if not message:
        return run
    activities = [activity.model_copy(deep=True) for activity in run.activities]
    for index in range(len(activities) - 1, -1, -1):
        activity = activities[index]
        if activity.kind != "commentary" or activity.status != "running":
            continue
        if message == activity.message:
            return run
        activities[index] = activity.model_copy(update={"message": message})
        return run.model_copy(update={"activities": activities}, deep=True)

    return _append_activity(
        run,
        AgentActivity(
            sequence=_next_activity_sequence(run),
            kind="commentary",
            status="running",
            startedAt=_timestamp(),
            message=message,
        ),
    )


def _finish_active_commentary_activity(run: AgentRun, status: str) -> AgentRun:
    activities = [activity.model_copy(deep=True) for activity in run.activities]
    for index in range(len(activities) - 1, -1, -1):
        activity = activities[index]
        if activity.kind == "commentary" and activity.status == "running":
            activities[index] = activity.model_copy(
                update={"status": status, "completed_at": _timestamp()},
            )
            return run.model_copy(update={"activities": activities}, deep=True)
    return run


def _finish_active_model_activity(run: AgentRun, status: str) -> AgentRun:
    activities = [activity.model_copy(deep=True) for activity in run.activities]
    for index in range(len(activities) - 1, -1, -1):
        activity = activities[index]
        if activity.kind == "model_turn" and activity.status == "running":
            activities[index] = activity.model_copy(
                update={"status": status, "completed_at": _timestamp()},
            )
            return run.model_copy(update={"activities": activities}, deep=True)
    return run


def _finish_active_provider_activities(run: AgentRun, status: str) -> AgentRun:
    return _finish_active_model_activity(_finish_active_commentary_activity(run, status), status)


def _append_activity(run: AgentRun, activity: AgentActivity) -> AgentRun:
    activities = [*(item.model_copy(deep=True) for item in run.activities), activity]
    return run.model_copy(update={"activities": activities[-_MAX_PUBLIC_ACTIVITIES:]}, deep=True)


def _next_activity_sequence(run: AgentRun) -> int:
    return run.activities[-1].sequence + 1 if run.activities else 1


def _timestamp() -> int:
    return int(time.time())


def _normalize_public_commentary(value: str) -> str:
    normalized = " ".join(value.replace("`", "").split())
    return normalized[:_MAX_PUBLIC_COMMENTARY_CHARS].strip()
