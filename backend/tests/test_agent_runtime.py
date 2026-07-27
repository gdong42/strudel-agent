from __future__ import annotations

import json

import pytest

from app.agent_runtime import (
    AgentRuntimeTransitionError,
    append_model_turn,
    append_tool_results,
    build_run_budget,
    create_agent_run,
    execute_model_turn,
)
from app.config import AgentRuntimeConfig
from app.models import (
    AgentFinalChange,
    AgentMessage,
    AgentRun,
    EditorVersion,
    ModelTurnRequest,
    ModelTurnResult,
    ToolCall,
    ToolResult,
)
from app.providers.base import ProviderError
from app.tools import ToolRegistry
from tests.fakes import ScriptedAgentProvider


def make_run() -> AgentRun:
    return create_agent_run(
        intent="  make the drums more energetic  ",
        editor_version=EditorVersion(code='s("bd")', hash="editor-hash"),
        apply_mode="manual",
        budget=build_run_budget(AgentRuntimeConfig(maxTurns=3, maxElapsedSeconds=20, maxTotalTokens=1000)),
        provider="mock",
        model="mock-model",
        now=100,
        run_id="run-1",
    )


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


@pytest.mark.anyio
async def test_scripted_provider_returns_turns_and_records_request_copies() -> None:
    provider = ScriptedAgentProvider(
        [ModelTurnResult(assistantMessage=AgentMessage(role="assistant", content="Use inspect_diff."))]
    )
    request = ModelTurnRequest(
        messages=[AgentMessage(role="user", content="Make it punchier.")],
        tools=[],
        model="test-model",
        remainingTokenBudget=500,
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
        "finalize_change",
        "request_user_input",
    ]
    assert provider.requests[0].remaining_token_budget == 1000
    assert [message.role for message in updated.messages] == ["system", "user", "assistant", "tool", "tool"]
    assert [result.name for result in updated.tool_results] == ["inspect_diff", "validate_candidate"]
    assert [result.call_id for result in updated.tool_results] == ["diff-1", "validate-1"]
    assert updated.tool_results[0].output["changed"] is True
    assert updated.tool_results[1].output["valid"] is True
    assert updated.usage.turns == 1
    assert updated.usage.total_tokens == 125


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
async def test_execute_model_turn_leaves_provider_failures_for_budgeted_runtime_handling() -> None:
    provider = ScriptedAgentProvider([ProviderError("provider unavailable", retryable=True)])

    with pytest.raises(ProviderError, match="provider unavailable"):
        await execute_model_turn(make_run(), provider, ToolRegistry(), now=110)


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
