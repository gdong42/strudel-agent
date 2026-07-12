from pathlib import Path

from app.changes import create_change, latest_change, undo_change
from app.models import ChangeRequest, GeneratedChange


def test_create_latest_and_undo_change(project_paths: dict[str, Path]) -> None:
    request = ChangeRequest(intent="add energy", currentCode='s("bd")', scope="drums", intensity="medium")
    generated = GeneratedChange(code='s("bd*4")', explanation="Added four-on-the-floor drums.")
    change = create_change(request, generated)

    assert change.pre_agent_code == 's("bd")'
    assert change.code == 's("bd*4")'
    assert change.explanation == "Added four-on-the-floor drums."
    assert latest_change() == change

    undone = undo_change(change.id)
    assert undone is not None
    assert undone.undone_at is not None
    assert latest_change().undone_at == undone.undone_at
