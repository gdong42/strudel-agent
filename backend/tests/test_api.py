from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.agent import AgentService
from app.main import app
from app.models import GeneratedChange
from app.providers.base import ProviderRequest


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
        "providers": [{"id": "mock", "label": "Mock", "requiresApiKey": False}],
    }


def test_mock_provider_connection(project_paths: dict[str, Path]) -> None:
    client = TestClient(app)

    response = client.post("/agent/providers/test", json={"provider": "mock"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
