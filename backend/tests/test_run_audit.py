from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.agent_runtime import build_run_budget, create_agent_run
from app.changes import create_change_from_agent_run, undo_change
from app.config import AgentRuntimeConfig
from app.models import AgentFinalChange, AgentFinalResponse, AgentRun, AgentRunFailure, EditorVersion, RequestUserInput
from app.run_audit import AgentAuditLog, list_audit_records


def make_run(run_id: str = "run-1") -> AgentRun:
    return create_agent_run(
        intent="intent-secret: make the drums more energetic",
        editor_version=EditorVersion(code='s("PRIVATE base code")', hash="editor-hash"),
        apply_mode="manual",
        budget=build_run_budget(AgentRuntimeConfig(maxTurns=3, maxElapsedSeconds=20, maxTotalTokens=1000)),
        provider="test-provider",
        model="test-model",
        now=100,
        run_id=run_id,
    )


def rebuild(run: AgentRun, **updates: object) -> AgentRun:
    payload = run.model_dump(by_alias=True)
    payload.update(updates)
    return AgentRun.model_validate(payload)


def test_audit_log_appends_safe_run_lifecycle_events(project_paths: dict[str, Path]) -> None:
    audit = AgentAuditLog()
    started = make_run()
    audit.record_started(started)
    paused = rebuild(
        started,
        status="needs_input",
        pendingInput=RequestUserInput(
            questionId="tempo",
            question="Keep the current tempo?",
            reason="PRIVATE ambiguity reason",
        ).model_dump(by_alias=True),
    )
    audit.record_state(paused)
    resumed = rebuild(paused, status="running", pendingInput=None)
    audit.record_answer(resumed, "tempo", "answer-secret: keep it at 124 BPM")
    completed = rebuild(
        resumed,
        status="completed",
        finalChange=AgentFinalChange(
            code='s("PRIVATE final candidate code")',
            explanation="Kept the tempo and added a kick.",
            action="apply",
            warnings=[{"level": "warn", "category": "performance", "message": "Check CPU headroom."}],
        ).model_dump(by_alias=True),
    )
    audit.record_state(completed)
    audit.record_staged_change(completed, "change-1")

    records = list_audit_records()
    serialized = "\n".join(path.read_text(encoding="utf-8") for path in project_paths["audits_dir"].glob("*.json"))

    assert [record.event for record in records] == [
        "run_started",
        "input_requested",
        "input_answered",
        "run_completed",
        "change_staged",
    ]
    assert records[0].intent is not None
    assert records[0].intent.sha256 == hashlib.sha256(
        b"intent-secret: make the drums more energetic"
    ).hexdigest()
    assert records[0].intent.byte_count == len(b"intent-secret: make the drums more energetic")
    assert records[1].question_id == "tempo"
    assert records[2].answer is not None
    assert records[3].final_explanation == "Kept the tempo and added a kick."
    assert records[4].change_id == "change-1"
    assert "intent-secret" not in serialized
    assert "answer-secret" not in serialized
    assert "PRIVATE base code" not in serialized
    assert "PRIVATE final candidate code" not in serialized
    assert "PRIVATE ambiguity reason" not in serialized


def test_audit_log_records_change_undo_without_copying_accepted_code(project_paths: dict[str, Path]) -> None:
    audit = AgentAuditLog()
    completed = rebuild(
        make_run(),
        status="completed",
        finalChange=AgentFinalChange(
            code='s("PRIVATE accepted code")',
            explanation="Added a kick.",
            action="apply",
        ).model_dump(by_alias=True),
    )
    change = create_change_from_agent_run(completed)
    undone = undo_change(change.id)
    assert undone is not None

    audit.record_change_undone(undone)

    [record] = list_audit_records()
    serialized = json.dumps(record.model_dump(by_alias=True))

    assert record.event == "change_undone"
    assert record.change_id == change.id
    assert record.intent is not None
    assert record.final_explanation == "Added a kick."
    assert "PRIVATE accepted code" not in serialized
    assert "intent-secret" not in serialized


def test_audit_log_records_a_safe_final_response(project_paths: dict[str, Path]) -> None:
    audit = AgentAuditLog()
    completed = rebuild(
        make_run(),
        status="completed",
        finalResponse=AgentFinalResponse(content="The kick plays four times per cycle.").model_dump(by_alias=True),
    )

    audit.record_state(completed)

    [record] = list_audit_records()
    assert record.event == "run_completed"
    assert record.final_response == "The kick plays four times per cycle."
    assert record.final_action is None
    assert record.final_explanation is None
