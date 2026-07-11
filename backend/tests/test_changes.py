from pathlib import Path

from app.changes import create_change, latest_change, undo_change
from app.models import ChangeRequest


def test_create_latest_and_undo_change(project_paths: dict[str, Path]) -> None:
    change = create_change(
        ChangeRequest(intent="add energy", currentCode='s("bd")', scope="drums", intensity="medium")
    )

    assert change.pre_agent_code == 's("bd")'
    assert "Agent draft: add energy (drums, medium)" in change.code
    assert latest_change() == change

    undone = undo_change(change.id)
    assert undone is not None
    assert undone.undone_at is not None
    assert latest_change().undone_at == undone.undone_at
