from __future__ import annotations

import asyncio
import json
import logging

import pytest

from app.agent_runtime import (
    AgentRunCancellation,
    AgentRuntimeTransitionError,
    append_model_turn,
    append_tool_results,
    build_run_budget,
    cancel_agent_run,
    create_agent_run,
    execute_model_turn,
    reopen_completed_agent_run,
    resume_agent_run,
    update_agent_run_editor_version,
)
from app.config import AgentRuntimeConfig
from app.models import (
    AgentFinalChange,
    AgentMessage,
    AgentRun,
    AgentRunUsage,
    EditorVersion,
    ModelTurnRequest,
    ModelTurnResult,
    ToolCall,
    ToolResult,
)
from app.providers.base import ProviderError
from app.tools import ToolRegistry
from tests.fakes import ScriptedAgentProvider


RUNTIME_LOGGER = "uvicorn.error.strudel_agent.runtime"


def make_run() -> AgentRun:
    return create_agent_run(
        intent="  make the drums more energetic  ",
        editor_version=EditorVersion(code='s("bd")', hash="editor-hash"),
        apply_mode="manual",
        budget=build_run_budget(
            AgentRuntimeConfig(
                maxTurns=3,
                maxElapsedSeconds=20,
                maxTotalTokens=1000,
                maxOutputTokensPerTurn=400,
            )
        ),
        provider="mock",
        model="mock-model",
        now=100,
        run_id="run-1",
    )


def make_paused_run() -> AgentRun:
    payload = make_run().model_dump(by_alias=True)
    payload.update(
        {
            "status": "needs_input",
            "pendingInput": {
                "questionId": "tempo",
                "question": "Keep the current tempo?",
                "options": [],
                "reason": "private ambiguity analysis",
            },
        }
    )
    return AgentRun.model_validate(payload)


class BlockingAgentProvider:
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


def test_create_agent_run_initializes_private_context_and_budget() -> None:
    run = make_run()

    assert run.status == "running"
    assert run.intent == "make the drums more energetic"
    assert run.budget.max_turns == 3
    assert run.created_at == run.updated_at == 100
    assert [message.role for message in run.messages] == ["system", "user"]
    assert json.loads(run.messages[1].content) == {
        "intent": "make the drums more energetic",
        "editorVersion": {"code": 's("bd")', "hash": "editor-hash"},
    }


def test_create_agent_run_accepts_an_empty_editor_as_a_blank_project() -> None:
    run = create_agent_run(
        intent="Start a minimal house beat.",
        editor_version=EditorVersion(code="", hash="empty-hash"),
        apply_mode="manual",
        budget=build_run_budget(AgentRuntimeConfig()),
        provider="mock",
        model="mock-model",
        now=100,
        run_id="blank-run",
    )

    assert run.editor_version.code == ""
    assert json.loads(run.messages[1].content)["editorVersion"] == {
        "code": "",
        "hash": "empty-hash",
    }


def test_create_agent_run_keeps_project_context_in_the_private_system_message() -> None:
    run = create_agent_run(
        intent="make the drums more energetic",
        editor_version=EditorVersion(code='s("bd")', hash="editor-hash"),
        apply_mode="manual",
        budget=build_run_budget(AgentRuntimeConfig(maxTurns=3, maxElapsedSeconds=20, maxTotalTokens=1000)),
        provider="mock",
        model="mock-model",
        project_context="# Set\n\n- Keep the bass stable.",
        now=100,
        run_id="run-with-context",
    )

    assert "Keep the bass stable." in run.messages[0].content
    assert "Keep the bass stable." not in run.to_public().model_dump_json()


def test_create_agent_run_includes_prior_conversation_only_in_its_initial_private_input() -> None:
    prior_context = [
        {
            "runId": "run-previous",
            "intent": "Make the drums more energetic.",
            "clarifications": [],
            "outcome": {"status": "completed", "action": "apply", "explanation": "Added a kick."},
        }
    ]
    run = create_agent_run(
        intent="Add a hi-hat pattern.",
        editor_version=EditorVersion(code='s("bd")', hash="editor-hash"),
        apply_mode="manual",
        budget=build_run_budget(AgentRuntimeConfig(maxTurns=3, maxElapsedSeconds=20, maxTotalTokens=1000)),
        provider="mock",
        model="mock-model",
        conversation_context=prior_context,
        now=100,
        run_id="run-with-conversation",
    )

    assert json.loads(run.messages[1].content) == {
        "intent": "Add a hi-hat pattern.",
        "editorVersion": {"code": 's("bd")', "hash": "editor-hash"},
        "conversationContext": prior_context,
    }
    assert "conversationContext" in run.messages[0].content


def test_append_model_turn_rebuilds_the_run_and_tracks_usage() -> None:
    original = make_run()
    updated = append_model_turn(
        original,
        ModelTurnResult(
            assistantMessage=AgentMessage(
                role="assistant",
                content="I will inspect the candidate.",
                toolCalls=[ToolCall(id="call-1", name="inspect_diff")],
            ),
            usage={"inputTokens": 120, "outputTokens": 30},
        ),
        now=125,
    )

    assert len(original.messages) == 2
    assert updated.messages[-1].tool_calls[0].name == "inspect_diff"
    assert updated.usage.turns == 1
    assert updated.usage.input_tokens == 120
    assert updated.usage.output_tokens == 30
    assert updated.usage.total_tokens == 150
    assert updated.updated_at == 125


def test_append_tool_results_returns_internal_tool_messages() -> None:
    run = make_run()
    updated = append_tool_results(
        run,
        [
            ToolResult(
                callId="call-1",
                name="validate_candidate",
                status="recoverable_error",
                output={"valid": False, "candidate": 's("private")'},
            )
        ],
        now=110,
    )

    assert run.tool_results == []
    assert updated.tool_results[0].status == "recoverable_error"
    assert updated.messages[-1].role == "tool"
    assert updated.messages[-1].tool_call_id == "call-1"
    assert json.loads(updated.messages[-1].content) == {
        "name": "validate_candidate",
        "status": "recoverable_error",
        "output": {"valid": False, "candidate": 's("private")'},
    }


def test_runtime_transitions_reject_terminal_runs_and_backward_time() -> None:
    run = make_run()
    completed_payload = run.model_dump(by_alias=True)
    completed_payload.update(
        {
            "status": "completed",
            "finalChange": AgentFinalChange(
                code='s("bd*4")',
                explanation="Added a kick.",
                action="apply",
            ).model_dump(by_alias=True),
        }
    )
    completed = AgentRun.model_validate(completed_payload)

    with pytest.raises(AgentRuntimeTransitionError, match="Only running"):
        append_model_turn(completed, ModelTurnResult(assistantMessage=AgentMessage(role="assistant")), now=101)
    with pytest.raises(AgentRuntimeTransitionError, match="cannot move backwards"):
        append_tool_results(run, [], now=99)


def test_cancel_agent_run_clears_a_pending_question_without_exposing_private_reason() -> None:
    paused = make_paused_run()

    cancelled = cancel_agent_run(paused, now=110)

    assert cancelled.status == "cancelled"
    assert cancelled.pending_input is None
    assert cancelled.to_public().question is None


def test_resume_agent_run_appends_the_answer_and_latest_editor_version() -> None:
    paused = make_paused_run()

    resumed = resume_agent_run(paused, question_id="tempo", answer="  Keep it at 124.  ", now=110)

    assert paused.status == "needs_input"
    assert resumed.status == "running"
    assert resumed.pending_input is None
    assert json.loads(resumed.messages[-1].content) == {
        "userInput": {"questionId": "tempo", "answer": "Keep it at 124."},
        "editorVersion": {"code": 's("bd")', "hash": "editor-hash"},
    }

    with pytest.raises(AgentRuntimeTransitionError, match="does not match"):
        resume_agent_run(paused, question_id="wrong", answer="Keep it at 124.", now=110)


def test_editor_update_requires_the_latest_hash_and_appends_private_context() -> None:
    run = make_run()
    next_version = EditorVersion(code='s("bd*4")', hash="next-hash")

    updated = update_agent_run_editor_version(
        run,
        base_hash="editor-hash",
        editor_version=next_version,
        now=110,
    )

    assert run.editor_version.code == 's("bd")'
    assert updated.editor_version == next_version
    assert json.loads(updated.messages[-1].content) == {
        "editorUpdate": {
            "baseHash": "editor-hash",
            "editorVersion": {"code": 's("bd*4")', "hash": "next-hash"},
        }
    }

    cleared = update_agent_run_editor_version(
        run,
        base_hash="editor-hash",
        editor_version=EditorVersion(code="", hash="empty-hash"),
        now=110,
    )
    assert cleared.editor_version.code == ""
    assert json.loads(cleared.messages[-1].content)["editorUpdate"]["editorVersion"] == {
        "code": "",
        "hash": "empty-hash",
    }

    with pytest.raises(AgentRuntimeTransitionError, match="stale"):
        update_agent_run_editor_version(
            updated,
            base_hash="editor-hash",
            editor_version=EditorVersion(code='s("hh")', hash="another-hash"),
            now=120,
        )

    with pytest.raises(AgentRuntimeTransitionError, match="reuses a hash"):
        update_agent_run_editor_version(
            run,
            base_hash="editor-hash",
            editor_version=EditorVersion(code='s("hh")', hash="editor-hash"),
            now=120,
        )


def test_completed_agent_run_can_reopen_against_an_empty_editor() -> None:
    run = make_run()
    payload = run.model_dump(by_alias=True)
    payload.update(
        {
            "status": "completed",
            "finalChange": {
                "code": 's("bd*4")',
                "explanation": "Added a kick.",
                "action": "apply",
                "warnings": [],
            },
        }
    )
    completed = AgentRun.model_validate(payload)

    reopened = reopen_completed_agent_run(
        completed,
        base_hash="editor-hash",
        editor_version=EditorVersion(code="", hash="empty-hash"),
        now=110,
    )

    assert reopened.status == "running"
    assert reopened.editor_version.code == ""
    assert reopened.final_change is None


@pytest.mark.anyio
async def test_execute_model_turn_honors_a_pre_cancelled_control_without_calling_the_provider() -> None:
    cancellation = AgentRunCancellation()
    cancellation.cancel()
    provider = ScriptedAgentProvider([ModelTurnResult(assistantMessage=AgentMessage(role="assistant", content="unused"))])

    cancelled = await execute_model_turn(
        make_run(),
        provider,
        ToolRegistry(),
        now=110,
        cancellation=cancellation,
    )

    assert cancelled.status == "cancelled"
    assert provider.requests == []


@pytest.mark.anyio
async def test_execute_model_turn_cancels_active_provider_work() -> None:
    cancellation = AgentRunCancellation()
    provider = BlockingAgentProvider()
    task = asyncio.create_task(execute_model_turn(make_run(), provider, ToolRegistry(), now=110, cancellation=cancellation))

    await provider.started.wait()
    cancellation.cancel()
    cancelled = await task

    assert cancelled.status == "cancelled"
    assert cancelled.final_change is None
    assert provider.cancelled is True


@pytest.mark.anyio
async def test_execute_model_turn_prefers_cancellation_over_a_concurrent_final_result() -> None:
    cancellation = AgentRunCancellation()

    class ConcurrentCancellationProvider:
        async def next_turn(self, request: ModelTurnRequest) -> ModelTurnResult:
            cancellation.cancel()
            return ModelTurnResult(
                assistantMessage=AgentMessage(
                    role="assistant",
                    toolCalls=[
                        ToolCall(
                            id="final-1",
                            name="finalize_change",
                            arguments={
                                "code": 's("bd*4")',
                                "explanation": "Should not be finalized.",
                                "action": "apply",
                                "warnings": [],
                            },
                        )
                    ],
                )
            )

    cancelled = await execute_model_turn(
        make_run(),
        ConcurrentCancellationProvider(),
        ToolRegistry(),
        now=110,
        cancellation=cancellation,
    )

    assert cancelled.status == "cancelled"
    assert cancelled.final_change is None
    assert cancelled.tool_results == []


@pytest.mark.anyio
async def test_execute_model_turn_cleans_up_provider_work_when_its_owner_is_cancelled() -> None:
    provider = BlockingAgentProvider()
    task = asyncio.create_task(
        execute_model_turn(make_run(), provider, ToolRegistry(), now=110, cancellation=AgentRunCancellation())
    )

    await provider.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert provider.cancelled is True


@pytest.mark.anyio
async def test_scripted_provider_returns_turns_and_records_request_copies() -> None:
    provider = ScriptedAgentProvider(
        [ModelTurnResult(assistantMessage=AgentMessage(role="assistant", content="Use inspect_diff."))]
    )
    request = ModelTurnRequest(
        messages=[AgentMessage(role="user", content="Make it punchier.")],
        tools=[],
        model="test-model",
        maxOutputTokens=500,
    )

    result = await provider.next_turn(request)
    request.messages[0].content = "mutated"

    assert result.assistant_message.content == "Use inspect_diff."
    assert provider.requests[0].messages[0].content == "Make it punchier."
    with pytest.raises(ProviderError, match="no remaining response"):
        await provider.next_turn(request)


@pytest.mark.anyio
async def test_execute_model_turn_runs_tools_in_provider_order_and_returns_internal_messages() -> None:
    run = make_run()
    provider = ScriptedAgentProvider(
        [
            ModelTurnResult(
                assistantMessage=AgentMessage(
                    role="assistant",
                    content="I will inspect and validate this candidate.",
                    toolCalls=[
                        ToolCall(
                            id="diff-1",
                            name="inspect_diff",
                            arguments={"baseCode": 's("bd")', "candidateCode": 's("bd*4")'},
                        ),
                        ToolCall(
                            id="validate-1",
                            name="validate_candidate",
                            arguments={"candidateCode": 's("bd*4")'},
                        ),
                    ],
                ),
                usage={"inputTokens": 100, "outputTokens": 25},
            )
        ]
    )

    updated = await execute_model_turn(run, provider, ToolRegistry(), now=110)

    assert [tool.name for tool in provider.requests[0].tools] == [
        "inspect_diff",
        "validate_candidate",
        "lookup_strudel_docs",
        "lookup_samples",
        "inspect_sample_usage",
        "finalize_change",
        "request_user_input",
    ]
    assert provider.requests[0].max_output_tokens == 400
    assert [message.role for message in updated.messages] == ["system", "user", "assistant", "tool", "tool"]
    assert [result.name for result in updated.tool_results] == ["inspect_diff", "validate_candidate"]
    assert [result.call_id for result in updated.tool_results] == ["diff-1", "validate-1"]
    assert updated.tool_results[0].output["changed"] is True
    assert updated.tool_results[1].output["valid"] is True
    assert updated.usage.turns == 1
    assert updated.usage.input_tokens == 100
    assert updated.usage.output_tokens == 25
    assert updated.usage.total_tokens == 125


@pytest.mark.anyio
async def test_execute_model_turn_logs_safe_provider_lifecycle(caplog: pytest.LogCaptureFixture) -> None:
    provider = ScriptedAgentProvider(
        [
            ModelTurnResult(
                assistantMessage=AgentMessage(role="assistant", content="private model output"),
                usage={"inputTokens": 12, "outputTokens": 3},
                providerRequestId="provider-request-1",
            )
        ]
    )

    with caplog.at_level(logging.INFO, logger=RUNTIME_LOGGER):
        await execute_model_turn(make_run(), provider, ToolRegistry(), now=110)

    assert (
        "Agent provider turn started run_id=run-1 provider=mock model=mock-model turn=1 "
        "max_output_tokens=400"
    ) in caplog.text
    assert (
        "Agent provider turn completed run_id=run-1 provider=mock model=mock-model turn=1 "
        "provider_request_id=provider-request-1 input_tokens=12 output_tokens=3"
    ) in caplog.text
    assert "private model output" not in caplog.text
    assert 's("bd")' not in caplog.text


@pytest.mark.anyio
async def test_execute_model_turn_allows_unlimited_cumulative_tokens_with_a_per_turn_cap() -> None:
    budget = build_run_budget(
        AgentRuntimeConfig(
            maxTurns=3,
            maxElapsedSeconds=20,
            maxTotalTokens=None,
            maxOutputTokensPerTurn=65_536,
        )
    )
    run = make_run().model_copy(
        update={"budget": budget, "usage": AgentRunUsage(totalTokens=10_000_000)}
    )
    provider = ScriptedAgentProvider(
        [ModelTurnResult(assistantMessage=AgentMessage(role="assistant", content="Continue."))]
    )

    updated = await execute_model_turn(run, provider, ToolRegistry(), now=110)

    assert updated.status == "running"
    assert provider.requests[0].max_output_tokens == 65_536


@pytest.mark.anyio
async def test_execute_model_turn_preserves_plain_text_and_appends_runtime_feedback() -> None:
    run = make_run()
    provider = ScriptedAgentProvider(
        [ModelTurnResult(assistantMessage=AgentMessage(role="assistant", content="I need to think again."))]
    )

    updated = await execute_model_turn(run, provider, ToolRegistry(), now=110)

    assert updated.messages[-2].content == "I need to think again."
    assert json.loads(updated.messages[-1].content)["runtimeFeedback"] == (
        "The previous response did not request a tool. Continue by calling an available tool."
    )
    assert updated.tool_results == []


@pytest.mark.anyio
async def test_execute_model_turn_returns_unknown_tool_as_a_private_fatal_result() -> None:
    run = make_run()
    provider = ScriptedAgentProvider(
        [
            ModelTurnResult(
                assistantMessage=AgentMessage(
                    role="assistant",
                    toolCalls=[ToolCall(id="bad-1", name="not_registered")],
                )
            )
        ]
    )

    updated = await execute_model_turn(run, provider, ToolRegistry(), now=110)

    assert updated.status == "running"
    assert updated.tool_results[0].status == "fatal_error"
    assert updated.tool_results[0].output["error"]["code"] == "unknown_tool"


@pytest.mark.anyio
async def test_execute_model_turn_sanitizes_provider_failures(caplog: pytest.LogCaptureFixture) -> None:
    provider = ScriptedAgentProvider([ProviderError("provider unavailable: api-key=secret", retryable=True)])

    with caplog.at_level(logging.WARNING, logger=RUNTIME_LOGGER):
        failed = await execute_model_turn(make_run(), provider, ToolRegistry(), now=110)

    assert failed.status == "failed"
    assert failed.failure is not None
    assert failed.failure.code == "provider_error"
    assert failed.failure.message == "The model provider could not complete this run."
    assert failed.failure.retryable is True
    assert "secret" not in json.dumps(failed.to_public().model_dump(by_alias=True))
    assert "run_id=run-1 provider=mock model=mock-model turn=1 retryable=True" in caplog.text
    assert "provider unavailable: api-key=[REDACTED]" in caplog.text
    assert "secret" not in caplog.text


@pytest.mark.anyio
async def test_execute_model_turn_sanitizes_unexpected_provider_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = ScriptedAgentProvider([RuntimeError("private provider detail")])

    with caplog.at_level(logging.ERROR, logger=RUNTIME_LOGGER):
        failed = await execute_model_turn(make_run(), provider, ToolRegistry(), now=110)

    assert failed.status == "failed"
    assert failed.failure is not None
    assert failed.failure.code == "internal_error"
    assert failed.failure.message == "The agent run could not complete."
    assert failed.failure.retryable is False
    assert "private provider detail" not in json.dumps(failed.to_public().model_dump(by_alias=True))
    assert "exception=RuntimeError duration_ms=" in caplog.text
    assert "detail=private provider detail" in caplog.text


@pytest.mark.anyio
async def test_execute_model_turn_sanitizes_malformed_provider_results(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class MalformedResultProvider:
        async def next_turn(self, request: ModelTurnRequest) -> object:
            return {"unexpected": "private provider detail"}

    with caplog.at_level(logging.ERROR, logger=RUNTIME_LOGGER):
        failed = await execute_model_turn(make_run(), MalformedResultProvider(), ToolRegistry(), now=110)

    assert failed.status == "failed"
    assert failed.failure is not None
    assert failed.failure.code == "provider_error"
    assert failed.failure.retryable is False
    assert "private provider detail" not in json.dumps(failed.to_public().model_dump(by_alias=True))
    assert "run_id=run-1 provider=mock model=mock-model result_type=dict" in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("usage", "now", "message"),
    [
        (AgentRunUsage(turns=3), 110, "The agent run reached its turn limit."),
        (AgentRunUsage(), 20_100, "The agent run exceeded its active time limit."),
        (AgentRunUsage(totalTokens=1000), 110, "The agent run exhausted its token budget."),
    ],
)
async def test_execute_model_turn_fails_before_calling_provider_when_a_budget_is_exhausted(
    usage: AgentRunUsage,
    now: int,
    message: str,
) -> None:
    provider = ScriptedAgentProvider([ModelTurnResult(assistantMessage=AgentMessage(role="assistant", content="unused"))])
    run = make_run().model_copy(update={"usage": usage})

    failed = await execute_model_turn(run, provider, ToolRegistry(), now=now)

    assert failed.status == "failed"
    assert failed.failure is not None
    assert failed.failure.code == "budget_exhausted"
    assert failed.failure.message == message
    assert provider.requests == []


@pytest.mark.anyio
async def test_execute_model_turn_fails_when_a_returned_turn_exceeds_the_token_budget() -> None:
    provider = ScriptedAgentProvider(
        [
            ModelTurnResult(
                assistantMessage=AgentMessage(
                    role="assistant",
                    toolCalls=[
                        ToolCall(
                            id="final-1",
                            name="finalize_change",
                            arguments={
                                "code": 's("private")',
                                "explanation": "private candidate code",
                                "action": "apply",
                                "warnings": [],
                            },
                        )
                    ],
                ),
                usage={"inputTokens": 800, "outputTokens": 201},
            )
        ]
    )

    failed = await execute_model_turn(make_run(), provider, ToolRegistry(), now=110)

    assert failed.status == "failed"
    assert failed.failure is not None
    assert failed.failure.code == "budget_exhausted"
    assert failed.usage.turns == 1
    assert failed.usage.total_tokens == 1001
    assert failed.tool_results == []
    assert failed.final_change is None
    assert 's("private")' not in json.dumps(failed.to_public().model_dump(by_alias=True))


@pytest.mark.anyio
async def test_execute_model_turn_fails_when_a_provider_result_arrives_after_the_time_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamps = iter([101, 20_100])
    monkeypatch.setattr(
        "app.agent_runtime._timestamp",
        lambda now: now if now is not None else next(timestamps),
    )
    provider = ScriptedAgentProvider([ModelTurnResult(assistantMessage=AgentMessage(role="assistant", content="too late"))])

    failed = await execute_model_turn(make_run(), provider, ToolRegistry())

    assert failed.status == "failed"
    assert failed.failure is not None
    assert failed.failure.code == "budget_exhausted"
    assert failed.failure.message == "The agent run exceeded its active time limit."
    assert failed.usage.elapsed_seconds == 20


@pytest.mark.anyio
async def test_execute_model_turn_cancels_a_provider_at_the_active_time_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamps = iter([100, 110])
    monkeypatch.setattr(
        "app.agent_runtime._timestamp",
        lambda now: now if now is not None else next(timestamps),
    )
    provider = BlockingAgentProvider()
    run = make_run().model_copy(
        update={
            "budget": make_run().budget.model_copy(update={"max_elapsed_seconds": 1}),
            "active_elapsed_milliseconds": 990,
        }
    )

    failed = await execute_model_turn(run, provider, ToolRegistry())

    assert failed.status == "failed"
    assert failed.failure is not None
    assert failed.failure.code == "budget_exhausted"
    assert failed.failure.message == "The agent run exceeded its active time limit."
    assert failed.usage.elapsed_seconds == 1
    assert provider.cancelled is True


@pytest.mark.anyio
async def test_agent_run_time_budget_excludes_time_waiting_for_user_input() -> None:
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
                                "question": "Should the tempo stay at 124 BPM?",
                                "options": [{"id": "keep", "label": "Keep 124 BPM"}],
                                "reason": "The requested tempo is ambiguous.",
                            },
                        )
                    ],
                )
            )
        ]
    )

    paused = await execute_model_turn(make_run(), provider, ToolRegistry(), now=5_100)
    resumed = resume_agent_run(paused, question_id="tempo", answer="Keep it.", now=65_100)
    updated = append_tool_results(resumed, [], now=70_100)

    assert paused.status == "needs_input"
    assert paused.usage.elapsed_seconds == 5
    assert paused.active_started_at is None
    assert resumed.usage.elapsed_seconds == 5
    assert resumed.active_started_at == 65_100
    assert updated.usage.elapsed_seconds == 10


@pytest.mark.anyio
async def test_execute_model_turn_completes_only_after_a_valid_finalization_request() -> None:
    provider = ScriptedAgentProvider(
        [
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
            )
        ]
    )

    completed = await execute_model_turn(make_run(), provider, ToolRegistry(), now=110)

    assert completed.status == "completed"
    assert completed.final_change is not None
    assert completed.final_change.code == 's("bd*4")'
    assert completed.to_public().final_change is not None


@pytest.mark.anyio
async def test_execute_model_turn_returns_invalid_finalization_to_the_run() -> None:
    provider = ScriptedAgentProvider(
        [
            ModelTurnResult(
                assistantMessage=AgentMessage(
                    role="assistant",
                    toolCalls=[
                        ToolCall(
                            id="final-1",
                            name="finalize_change",
                            arguments={
                                "code": 'eval("bad")',
                                "explanation": "Unsafe change.",
                                "action": "apply",
                                "warnings": [],
                            },
                        )
                    ],
                )
            )
        ]
    )

    updated = await execute_model_turn(make_run(), provider, ToolRegistry(), now=110)

    assert updated.status == "running"
    assert updated.final_change is None
    assert updated.tool_results[-1].status == "recoverable_error"
    assert updated.tool_results[-1].output["error"]["code"] == "candidate_validation_failed"
    assert updated.tool_results[-1].output["validation"]["valid"] is False


@pytest.mark.anyio
async def test_execute_model_turn_rejects_noop_that_changes_editor_code() -> None:
    provider = ScriptedAgentProvider(
        [
            ModelTurnResult(
                assistantMessage=AgentMessage(
                    role="assistant",
                    toolCalls=[
                        ToolCall(
                            id="final-1",
                            name="finalize_change",
                            arguments={
                                "code": 's("hh")',
                                "explanation": "Nothing changed.",
                                "action": "noop",
                                "warnings": [],
                            },
                        )
                    ],
                )
            )
        ]
    )

    updated = await execute_model_turn(make_run(), provider, ToolRegistry(), now=110)

    assert updated.status == "running"
    assert updated.tool_results[-1].output["error"]["code"] == "noop_changed_code"


@pytest.mark.anyio
async def test_execute_model_turn_pauses_only_for_a_valid_input_request() -> None:
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
                                "question": "Should the tempo stay at 124 BPM?",
                                "options": [{"id": "keep", "label": "Keep 124 BPM"}],
                                "reason": "The arrangement conflicts with a tempo change.",
                            },
                        )
                    ],
                )
            )
        ]
    )

    paused = await execute_model_turn(make_run(), provider, ToolRegistry(), now=110)

    assert paused.status == "needs_input"
    assert paused.pending_input is not None
    assert paused.pending_input.reason == "The arrangement conflicts with a tempo change."
    assert paused.to_public().question is not None
    assert paused.to_public().question.question == "Should the tempo stay at 124 BPM?"


@pytest.mark.anyio
async def test_execute_model_turn_returns_plain_text_and_terminal_conflicts_to_the_run() -> None:
    plain_text_provider = ScriptedAgentProvider(
        [ModelTurnResult(assistantMessage=AgentMessage(role="assistant", content="Done."))]
    )
    plain_text = await execute_model_turn(make_run(), plain_text_provider, ToolRegistry(), now=110)

    assert plain_text.status == "running"
    assert json.loads(plain_text.messages[-1].content)["runtimeFeedback"] == (
        "The previous response did not request a tool. Continue by calling an available tool."
    )

    conflict_provider = ScriptedAgentProvider(
        [
            ModelTurnResult(
                assistantMessage=AgentMessage(
                    role="assistant",
                    toolCalls=[
                        ToolCall(id="diff-1", name="inspect_diff", arguments={"baseCode": "a", "candidateCode": "b"}),
                        ToolCall(
                            id="final-1",
                            name="finalize_change",
                            arguments={
                                "code": 's("bd")',
                                "explanation": "Done.",
                                "action": "apply",
                                "warnings": [],
                            },
                        ),
                    ],
                )
            )
        ]
    )
    conflict = await execute_model_turn(make_run(), conflict_provider, ToolRegistry(), now=110)

    assert conflict.status == "running"
    assert [result.output["error"]["code"] for result in conflict.tool_results] == [
        "terminal_tool_conflict",
        "terminal_tool_conflict",
    ]
