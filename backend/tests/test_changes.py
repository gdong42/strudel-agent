from pathlib import Path

from app.changes import create_change_from_agent_run, latest_change, undo_change
from app.models import AgentRun


def completed_run() -> AgentRun:
    return AgentRun(
        id="run-1",
        projectId="local-project",
        sessionId="local-session",
        status="completed",
        intent="add energy",
        applyMode="manual",
        editorVersion={"code": 's("bd")', "hash": "base-hash"},
        createdAt=1_000,
        updatedAt=1_042,
        budget={"maxTurns": 4, "maxElapsedSeconds": 30, "maxTotalTokens": 2_000},
        finalChange={
            "code": 's("bd*4")',
            "explanation": "Added four-on-the-floor drums.",
            "action": "apply",
            "warnings": [],
        },
        provider="openai",
        model="test-model",
    )


def test_create_latest_and_undo_change_from_completed_agent_run(project_paths: dict[str, Path]) -> None:
    change = create_change_from_agent_run(completed_run())

    assert change.pre_agent_code == 's("bd")'
    assert change.code == 's("bd*4")'
    assert change.explanation == "Added four-on-the-floor drums."
    assert change.provider == "openai"
    assert change.model == "test-model"
    assert change.latency_ms == 42
    assert latest_change() == change

    undone = undo_change(change.id)

    assert undone is not None
    assert undone.undone_at is not None
    assert latest_change().undone_at == undone.undone_at
