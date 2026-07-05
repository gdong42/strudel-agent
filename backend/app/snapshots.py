from __future__ import annotations

import json
import time
from pathlib import Path
from uuid import uuid4

from .config import load_config
from .models import LOCAL_PROJECT_ID, LOCAL_SESSION_ID, SnapshotRecord
from .paths import snapshots_dir


SNAPSHOTS_DIR = snapshots_dir()
MAX_SNAPSHOTS = load_config().snapshots.max_count
MAX_SNAPSHOT_AGE_MS = load_config().snapshots.max_age_hours * 60 * 60 * 1000


def list_snapshots() -> list[SnapshotRecord]:
    if not SNAPSHOTS_DIR.exists():
        return []

    snapshots: list[SnapshotRecord] = []
    for path in SNAPSHOTS_DIR.glob("*.json"):
        try:
            snapshots.append(SnapshotRecord.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue

    return sorted(snapshots, key=lambda snapshot: snapshot.created_at, reverse=True)


def create_snapshot(code: str, label: str = "Manual evaluate") -> SnapshotRecord:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = SnapshotRecord(
        id=f"{int(time.time() * 1000)}-{uuid4().hex[:8]}",
        projectId=LOCAL_PROJECT_ID,
        sessionId=LOCAL_SESSION_ID,
        createdAt=int(time.time() * 1000),
        label=label,
        code=code,
    )

    _snapshot_path(snapshot.id).write_text(
        json.dumps(snapshot.model_dump(by_alias=True), indent=2),
        encoding="utf-8",
    )
    prune_snapshots()
    return snapshot


def read_snapshot(snapshot_id: str) -> SnapshotRecord | None:
    path = _snapshot_path(snapshot_id)
    if not path.exists():
        return None
    return SnapshotRecord.model_validate_json(path.read_text(encoding="utf-8"))


def latest_snapshot() -> SnapshotRecord | None:
    snapshots = list_snapshots()
    if not snapshots:
        return None
    return snapshots[0]


def prune_snapshots() -> None:
    snapshots = list_snapshots()
    now = int(time.time() * 1000)
    for snapshot in snapshots[MAX_SNAPSHOTS:]:
        try:
            _snapshot_path(snapshot.id).unlink()
        except FileNotFoundError:
            continue
    for snapshot in snapshots:
        if now - snapshot.created_at <= MAX_SNAPSHOT_AGE_MS:
            continue
        try:
            _snapshot_path(snapshot.id).unlink()
        except FileNotFoundError:
            continue


def _snapshot_path(snapshot_id: str) -> Path:
    return SNAPSHOTS_DIR / f"{snapshot_id}.json"
