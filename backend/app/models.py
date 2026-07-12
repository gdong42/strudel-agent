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


class ChangedRange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: int = Field(alias="from")
    to: int
    description: str


class ChangeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    intent: str
    current_code: str = Field(alias="currentCode")
    apply_mode: Literal["manual", "auto"] = Field(default="manual", alias="applyMode")


class GeneratedChange(BaseModel):
    code: str
    explanation: str
    warnings: list[ChangeWarning] = Field(default_factory=list)
    ranges: list[ChangedRange] | None = None


class AgentResult(GeneratedChange):
    provider: str
    model: str | None = None
    latency_ms: int = Field(alias="latencyMs")


class ChangeRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    project_id: str = Field(alias="projectId")
    session_id: str = Field(alias="sessionId")
    created_at: int = Field(alias="createdAt")
    intent: str
    apply_mode: Literal["manual", "auto"] = Field(alias="applyMode")
    pre_agent_code: str = Field(alias="preAgentCode")
    code: str
    explanation: str
    provider: str = "unknown"
    model: str | None = None
    latency_ms: int | None = Field(default=None, alias="latencyMs")
    warnings: list[ChangeWarning] = Field(default_factory=list)
    ranges: list[ChangedRange] | None = None
    undone_at: int | None = Field(default=None, alias="undoneAt")


class ChangeListResponse(BaseModel):
    change: ChangeRecord | None


class ChangeUndoResponse(BaseModel):
    change: ChangeRecord
    code: str


class ProviderInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    label: str
    requires_api_key: bool = Field(alias="requiresApiKey")
    default_model: str | None = Field(default=None, alias="defaultModel")


class AgentSettingsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    default_provider: str = Field(alias="defaultProvider")
    default_model: str | None = Field(alias="defaultModel")
    providers: list[ProviderInfo]


class ProviderTestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider: str | None = None
    model: str | None = None
    api_key: str | None = Field(default=None, alias="apiKey")


class ProviderTestResponse(BaseModel):
    ok: bool
    message: str
