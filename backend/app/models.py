from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    action: Literal["apply", "noop"] = "apply"
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


AgentRunStatus = Literal["running", "needs_input", "completed", "failed", "cancelled"]
AgentMessageRole = Literal["system", "user", "assistant", "tool"]
ToolResultStatus = Literal["ok", "recoverable_error", "fatal_error"]
AgentActivityKind = Literal["model_turn", "commentary", "tool", "editor_update", "user_input"]
AgentActivityStatus = Literal["running", "completed", "cancelled"]
AgentActivityTool = Literal[
    "inspect_diff",
    "validate_candidate",
    "lookup_strudel_docs",
    "lookup_samples",
    "inspect_sample_usage",
    "finalize_change",
    "request_user_input",
    "agent_tool",
]


class EditorVersion(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code: str
    hash: str = Field(min_length=1)


class AgentActivity(BaseModel):
    """Browser-safe progress metadata. It never contains model or tool payloads."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    sequence: int = Field(ge=1)
    kind: AgentActivityKind
    status: AgentActivityStatus
    started_at: int = Field(alias="startedAt", ge=0)
    completed_at: int | None = Field(default=None, alias="completedAt", ge=0)
    turn: int | None = Field(default=None, ge=1)
    tool: AgentActivityTool | None = None
    message: str | None = Field(default=None, min_length=1, max_length=4096)

    @model_validator(mode="after")
    def validate_activity_shape(self) -> "AgentActivity":
        if self.kind == "model_turn" and self.turn is None:
            raise ValueError("Model turn activities require a turn")
        if self.kind != "model_turn" and self.turn is not None:
            raise ValueError("Only model turn activities may include a turn")
        if self.kind == "tool" and self.tool is None:
            raise ValueError("Tool activities require a tool")
        if self.kind != "tool" and self.tool is not None:
            raise ValueError("Only tool activities may include a tool")
        if self.kind == "commentary" and self.message is None:
            raise ValueError("Commentary activities require a message")
        if self.kind != "commentary" and self.message is not None:
            raise ValueError("Only commentary activities may include a message")
        if self.status == "running" and self.completed_at is not None:
            raise ValueError("Running activities cannot have completedAt")
        if self.status != "running" and self.completed_at is None:
            raise ValueError("Finished activities require completedAt")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("Activity completedAt cannot precede startedAt")
        return self


class AgentQuestionOption(BaseModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    description: str | None = None


class AgentQuestion(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    options: list[AgentQuestionOption] = Field(default_factory=list)


class RequestUserInput(BaseModel):
    """Internal tool arguments. `reason` is deliberately absent from public state."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    question_id: str = Field(alias="questionId", min_length=1)
    question: str = Field(min_length=1)
    options: list[AgentQuestionOption] = Field(default_factory=list)
    reason: str = Field(min_length=1)

    def to_public_question(self) -> AgentQuestion:
        return AgentQuestion(id=self.question_id, question=self.question, options=self.options)


class ToolCall(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolDefinition(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input_schema: dict[str, Any] = Field(alias="inputSchema")


class ToolResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    call_id: str = Field(alias="callId", min_length=1)
    name: str = Field(min_length=1)
    status: ToolResultStatus
    output: dict[str, Any] = Field(default_factory=dict)


class AgentMessage(BaseModel):
    """Private normalized model message. Never serialize it to browser clients."""

    model_config = ConfigDict(populate_by_name=True)

    role: AgentMessageRole
    content: str = ""
    reasoning_content: str | None = Field(default=None, alias="reasoningContent")
    tool_calls: list[ToolCall] = Field(default_factory=list, alias="toolCalls")
    tool_call_id: str | None = Field(default=None, alias="toolCallId")

    @model_validator(mode="after")
    def validate_tool_message_shape(self) -> "AgentMessage":
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("Tool messages require toolCallId")
        if self.role != "tool" and self.tool_call_id:
            raise ValueError("Only tool messages may include toolCallId")
        if self.role != "assistant" and self.tool_calls:
            raise ValueError("Only assistant messages may include toolCalls")
        if self.role != "assistant" and self.reasoning_content is not None:
            raise ValueError("Only assistant messages may include reasoningContent")
        return self


class ModelUsage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    input_tokens: int = Field(default=0, alias="inputTokens", ge=0)
    output_tokens: int = Field(default=0, alias="outputTokens", ge=0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ModelTurnRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    messages: list[AgentMessage]
    tools: list[ToolDefinition]
    model: str = Field(min_length=1)
    max_output_tokens: int = Field(alias="maxOutputTokens", ge=0)


class ModelTurnResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    assistant_message: AgentMessage = Field(alias="assistantMessage")
    usage: ModelUsage = Field(default_factory=ModelUsage)
    provider_request_id: str | None = Field(default=None, alias="providerRequestId")

    @model_validator(mode="after")
    def validate_assistant_message(self) -> "ModelTurnResult":
        if self.assistant_message.role != "assistant":
            raise ValueError("Model turns must return an assistant message")
        return self


class AgentRunBudget(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    max_turns: int = Field(alias="maxTurns", ge=1)
    max_elapsed_seconds: int = Field(alias="maxElapsedSeconds", ge=1)
    max_total_tokens: int | None = Field(alias="maxTotalTokens", ge=1)
    max_output_tokens_per_turn: int = Field(default=65_536, alias="maxOutputTokensPerTurn", ge=1)


class AgentRunUsage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    turns: int = Field(default=0, ge=0)
    elapsed_seconds: int = Field(default=0, alias="elapsedSeconds", ge=0)
    input_tokens: int = Field(default=0, alias="inputTokens", ge=0)
    output_tokens: int = Field(default=0, alias="outputTokens", ge=0)
    total_tokens: int = Field(default=0, alias="totalTokens", ge=0)


AgentAuditEvent = Literal[
    "run_started",
    "input_requested",
    "input_answered",
    "run_completed",
    "run_failed",
    "run_cancelled",
    "change_staged",
    "change_undone",
]


class AuditTextFingerprint(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    sha256: str = Field(min_length=64, max_length=64)
    byte_count: int = Field(alias="byteCount", ge=0)


class AgentAuditRecord(BaseModel):
    """Durable, code-free audit event. This model is never a browser response."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(min_length=1)
    project_id: str = Field(alias="projectId")
    session_id: str = Field(alias="sessionId")
    run_id: str | None = Field(default=None, alias="runId")
    occurred_at: int = Field(alias="occurredAt", ge=0)
    event: AgentAuditEvent
    status: AgentRunStatus | None = None
    provider: str | None = None
    model: str | None = None
    usage: AgentRunUsage | None = None
    intent: AuditTextFingerprint | None = None
    question_id: str | None = Field(default=None, alias="questionId")
    answer: AuditTextFingerprint | None = None
    final_action: Literal["apply", "noop"] | None = Field(default=None, alias="finalAction")
    final_explanation: str | None = Field(default=None, alias="finalExplanation")
    final_response: str | None = Field(default=None, alias="finalResponse")
    final_warnings: list[ChangeWarning] = Field(default_factory=list, alias="finalWarnings")
    change_id: str | None = Field(default=None, alias="changeId")
    error_code: str | None = Field(default=None, alias="errorCode")
    truncated: bool = False


class AgentFinalChange(BaseModel):
    code: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    action: Literal["apply", "noop"]
    warnings: list[ChangeWarning] = Field(default_factory=list)
    ranges: list[ChangedRange] | None = None


class AgentFinalResponse(BaseModel):
    content: str = Field(min_length=1)


class AgentRunFailure(BaseModel):
    code: Literal[
        "budget_exhausted",
        "provider_error",
        "tool_error",
        "finalization_failed",
        "internal_error",
    ]
    message: str = Field(min_length=1)
    retryable: bool = False


class AgentRunStartRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    intent: str = Field(min_length=1)
    editor_version: EditorVersion = Field(alias="editorVersion")
    apply_mode: Literal["manual", "auto"] = Field(default="manual", alias="applyMode")
    runtime_limits: AgentRunBudget | None = Field(default=None, alias="runtimeLimits")


class AgentRunInputRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    question_id: str = Field(alias="questionId", min_length=1)
    answer: str = Field(min_length=1)


class AgentRunEditorUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    base_hash: str = Field(alias="baseHash", min_length=1)
    editor_version: EditorVersion = Field(alias="editorVersion")


class AgentRunStageRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    base_hash: str = Field(alias="baseHash", min_length=1)
    editor_version: EditorVersion = Field(alias="editorVersion")


class AgentRun(BaseModel):
    """Internal runtime state. Do not serialize this model to browser clients."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(min_length=1)
    project_id: str = Field(alias="projectId")
    session_id: str = Field(alias="sessionId")
    status: AgentRunStatus
    intent: str = Field(min_length=1)
    apply_mode: Literal["manual", "auto"] = Field(alias="applyMode")
    editor_version: EditorVersion = Field(alias="editorVersion")
    created_at: int = Field(alias="createdAt", ge=0)
    updated_at: int = Field(alias="updatedAt", ge=0)
    active_elapsed_milliseconds: int = Field(default=0, alias="activeElapsedMilliseconds", ge=0)
    active_started_at: int | None = Field(default=None, alias="activeStartedAt", ge=0)
    budget: AgentRunBudget
    usage: AgentRunUsage = Field(default_factory=AgentRunUsage)
    activities: list[AgentActivity] = Field(default_factory=list)
    messages: list[AgentMessage] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list, alias="toolResults")
    final_change: AgentFinalChange | None = Field(default=None, alias="finalChange")
    final_response: AgentFinalResponse | None = Field(default=None, alias="finalResponse")
    pending_input: RequestUserInput | None = Field(default=None, alias="pendingInput")
    failure: AgentRunFailure | None = None
    provider: str | None = None
    model: str | None = None
    staged_change_id: str | None = Field(default=None, alias="stagedChangeId")

    @model_validator(mode="after")
    def validate_status_shape(self) -> "AgentRun":
        if self.status == "completed" and (self.final_change is None) == (self.final_response is None):
            raise ValueError("Completed runs require exactly one final result")
        if self.status == "needs_input" and not self.pending_input:
            raise ValueError("needs_input runs require pendingInput")
        if self.status == "failed" and not self.failure:
            raise ValueError("Failed runs require failure")
        if self.status in {"running", "needs_input", "failed", "cancelled"} and self.final_change:
            raise ValueError("Only completed runs may include finalChange")
        if self.status != "completed" and self.final_response:
            raise ValueError("Only completed runs may include finalResponse")
        if self.status != "needs_input" and self.pending_input:
            raise ValueError("Only needs_input runs may include pendingInput")
        if self.status != "failed" and self.failure:
            raise ValueError("Only failed runs may include failure")
        if self.staged_change_id and self.status != "completed":
            raise ValueError("Only completed Agent Runs may have a staged change")
        return self

    def to_public(self) -> "AgentRunPublic":
        return AgentRunPublic(
            id=self.id,
            status=self.status,
            question=self.pending_input.to_public_question() if self.status == "needs_input" and self.pending_input else None,
            finalChange=self.final_change if self.status == "completed" else None,
            finalResponse=self.final_response if self.status == "completed" else None,
            error=self.failure if self.status == "failed" else None,
            activities=[activity.model_copy(deep=True) for activity in self.activities],
        )


class AgentRunPublic(BaseModel):
    """Browser-safe projection of an Agent Run."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    status: AgentRunStatus
    question: AgentQuestion | None = None
    final_change: AgentFinalChange | None = Field(default=None, alias="finalChange")
    final_response: AgentFinalResponse | None = Field(default=None, alias="finalResponse")
    error: AgentRunFailure | None = None
    activities: list[AgentActivity] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_public_status_shape(self) -> "AgentRunPublic":
        if self.status == "completed" and (self.final_change is None) == (self.final_response is None):
            raise ValueError("Completed public runs require exactly one final result")
        if self.status == "needs_input" and not self.question:
            raise ValueError("needs_input public runs require question")
        if self.status == "failed" and not self.error:
            raise ValueError("Failed public runs require error")
        if self.status != "completed" and self.final_change:
            raise ValueError("Only completed public runs may include finalChange")
        if self.status != "completed" and self.final_response:
            raise ValueError("Only completed public runs may include finalResponse")
        if self.status != "needs_input" and self.question:
            raise ValueError("Only needs_input public runs may include question")
        if self.status != "failed" and self.error:
            raise ValueError("Only failed public runs may include error")
        return self


class ProviderInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    label: str
    requires_api_key: bool = Field(alias="requiresApiKey")
    default_model: str | None = Field(default=None, alias="defaultModel")
    default_runtime: AgentRunBudget = Field(alias="defaultRuntime")


class AgentSettingsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    default_provider: str = Field(alias="defaultProvider")
    default_model: str | None = Field(alias="defaultModel")
    default_runtime: AgentRunBudget = Field(alias="defaultRuntime")
    providers: list[ProviderInfo]


class ProviderTestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider: str | None = None
    model: str | None = None
    api_key: str | None = Field(default=None, alias="apiKey")


class ProviderTestResponse(BaseModel):
    ok: bool
    message: str
