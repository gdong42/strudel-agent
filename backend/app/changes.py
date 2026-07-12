from __future__ import annotations

import json
import time
from pathlib import Path
from uuid import uuid4

from .models import ChangeRecord, ChangeRequest, GeneratedChange, LOCAL_PROJECT_ID, LOCAL_SESSION_ID
from .paths import changes_dir


CHANGES_DIR = changes_dir()


def create_change(request: ChangeRequest, generated: GeneratedChange) -> ChangeRecord:
    now = int(time.time() * 1000)
    record = ChangeRecord(
        id=f"{now}-{uuid4().hex[:8]}",
        projectId=LOCAL_PROJECT_ID,
        sessionId=LOCAL_SESSION_ID,
        createdAt=now,
        intent=request.intent.strip(),
        scope=request.scope,
        intensity=request.intensity,
        applyMode=request.apply_mode,
        preAgentCode=request.current_code,
        code=generated.code,
        explanation=generated.explanation,
        warnings=generated.warnings,
        ranges=generated.ranges,
    )
    _write_change(record)
    return record


def read_change(change_id: str) -> ChangeRecord | None:
    path = _change_path(change_id)
    if not path.exists():
        return None
    try:
        return ChangeRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def latest_change() -> ChangeRecord | None:
    if not CHANGES_DIR.exists():
        return None
    records = [record for path in CHANGES_DIR.glob("*.json") if (record := read_change(path.stem))]
    return max(records, key=lambda record: record.created_at, default=None)


def undo_change(change_id: str) -> ChangeRecord | None:
    record = read_change(change_id)
    if not record:
        return None
    record.undone_at = int(time.time() * 1000)
    _write_change(record)
    return record


def _write_change(record: ChangeRecord) -> None:
    CHANGES_DIR.mkdir(parents=True, exist_ok=True)
    _change_path(record.id).write_text(
        json.dumps(record.model_dump(by_alias=True), indent=2),
        encoding="utf-8",
    )


def _change_path(change_id: str) -> Path:
    return CHANGES_DIR / f"{change_id}.json"
