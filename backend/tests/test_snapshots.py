from __future__ import annotations

from pathlib import Path

from app import snapshots


def test_create_and_read_snapshot(project_paths: dict[str, Path]) -> None:
    snapshot = snapshots.create_snapshot('s("bd")', "First")

    read_back = snapshots.read_snapshot(snapshot.id)

    assert read_back == snapshot
    assert project_paths["snapshots_dir"].exists()


def test_list_snapshots_descending(project_paths: dict[str, Path], monkeypatch) -> None:
    current = 1000.0

    def tick() -> float:
        nonlocal current
        current += 1
        return current

    monkeypatch.setattr(snapshots.time, "time", tick)

    first = snapshots.create_snapshot('s("bd")', "First")
    second = snapshots.create_snapshot('s("hh")', "Second")

    assert [snapshot.id for snapshot in snapshots.list_snapshots()] == [second.id, first.id]


def test_read_missing_snapshot_returns_none(project_paths: dict[str, Path]) -> None:
    assert snapshots.read_snapshot("missing") is None


def test_prune_by_count(project_paths: dict[str, Path], monkeypatch) -> None:
    monkeypatch.setattr(snapshots, "MAX_SNAPSHOTS", 2)
    current = 1000.0

    def tick() -> float:
        nonlocal current
        current += 1
        return current

    monkeypatch.setattr(snapshots.time, "time", tick)

    first = snapshots.create_snapshot('s("bd")', "First")
    snapshots.create_snapshot('s("hh")', "Second")
    snapshots.create_snapshot('s("cp")', "Third")

    assert snapshots.read_snapshot(first.id) is None
    assert len(snapshots.list_snapshots()) == 2


def test_prune_by_age(project_paths: dict[str, Path], monkeypatch) -> None:
    monkeypatch.setattr(snapshots, "MAX_SNAPSHOT_AGE_MS", 1000)
    now = 1000.0
    monkeypatch.setattr(snapshots.time, "time", lambda: now)
    old = snapshots.create_snapshot('s("bd")', "Old")

    now = 1002.0
    snapshots.prune_snapshots()

    assert snapshots.read_snapshot(old.id) is None
