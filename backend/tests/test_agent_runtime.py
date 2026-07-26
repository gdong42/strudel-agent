from __future__ import annotations

import json

import pytest

from app.agent_runtime import (
    AgentRuntimeTransitionError,
    append_model_turn,
    append_tool_results,
    build_run_budget,
    create_agent_run,
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
