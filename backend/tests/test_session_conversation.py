from __future__ import annotations

import json

from app.agent_runtime import build_run_budget, create_agent_run
from app.config import AgentRuntimeConfig
from app.models import AgentFinalChange, AgentFinalResponse, AgentRun, AgentRunFailure, EditorVersion, RequestUserInput
from app.session_conversation import SessionConversation


def make_run(run_id: str, intent: str = "Make the drums more energetic.") -> AgentRun:
    return create_agent_run(
        intent=intent,
        editor_version=EditorVersion(code='s("bd")', hash=f"{run_id}-hash"),
        apply_mode="manual",
        budget=build_run_budget(AgentRuntimeConfig(maxTurns=3, maxElapsedSeconds=20, maxTotalTokens=1000)),
        provider="mock",
        model="mock-model",
        now=100,
        run_id=run_id,
    )


def rebuild(run: AgentRun, **updates: object) -> AgentRun:
    payload = run.model_dump(by_alias=True)
    payload.update(updates)
    return AgentRun.model_validate(payload)


def test_session_conversation_projects_only_safe_user_meaningful_run_data() -> None:
    conversation = SessionConversation()
    started = make_run("run-1")
    conversation.record_started(started)
    paused = rebuild(
        started,
        status="needs_input",
        pendingInput=RequestUserInput(
            questionId="tempo",
            question="Keep the current tempo?",
            reason="PRIVATE ambiguity analysis",
        ).model_dump(by_alias=True),
    )
    conversation.record_state(paused)
    conversation.record_answer("run-1", "tempo", "Keep it at 124 BPM.")
    completed = rebuild(
        paused,
        status="completed",
        pendingInput=None,
        finalChange=AgentFinalChange(
            code='s("PRIVATE candidate code")',
            explanation="Kept the tempo and added a kick.",
            action="apply",
            warnings=[{"level": "warn", "category": "performance", "message": "Check CPU headroom."}],
        ).model_dump(by_alias=True),
    )
    conversation.record_state(completed)
    conversation.record_staged_change("run-1", "change-1")

    context = conversation.model_context()
    serialized = json.dumps(context)

    assert context == [
        {
            "runId": "run-1",
            "createdAt": 100,
            "intent": "Make the drums more energetic.",
            "clarifications": [{"question": "Keep the current tempo?", "answer": "Keep it at 124 BPM."}],
            "outcome": {
                "status": "completed",
                "action": "apply",
                "explanation": "Kept the tempo and added a kick.",
                "warnings": [{"level": "warn", "category": "performance", "message": "Check CPU headroom."}],
                "changeId": "change-1",
            },
        }
    ]
    assert "PRIVATE" not in serialized
    assert "candidate code" not in serialized


def test_session_conversation_tracks_safe_terminal_outcomes_without_failure_messages() -> None:
    conversation = SessionConversation()
    started = make_run("run-1")
    conversation.record_started(started)
    failed = rebuild(
        started,
        status="failed",
        failure=AgentRunFailure(
            code="provider_error",
            message="PRIVATE provider detail",
            retryable=True,
        ).model_dump(by_alias=True),
    )
    conversation.record_state(failed)

    context = conversation.model_context()

    assert context[0]["outcome"] == {"status": "failed", "errorCode": "provider_error"}
    assert "PRIVATE provider detail" not in json.dumps(context)


def test_session_conversation_records_a_bounded_final_response() -> None:
    conversation = SessionConversation()
    started = make_run("run-1", intent="Explain this rhythm.")
    conversation.record_started(started)
    conversation.record_state(
        rebuild(
            started,
            status="completed",
            finalResponse=AgentFinalResponse(content="The kick plays four times per cycle.").model_dump(by_alias=True),
        )
    )

    context = conversation.model_context()

    assert context[0]["outcome"] == {
        "status": "completed",
        "response": "The kick plays four times per cycle.",
    }


def test_session_conversation_clear_removes_all_revision_context() -> None:
    conversation = SessionConversation()
    started = make_run("run-1")
    conversation.record_started(started)
    conversation.record_state(rebuild(started, status="cancelled"))

    assert conversation.model_context()

    conversation.clear()

    assert conversation.model_context() == []


def test_session_conversation_evicts_old_records_and_marks_truncated_text() -> None:
    conversation = SessionConversation(max_records=2, max_bytes=512)
    for index in range(3):
        started = make_run(f"run-{index}", intent=f"Request {index}: " + "x" * 300)
        conversation.record_started(started)
        conversation.record_state(
            rebuild(
                started,
                status="cancelled",
            )
        )

    context = conversation.model_context()

    assert [entry["runId"] for entry in context] == ["run-1", "run-2"]
    assert all(entry["truncated"] is True for entry in context)
    assert len(json.dumps(context, separators=(",", ":")).encode("utf-8")) <= 512
