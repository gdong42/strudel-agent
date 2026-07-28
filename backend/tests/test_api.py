from __future__ import annotations

import asyncio
import json
from pathlib import Path
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.agent import AgentService
from app.agent_runs import AgentRunManager
from app.models import AgentMessage, AgentRunPublic, GeneratedChange, ModelTurnResult, ToolCall
from app.providers.base import ProviderRequest
from tests.fakes import ScriptedAgentProvider


app = main.app


class EmptyCodeProvider:
    async def create_change(self, request: ProviderRequest) -> GeneratedChange:
        return GeneratedChange(code=" ", explanation="Invalid response")


def test_get_track(project_paths: dict[str, Path]) -> None:
    client = TestClient(app)

    response = client.get("/track")

    assert response.status_code == 200
    assert response.json()["code"] == 's("bd")\n'
    assert response.json()["projectId"] == "local-project"


def test_post_track_rejects_empty_code(project_paths: dict[str, Path]) -> None:
    client = TestClient(app)

    response = client.post("/track", json={"code": "   "})

    assert response.status_code == 400


def test_snapshot_create_list_and_revert(project_paths: dict[str, Path]) -> None:
    client = TestClient(app)

    created = client.post("/snapshots", json={"code": 's("hh")', "label": "Good"})
    assert created.status_code == 200
    snapshot_id = created.json()["id"]

    listed = client.get("/snapshots")
    assert listed.status_code == 200
    assert listed.json()["snapshots"][0]["id"] == snapshot_id

    reverted = client.post(f"/snapshots/{snapshot_id}/revert")
    assert reverted.status_code == 200
    assert reverted.json()["snapshot"]["code"] == 's("hh")'
    assert project_paths["track_path"].read_text(encoding="utf-8") == 's("hh")'


def test_revert_missing_snapshot_returns_404(project_paths: dict[str, Path]) -> None:
    client = TestClient(app)

    response = client.post("/snapshots/missing/revert")

    assert response.status_code == 404


def test_state_uses_latest_snapshot_as_last_good(project_paths: dict[str, Path]) -> None:
    client = TestClient(app)

    client.post("/snapshots", json={"code": 's("hh")'})
    response = client.get("/state")

    assert response.status_code == 200
    assert response.json()["editorCode"] == 's("bd")\n'
    assert response.json()["lastGoodCode"] == 's("hh")'


def test_change_stage_latest_and_undo(project_paths: dict[str, Path]) -> None:
    client = TestClient(app)
    staged = client.post(
        "/changes",
        json={"intent": "more groove", "currentCode": 's("bd")', "applyMode": "manual"},
    )
    assert staged.status_code == 200
    assert staged.json()["preAgentCode"] == 's("bd")'
    assert "more groove" in staged.json()["code"]

    latest = client.get("/changes/latest")
    assert latest.json()["change"]["id"] == staged.json()["id"]

    undone = client.post(f'/changes/{staged.json()["id"]}/undo')
    assert undone.status_code == 200
    assert undone.json()["code"] == 's("bd")'


def test_change_rejects_empty_intent(project_paths: dict[str, Path]) -> None:
    client = TestClient(app)
    response = client.post("/changes", json={"intent": " ", "currentCode": 's("bd")'})
    assert response.status_code == 400


def test_change_rejects_invalid_provider_response_without_persisting(
    project_paths: dict[str, Path], monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.main.create_agent_service",
        lambda *args, **kwargs: AgentService(EmptyCodeProvider()),
    )
    client = TestClient(app)

    response = client.post("/changes", json={"intent": "change it", "currentCode": 's("bd")'})

    assert response.status_code == 502
    assert "empty Strudel code" in response.json()["detail"]
    assert list(project_paths["changes_dir"].glob("*.json")) == []


def test_agent_settings_exposes_defaults_without_secrets(project_paths: dict[str, Path]) -> None:
    client = TestClient(app)

    response = client.get("/agent/settings")

    assert response.status_code == 200
    assert response.json() == {
        "defaultProvider": "mock",
        "defaultModel": None,
        "providers": [
            {"id": "mock", "label": "Mock", "requiresApiKey": False, "defaultModel": None},
            {
                "id": "deepseek",
                "label": "DeepSeek",
                "requiresApiKey": True,
                "defaultModel": "deepseek-v4-pro",
            },
            {
                "id": "openai",
                "label": "OpenAI",
                "requiresApiKey": True,
                "defaultModel": "gpt-5.6-terra",
            },
        ],
    }


def test_mock_provider_connection(project_paths: dict[str, Path]) -> None:
    client = TestClient(app)

    response = client.post("/agent/providers/test", json={"provider": "mock"})

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_start_and_read_agent_run_exposes_only_public_state(
    project_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
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
                                "options": [{"id": "keep", "label": "Keep it", "description": None}],
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
    monkeypatch.setattr(main, "agent_runs", AgentRunManager())
    monkeypatch.setattr(
        main,
        "create_agent_service",
        lambda *args, **kwargs: AgentService(provider, provider_name="test-provider", model="test-model"),
    )

    with TestClient(app) as client:
        started = client.post(
            "/agent/runs",
            json={
                "intent": "Make the drums more energetic.",
                "editorVersion": {"code": 's("bd")', "hash": "editor-hash"},
                "applyMode": "manual",
            },
            headers={"X-Agent-Provider": "mock"},
        )

        assert started.status_code == 202
        started_payload = started.json()
        assert set(started_payload) == {"id", "status", "question", "finalChange", "error"}
        assert started_payload["status"] == "running"
        assert "test-provider" not in json.dumps(started_payload)

        current = started_payload
        for _ in range(100):
            current = client.get(f'/agent/runs/{started_payload["id"]}').json()
            if current["status"] == "needs_input":
                break
            time.sleep(0.01)

        assert current == {
            "id": started_payload["id"],
            "status": "needs_input",
            "question": {
                "id": "tempo",
                "question": "Keep the current tempo?",
                "options": [{"id": "keep", "label": "Keep it", "description": None}],
            },
            "finalChange": None,
            "error": None,
        }
        assert "private ambiguity analysis" not in json.dumps(current)

        editor_updated = client.post(
            f'/agent/runs/{started_payload["id"]}/editor',
            json={
                "baseHash": "editor-hash",
                "editorVersion": {"code": 's("bd*4")', "hash": "latest-hash"},
            },
        )
        assert editor_updated.status_code == 200
        assert editor_updated.json()["status"] == "needs_input"

        stale_editor_update = client.post(
            f'/agent/runs/{started_payload["id"]}/editor',
            json={
                "baseHash": "editor-hash",
                "editorVersion": {"code": 's("hh")', "hash": "stale-hash"},
            },
        )
        assert stale_editor_update.status_code == 409

        resumed = client.post(
            f'/agent/runs/{started_payload["id"]}/input',
            json={"questionId": "tempo", "answer": "Keep it at 124."},
            headers={"X-Agent-Provider": "mock"},
        )
        assert resumed.status_code == 202
        assert resumed.json()["status"] == "running"

        for _ in range(100):
            current = client.get(f'/agent/runs/{started_payload["id"]}').json()
            if current["status"] == "completed":
                break
            time.sleep(0.01)

        assert current["status"] == "completed"
        assert json.loads(provider.requests[-1].messages[-1].content) == {
            "userInput": {"questionId": "tempo", "answer": "Keep it at 124."},
            "editorVersion": {"code": 's("bd*4")', "hash": "latest-hash"},
        }


def test_default_mock_agent_run_completes(project_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "agent_runs", AgentRunManager())

    with TestClient(app) as client:
        started = client.post(
            "/agent/runs",
            json={
                "intent": "Make the drums more energetic.",
                "editorVersion": {"code": 's("bd")', "hash": "editor-hash"},
                "applyMode": "manual",
            },
        )
        assert started.status_code == 202

        current = started.json()
        for _ in range(100):
            current = client.get(f'/agent/runs/{current["id"]}').json()
            if current["status"] == "completed":
                break
            time.sleep(0.01)

    assert current["status"] == "completed"
    assert current["finalChange"]["code"] == 's("bd")\n\n// Agent draft: Make the drums more energetic.\n'


def test_cancel_agent_run_is_idempotent(project_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(main, "agent_runs", AgentRunManager())
    monkeypatch.setattr(
        main,
        "create_agent_service",
        lambda *args, **kwargs: AgentService(provider, provider_name="test-provider", model="test-model"),
    )

    with TestClient(app) as client:
        started = client.post(
            "/agent/runs",
            json={
                "intent": "Make the drums more energetic.",
                "editorVersion": {"code": 's("bd")', "hash": "editor-hash"},
                "applyMode": "manual",
            },
        )
        run_id = started.json()["id"]
        for _ in range(100):
            current = client.get(f"/agent/runs/{run_id}").json()
            if current["status"] == "needs_input":
                break
            time.sleep(0.01)

        cancelled = client.post(f"/agent/runs/{run_id}/cancel")
        repeated = client.post(f"/agent/runs/{run_id}/cancel")
        rejected_input = client.post(
            f"/agent/runs/{run_id}/input",
            json={"questionId": "tempo", "answer": "Keep it at 124."},
        )

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "cancelled"
    assert rejected_input.status_code == 409


def test_start_agent_run_rejects_empty_editor_code(project_paths: dict[str, Path]) -> None:
    client = TestClient(app)

    response = client.post(
        "/agent/runs",
        json={
            "intent": "Make the drums more energetic.",
            "editorVersion": {"code": " ", "hash": "editor-hash"},
            "applyMode": "manual",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Agent Run editor code cannot be empty"


def test_get_missing_agent_run_returns_404(project_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "agent_runs", AgentRunManager())

    with TestClient(app) as client:
        response = client.get("/agent/runs/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Agent Run not found"


@pytest.mark.anyio
async def test_agent_run_event_contains_only_public_payload() -> None:
    queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
    main.clients.add(queue)
    run = AgentRunPublic(
        id="run-1",
        status="needs_input",
        question={"id": "tempo", "question": "Keep the current tempo?", "options": []},
    )

    try:
        await main.broadcast_agent_run(run)
        event, payload = await queue.get()
    finally:
        main.clients.discard(queue)

    assert event == "agent-run"
    assert payload == run.model_dump(by_alias=True)
    assert set(payload) == {"id", "status", "question", "finalChange", "error"}
