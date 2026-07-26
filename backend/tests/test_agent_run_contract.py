from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.models import (
    AgentFinalChange,
    AgentMessage,
    AgentRun,
    AgentRunPublic,
    ModelTurnRequest,
    ModelTurnResult,
    RequestUserInput,
    ToolCall,
    ToolDefinition,
    ToolResult,
)


def make_run(status: str = "running", **overrides: object) -> AgentRun:
    payload: dict[str, object] = {
        "id": "run-1",
        "projectId": "local-project",
        "sessionId": "local-session",
        "status": status,
        "intent": "make it more energetic",
        "applyMode": "manual",
        "editorVersion": {"code": 's("bd")', "hash": "editor-hash"},
        "createdAt": 1,
        "updatedAt": 1,
        "budget": {"maxTurns": 8, "maxElapsedSeconds": 60, "maxTotalTokens": 12000},
    }
    payload.update(overrides)
    return AgentRun(**payload)


def make_final_change() -> AgentFinalChange:
    return AgentFinalChange(
        code='s("bd*4")',
        explanation="Added a four-on-the-floor kick.",
        action="apply",
    )


def test_model_turn_contract_uses_normalized_messages_and_tool_calls() -> None:
    request = ModelTurnRequest(
        messages=[
            AgentMessage(role="system", content="You are a Strudel agent."),
            AgentMessage(
                role="assistant",
                content="I will inspect the change.",
                toolCalls=[ToolCall(id="call-1", name="inspect_diff", arguments={"candidate": "next"})],
            ),
        ],
        tools=[
            ToolDefinition(
                name="inspect_diff",
                description="Inspect the candidate diff.",
                inputSchema={"type": "object"},
            )
        ],
        model="provider-model",
        remainingTokenBudget=4096,
    )
    result = ModelTurnResult(
        assistantMessage=AgentMessage(
            role="assistant",
            toolCalls=[ToolCall(id="call-2", name="validate_candidate")],
        ),
        usage={"inputTokens": 100, "outputTokens": 20},
        providerRequestId="provider-request-1",
    )

    assert request.model_dump(by_alias=True)["remainingTokenBudget"] == 4096
    assert request.model_dump(by_alias=True)["messages"][1]["toolCalls"][0]["name"] == "inspect_diff"
    assert result.usage.total_tokens == 120
    assert result.model_dump(by_alias=True)["providerRequestId"] == "provider-request-1"


def test_model_turn_rejects_non_assistant_response() -> None:
    with pytest.raises(ValidationError, match="assistant message"):
        ModelTurnResult(assistantMessage=AgentMessage(role="user", content="not a response"))


def test_agent_run_public_projection_hides_internal_state() -> None:
    run = make_run(
        status="needs_input",
        messages=[AgentMessage(role="assistant", content="PRIVATE candidate code s(\"secret\")")],
        toolResults=[
            ToolResult(
                callId="call-1",
                name="validate_candidate",
                status="recoverable_error",
                output={"candidate": 's("secret")', "reasoning": "PRIVATE review note"},
            )
        ],
        pendingInput=RequestUserInput(
            questionId="tempo",
            question="Should the tempo stay at 124 BPM?",
            options=[{"id": "keep", "label": "Keep 124 BPM"}],
            reason="PRIVATE ambiguity analysis",
        ),
    )

    public_payload = run.to_public().model_dump(by_alias=True)
    public_json = json.dumps(public_payload)

    assert public_payload == {
        "id": "run-1",
        "status": "needs_input",
        "question": {
            "id": "tempo",
            "question": "Should the tempo stay at 124 BPM?",
            "options": [{"id": "keep", "label": "Keep 124 BPM", "description": None}],
        },
        "finalChange": None,
        "error": None,
    }
    assert "PRIVATE" not in public_json
    assert "secret" not in public_json


def test_agent_run_requires_only_status_appropriate_payloads() -> None:
    with pytest.raises(ValidationError, match="require finalChange"):
        make_run(status="completed")

    with pytest.raises(ValidationError, match="Only completed runs"):
        make_run(status="running", finalChange=make_final_change())

    with pytest.raises(ValidationError, match="Only needs_input runs"):
        make_run(
            status="running",
            pendingInput={
                "questionId": "tempo",
                "question": "Choose a tempo",
                "reason": "Need a decision",
            },
        )

    with pytest.raises(ValidationError, match="Only failed runs"):
        make_run(
            status="cancelled",
            failure={"code": "provider_error", "message": "No provider"},
        )


def test_agent_run_public_requires_status_appropriate_payloads() -> None:
    with pytest.raises(ValidationError, match="require question"):
        AgentRunPublic(id="run-1", status="needs_input")

    with pytest.raises(ValidationError, match="Only needs_input public runs"):
        AgentRunPublic(
            id="run-1",
            status="running",
            question={"id": "tempo", "question": "Choose a tempo"},
        )

    completed = AgentRunPublic(id="run-1", status="completed", finalChange=make_final_change())

    assert completed.model_dump(by_alias=True)["finalChange"]["code"] == 's("bd*4")'
