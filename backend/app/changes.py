from __future__ import annotations

import json
import time
from pathlib import Path
from uuid import uuid4

from .models import AgentRun, ChangeRecord
from .paths import changes_dir


CHANGES_DIR = changes_dir()


def create_change_from_agent_run(run: AgentRun) -> ChangeRecord:
    if run.status != "completed" or not run.final_change or run.final_change.action != "apply":
        raise ValueError("Only completed apply Agent Runs may be persisted as changes")

    now = int(time.time() * 1000)
    record = ChangeRecord(
        id=f"{now}-{uuid4().hex[:8]}",
        projectId=run.project_id,
        sessionId=run.session_id,
        createdAt=now,
        intent=run.intent,
        applyMode=run.apply_mode,
        preAgentCode=run.editor_version.code,
        code=run.final_change.code,
        explanation=run.final_change.explanation,
        action=run.final_change.action,
        provider=run.provider or "unknown",
        model=run.model,
        latencyMs=max(0, run.updated_at - run.created_at),
        warnings=run.final_change.warnings,
        ranges=run.final_change.ranges,
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
