from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


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
