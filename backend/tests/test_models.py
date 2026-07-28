from __future__ import annotations

from app.models import RuntimeState, SnapshotCreateRequest, TrackPayload


def test_snapshot_create_request_defaults_label() -> None:
    payload = SnapshotCreateRequest(code='s("bd")')

    assert payload.label == "Manual evaluate"


def test_track_payload_serializes_camel_case_aliases() -> None:
    payload = TrackPayload(projectId="project", sessionId="session", code='s("bd")', updatedAt=123)

    assert payload.model_dump(by_alias=True) == {
        "projectId": "project",
        "sessionId": "session",
        "code": 's("bd")',
        "updatedAt": 123,
    }


def test_runtime_state_serializes_camel_case_aliases() -> None:
    state = RuntimeState(
        projectId="project",
        sessionId="session",
        activeCode='s("bd")',
        editorCode='s("hh")',
        lastGoodCode='s("bd")',
    )

    assert state.model_dump(by_alias=True) == {
        "projectId": "project",
        "sessionId": "session",
        "activeCode": 's("bd")',
        "editorCode": 's("hh")',
        "lastGoodCode": 's("bd")',
    }
