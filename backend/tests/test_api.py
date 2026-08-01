from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.agent import AgentService
from app.agent_runs import AgentRunManager
from app.models import AgentMessage, AgentRunPublic, ModelTurnResult, ToolCall
from app.run_audit import list_audit_records
from tests.fakes import ScriptedAgentProvider


app = main.app


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


def test_get_samples_returns_an_empty_catalog_when_no_registry_is_configured(project_paths: dict[str, Path]) -> None:
    client = TestClient(app)

    response = client.get("/samples")

    assert response.status_code == 200
    assert response.json() == {"configured": False, "samples": []}


def test_get_samples_returns_declared_project_sounds(project_paths: dict[str, Path]) -> None:
    root = project_paths["track_path"].parent.parent
    registry = root / "samples" / "registry.json"
    registry.parent.mkdir()
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "sounds": [
                    {"name": "house_hat", "tags": ["drum", "hat"]},
                    {"name": "house_kick", "tags": ["drum", "kick"], "description": "Dry kick."},
                ],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(app)

    response = client.get("/samples")

    assert response.status_code == 200
    assert response.json() == {
        "configured": True,
        "samples": [
            {"name": "house_hat", "tags": ["drum", "hat"], "description": None},
            {"name": "house_kick", "tags": ["drum", "kick"], "description": "Dry kick."},
        ],
    }


def test_get_samples_reports_an_invalid_registry_without_exposing_a_path(project_paths: dict[str, Path]) -> None:
    root = project_paths["track_path"].parent.parent
    registry = root / "samples" / "registry.json"
    registry.parent.mkdir()
    registry.write_text("not json", encoding="utf-8")
    client = TestClient(app)

    response = client.get("/samples")

    assert response.status_code == 400
    assert response.json()["detail"] == "Could not load sample registry registry.json"
    assert str(root) not in response.text


def test_legacy_change_generation_endpoint_is_not_available(project_paths: dict[str, Path]) -> None:
    client = TestClient(app)

    response = client.post("/changes", json={"intent": "more groove", "currentCode": 's("bd")'})

    assert response.status_code == 404


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
        assert set(started_payload) == {"id", "status", "question", "finalChange", "error", "activities"}
        assert started_payload["status"] == "running"
        assert started_payload["activities"] == []
        assert "test-provider" not in json.dumps(started_payload)

        current = started_payload
        for _ in range(100):
            current = client.get(f'/agent/runs/{started_payload["id"]}').json()
            if current["status"] == "needs_input":
                break
            time.sleep(0.01)

        assert current["id"] == started_payload["id"]
        assert current["status"] == "needs_input"
        assert current["question"] == {
            "id": "tempo",
            "question": "Keep the current tempo?",
            "options": [{"id": "keep", "label": "Keep it", "description": None}],
        }
        assert current["finalChange"] is None
        assert current["error"] is None
        assert [activity["kind"] for activity in current["activities"]] == ["model_turn", "tool"]
        assert current["activities"][-1]["tool"] == "request_user_input"
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


def test_start_agent_run_loads_project_context_without_exposing_it(
    project_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = project_paths["track_path"].parent.parent
    context = "# Set\n\n- Keep the bass stable.\n"
    (root / "agent-context.md").write_text(context, encoding="utf-8")
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
        current = started.json()
        for _ in range(100):
            current = client.get(f"/agent/runs/{run_id}").json()
            if current["status"] == "completed":
                break
            time.sleep(0.01)

    assert started.status_code == 202
    assert current["status"] == "completed"
    assert context in provider.requests[0].messages[0].content
    assert "Keep the bass stable." not in json.dumps(started.json())
    assert "Keep the bass stable." not in json.dumps(current)


def test_start_agent_run_rejects_an_unsafe_project_context_path(project_paths: dict[str, Path]) -> None:
    root = project_paths["track_path"].parent.parent
    (root / "project.config.json").write_text(
        '{"agent":{"contextFile":"../outside.md"}}',
        encoding="utf-8",
    )
    client = TestClient(app)

    response = client.post(
        "/agent/runs",
        json={
            "intent": "Make the drums more energetic.",
            "editorVersion": {"code": 's("bd")', "hash": "editor-hash"},
            "applyMode": "manual",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Project context file must stay inside the project root"


def test_completed_agent_run_reopens_after_a_stale_editor_update(
    project_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
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
            ),
            ModelTurnResult(
                assistantMessage=AgentMessage(
                    role="assistant",
                    toolCalls=[
                        ToolCall(
                            id="final-2",
                            name="finalize_change",
                            arguments={
                                "code": 's("hh*8")',
                                "explanation": "Applied the latest editor context.",
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
        )
        run_id = started.json()["id"]
        current = started.json()
        for _ in range(100):
            current = client.get(f"/agent/runs/{run_id}").json()
            if current["status"] == "completed":
                break
            time.sleep(0.01)

        reopened = client.post(
            f"/agent/runs/{run_id}/editor",
            json={
                "baseHash": "editor-hash",
                "editorVersion": {"code": 's("hh*8")', "hash": "latest-hash"},
            },
        )
        for _ in range(100):
            current = client.get(f"/agent/runs/{run_id}").json()
            if current["status"] == "completed":
                break
            time.sleep(0.01)

    assert reopened.status_code == 200
    assert reopened.json()["status"] == "running"
    assert current["finalChange"]["code"] == 's("hh*8")'
    assert json.loads(provider.requests[-1].messages[-1].content) == {
        "editorUpdate": {
            "baseHash": "editor-hash",
            "editorVersion": {"code": 's("hh*8")', "hash": "latest-hash"},
        }
    }


def test_completed_agent_run_persists_only_after_stage_ack(
    project_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
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
        run_id = started.json()["id"]
        current = started.json()
        for _ in range(100):
            current = client.get(f"/agent/runs/{run_id}").json()
            if current["status"] == "completed":
                break
            time.sleep(0.01)

        assert current["status"] == "completed"
        assert list(project_paths["changes_dir"].glob("*.json")) == []
        final_code = current["finalChange"]["code"]
        final_hash = hashlib.sha256(final_code.encode("utf-8")).hexdigest()

        rejected = client.post(
            f"/agent/runs/{run_id}/stage",
            json={
                "baseHash": "wrong-base-hash",
                "editorVersion": {"code": final_code, "hash": final_hash},
            },
        )
        staged = client.post(
            f"/agent/runs/{run_id}/stage",
            json={
                "baseHash": "editor-hash",
                "editorVersion": {"code": final_code, "hash": final_hash},
            },
        )
        repeated = client.post(
            f"/agent/runs/{run_id}/stage",
            json={
                "baseHash": "editor-hash",
                "editorVersion": {"code": final_code, "hash": final_hash},
            },
        )
        latest = client.get("/changes/latest")
        undone = client.post(f'/changes/{staged.json()["id"]}/undo')

    assert rejected.status_code == 409
    assert staged.status_code == 201
    assert staged.json()["preAgentCode"] == 's("bd")'
    assert staged.json()["code"] == final_code
    assert repeated.status_code == 201
    assert repeated.json()["id"] == staged.json()["id"]
    assert latest.status_code == 200
    assert latest.json()["change"]["id"] == staged.json()["id"]
    assert undone.status_code == 200
    assert undone.json()["code"] == 's("bd")'
    assert len(list(project_paths["changes_dir"].glob("*.json"))) == 1
    [audit] = list_audit_records()
    assert audit.event == "change_undone"
    assert audit.change_id == staged.json()["id"]
    assert final_code not in audit.model_dump_json()


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
    assert set(payload) == {"id", "status", "question", "finalChange", "error", "activities"}
