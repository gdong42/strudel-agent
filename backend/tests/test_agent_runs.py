from __future__ import annotations

import asyncio
import json

import pytest

from app.agent_runs import AgentRunManager
from app.config import AgentRuntimeConfig
from app.agent_runtime import AgentRuntimeTransitionError, build_run_budget
from app.models import AgentMessage, AgentRunPublic, EditorVersion, ModelTurnRequest, ModelTurnResult, ToolCall
from app.providers.base import AgentProvider, ProviderError
from tests.fakes import ScriptedAgentProvider


def run_budget():
    return build_run_budget(AgentRuntimeConfig(maxTurns=4, maxElapsedSeconds=20, maxTotalTokens=2_000))


async def start_run(manager: AgentRunManager, provider: AgentProvider):
    return await manager.start(
        intent="Make the drums more energetic.",
        editor_version=EditorVersion(code='s("bd")', hash="editor-hash"),
        apply_mode="manual",
        budget=run_budget(),
        provider_name="test-provider",
        model="test-model",
        provider=provider,
    )


@pytest.mark.anyio
async def test_manager_drives_multiple_turns_to_a_final_public_change() -> None:
    provider = ScriptedAgentProvider(
        [
            ModelTurnResult(
                assistantMessage=AgentMessage(
                    role="assistant",
                    toolCalls=[
                        ToolCall(
                            id="diff-1",
                            name="inspect_diff",
                            arguments={"baseCode": 's("bd")', "candidateCode": 's("bd*4")'},
                        )
                    ],
                )
            ),
            ModelTurnResult(
                assistantMessage=AgentMessage(
                    role="assistant",
                    toolCalls=[
                        ToolCall(
                            id="final-1",
                            name="finalize_change",
                            arguments={
                                "code": 's("bd*4")',
                                "explanation": "Added a four-on-the-floor kick.",
                                "action": "apply",
                                "warnings": [],
                            },
                        )
                    ],
                )
            ),
        ]
    )
    manager = AgentRunManager()

    started = await start_run(manager, provider)
    completed = await manager.wait(started.id)
    public = await manager.get_public(started.id)

    assert completed is not None
    assert completed.status == "completed"
    assert len(provider.requests) == 2
    assert public is not None
    assert public.status == "completed"
    assert public.final_change is not None
    assert public.final_change.code == 's("bd*4")'


@pytest.mark.anyio
async def test_manager_publishes_only_public_lifecycle_changes() -> None:
    updates: list[AgentRunPublic] = []

    async def record_update(update: AgentRunPublic) -> None:
        updates.append(update)

    provider = ScriptedAgentProvider(
        [
            ModelTurnResult(
                assistantMessage=AgentMessage(
                    role="assistant",
                    toolCalls=[
                        ToolCall(
                            id="diff-1",
                            name="inspect_diff",
                            arguments={"baseCode": 's("bd")', "candidateCode": 's("bd*4")'},
                        )
                    ],
                )
            ),
            ModelTurnResult(
                assistantMessage=AgentMessage(
                    role="assistant",
                    toolCalls=[
                        ToolCall(
                            id="final-1",
                            name="finalize_change",
                            arguments={
                                "code": 's("bd*4")',
                                "explanation": "Added a four-on-the-floor kick.",
                                "action": "apply",
                                "warnings": [],
                            },
                        )
                    ],
                )
            ),
        ]
    )
    manager = AgentRunManager(on_update=record_update)

    started = await start_run(manager, provider)
    await manager.wait(started.id)

    assert [update.status for update in updates] == ["running", "completed"]
    assert all(
        set(update.model_dump(by_alias=True)) == {"id", "status", "question", "finalChange", "error"}
        for update in updates
    )
    assert "inspect_diff" not in json.dumps([update.model_dump(by_alias=True) for update in updates])


@pytest.mark.anyio
async def test_manager_stops_for_input_and_projects_only_the_question() -> None:
    provider = ScriptedAgentProvider(
        [
            ModelTurnResult(
                assistantMessage=AgentMessage(
                    role="assistant",
                    toolCalls=[
                        ToolCall(
                            id="input-1",
                            name="request_user_input",
                            arguments={
                                "questionId": "tempo",
                                "question": "Keep the current tempo?",
                                "options": [{"id": "keep", "label": "Keep it"}],
                                "reason": "private ambiguity analysis",
                            },
                        )
                    ],
                )
            )
        ]
    )
    manager = AgentRunManager()

    started = await start_run(manager, provider)
    paused = await manager.wait(started.id)
    public = await manager.get_public(started.id)

    assert paused is not None
    assert paused.status == "needs_input"
    assert public is not None
    assert public.question is not None
    assert public.question.question == "Keep the current tempo?"
    assert "private ambiguity analysis" not in json.dumps(public.model_dump(by_alias=True))


@pytest.mark.anyio
async def test_manager_resumes_a_paused_run_with_the_latest_editor_context() -> None:
    updates: list[AgentRunPublic] = []

    async def record_update(update: AgentRunPublic) -> None:
        updates.append(update)

    provider = ScriptedAgentProvider(
        [
            ModelTurnResult(
                assistantMessage=AgentMessage(
                    role="assistant",
                    toolCalls=[
                        ToolCall(
                            id="input-1",
                            name="request_user_input",
                            arguments={
                                "questionId": "tempo",
                                "question": "Keep the current tempo?",
                                "options": [],
                                "reason": "private ambiguity analysis",
                            },
                        )
                    ],
                )
            ),
            ModelTurnResult(
                assistantMessage=AgentMessage(
                    role="assistant",
                    toolCalls=[
                        ToolCall(
                            id="final-1",
                            name="finalize_change",
                            arguments={
                                "code": 's("bd*4")',
                                "explanation": "Added a four-on-the-floor kick.",
                                "action": "apply",
                                "warnings": [],
                            },
                        )
                    ],
                )
            ),
        ]
    )
    manager = AgentRunManager(on_update=record_update)

    started = await start_run(manager, provider)
    paused = await manager.wait(started.id)
    assert paused is not None
    assert paused.status == "needs_input"

    updated = await manager.update_editor(
        started.id,
        base_hash="editor-hash",
        editor_version=EditorVersion(code='s("bd*4")', hash="latest-hash"),
    )
    assert updated is not None
    assert updated.status == "needs_input"

    with pytest.raises(AgentRuntimeTransitionError, match="original provider"):
        await manager.resume(
            started.id,
            question_id="tempo",
            answer="Keep it at 124.",
            provider_name="other-provider",
            model="test-model",
            provider=provider,
        )

    resumed = await manager.resume(
        started.id,
        question_id="tempo",
        answer="Keep it at 124.",
        provider_name="test-provider",
        model="test-model",
        provider=provider,
    )
    completed = await manager.wait(started.id)

    assert resumed is not None
    assert resumed.status == "running"
    assert completed is not None
    assert completed.status == "completed"
    assert [update.status for update in updates] == ["running", "needs_input", "running", "completed"]
    assert json.loads(provider.requests[-1].messages[-1].content) == {
        "userInput": {"questionId": "tempo", "answer": "Keep it at 124."},
        "editorVersion": {"code": 's("bd*4")', "hash": "latest-hash"},
    }


@pytest.mark.anyio
async def test_manager_restarts_an_active_turn_after_an_editor_update() -> None:
    class SupersededTurnProvider:
        def __init__(self) -> None:
            self.requests: list[ModelTurnRequest] = []
            self.first_turn_started = asyncio.Event()
            self.first_turn_cancelled = False

        async def next_turn(self, request: ModelTurnRequest) -> ModelTurnResult:
            self.requests.append(request.model_copy(deep=True))
            if len(self.requests) == 1:
                self.first_turn_started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.first_turn_cancelled = True
                    raise
            return ModelTurnResult(
                assistantMessage=AgentMessage(
                    role="assistant",
                    toolCalls=[
                        ToolCall(
                            id="final-1",
                            name="finalize_change",
                            arguments={
                                "code": 's("hh")',
                                "explanation": "Applied the latest editor context.",
                                "action": "apply",
                                "warnings": [],
                            },
                        )
                    ],
                )
            )

        async def test_connection(self) -> None:
            return None

    provider = SupersededTurnProvider()
    manager = AgentRunManager()

    started = await start_run(manager, provider)
    await provider.first_turn_started.wait()
    updated = await manager.update_editor(
        started.id,
        base_hash="editor-hash",
        editor_version=EditorVersion(code='s("hh")', hash="latest-hash"),
    )
    completed = await manager.wait(started.id)

    assert updated is not None
    assert updated.status == "running"
    assert completed is not None
    assert completed.status == "completed"
    assert provider.first_turn_cancelled is True
    assert len(provider.requests) == 2
    assert json.loads(provider.requests[-1].messages[-1].content) == {
        "editorUpdate": {
            "baseHash": "editor-hash",
            "editorVersion": {"code": 's("hh")', "hash": "latest-hash"},
        }
    }


@pytest.mark.anyio
async def test_manager_publishes_one_cancelled_update_for_a_paused_run() -> None:
    updates: list[AgentRunPublic] = []

    async def record_update(update: AgentRunPublic) -> None:
        updates.append(update)

    provider = ScriptedAgentProvider(
        [
            ModelTurnResult(
                assistantMessage=AgentMessage(
                    role="assistant",
                    toolCalls=[
                        ToolCall(
                            id="input-1",
                            name="request_user_input",
                            arguments={
                                "questionId": "tempo",
                                "question": "Keep the current tempo?",
                                "options": [],
                                "reason": "private ambiguity analysis",
                            },
                        )
                    ],
                )
            )
        ]
    )
    manager = AgentRunManager(on_update=record_update)

    started = await start_run(manager, provider)
    await manager.wait(started.id)
    cancelled = await manager.cancel(started.id)

    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert [update.status for update in updates] == ["running", "needs_input", "cancelled"]


@pytest.mark.anyio
async def test_manager_cancels_an_active_provider_task() -> None:
    class BlockingProvider:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.cancelled = False

        async def next_turn(self, request: ModelTurnRequest) -> ModelTurnResult:
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            raise AssertionError("Blocking provider unexpectedly completed")

        async def test_connection(self) -> None:
            return None

    provider = BlockingProvider()
    manager = AgentRunManager()

    started = await start_run(manager, provider)
    await provider.started.wait()
    cancelled = await manager.cancel(started.id)

    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert provider.cancelled is True


@pytest.mark.anyio
async def test_manager_sanitizes_provider_failures_and_keeps_terminal_state_readable() -> None:
    manager = AgentRunManager()
    started = await start_run(manager, ScriptedAgentProvider([ProviderError("api-key=secret", retryable=True)]))

    failed = await manager.wait(started.id)
    public = await manager.get_public(started.id)

    assert failed is not None
    assert failed.status == "failed"
    assert public is not None
    assert public.error is not None
    assert public.error.code == "provider_error"
    assert "secret" not in json.dumps(public.model_dump(by_alias=True))
