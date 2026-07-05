from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


LOCAL_PROJECT_ID = "local-project"
LOCAL_SESSION_ID = "local-session"


class TrackPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_id: str = Field(alias="projectId")
    session_id: str = Field(alias="sessionId")
    code: str
    updated_at: int = Field(alias="updatedAt")


class TrackSaveRequest(BaseModel):
    code: str


class RuntimeState(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_id: str = Field(alias="projectId")
    session_id: str = Field(alias="sessionId")
    active_code: str = Field(alias="activeCode")
    editor_code: str = Field(alias="editorCode")
    last_good_code: str = Field(alias="lastGoodCode")


class SnapshotCreateRequest(BaseModel):
    code: str
    label: str = "Manual evaluate"


class SnapshotRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    project_id: str = Field(alias="projectId")
    session_id: str = Field(alias="sessionId")
    created_at: int = Field(alias="createdAt")
    label: str
    code: str


class SnapshotListResponse(BaseModel):
    snapshots: list[SnapshotRecord]


class SnapshotRevertResponse(BaseModel):
    snapshot: SnapshotRecord
    track: TrackPayload


class ChangeWarning(BaseModel):
    level: Literal["info", "warn", "risk"]
    message: str
    category: Literal["sample", "visual", "structure", "performance", "mini-notation"]
