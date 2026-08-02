from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .agent import AgentConfigurationError, create_agent_service, list_provider_info
from .agent_runs import AgentRunManager
from .agent_runtime import AgentRuntimeTransitionError, build_run_budget
from .changes import latest_change, undo_change
from .config import load_config
from .models import (
    AgentRunEditorUpdateRequest,
    AgentRunInputRequest,
    AgentRunPublic,
    AgentRunStageRequest,
    AgentRunStartRequest,
    ChangeListResponse,
    ChangeUndoResponse,
    AgentSettingsResponse,
    LOCAL_PROJECT_ID,
    LOCAL_SESSION_ID,
    RuntimeState,
    SnapshotCreateRequest,
    SnapshotListResponse,
    SnapshotRevertResponse,
    TrackPayload,
    TrackSaveRequest,
    ProviderTestRequest,
    ProviderTestResponse,
)
from .providers.base import ProviderError
from .project_context import ProjectContextError, load_project_context
from .run_audit import AgentAuditLog
from .samples import SampleListResponse, SampleRegistryError, declared_samples, load_sample_registry
from .snapshots import create_snapshot, latest_snapshot, list_snapshots, read_snapshot
from .tracks import read_track, write_track


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await agent_runs.close()


app = FastAPI(title="Strudel Agent", lifespan=lifespan)
SseEvent = tuple[str, dict[str, Any]]
clients: set[asyncio.Queue[SseEvent]] = set()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def track_event() -> dict[str, Any]:
    return TrackPayload(
        projectId=LOCAL_PROJECT_ID,
        sessionId=LOCAL_SESSION_ID,
        code=read_track(),
        updatedAt=int(time.time() * 1000),
    ).model_dump(by_alias=True)


def encode_sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def broadcast_track() -> None:
    await broadcast("track", track_event())


async def broadcast_agent_run(run: AgentRunPublic) -> None:
    await broadcast("agent-run", run.model_dump(by_alias=True))


async def broadcast(event: str, payload: dict[str, Any]) -> None:
    for queue in list(clients):
        await queue.put((event, payload))


agent_audit = AgentAuditLog()
agent_runs = AgentRunManager(on_update=broadcast_agent_run, audit_log=agent_audit)


@app.get("/track")
async def get_track() -> dict[str, Any]:
    return track_event()


@app.get("/state")
async def get_state() -> dict[str, Any]:
    code = read_track()
    snapshot = latest_snapshot()
    return RuntimeState(
        projectId=LOCAL_PROJECT_ID,
        sessionId=LOCAL_SESSION_ID,
        activeCode=snapshot.code if snapshot else code,
        editorCode=code,
        lastGoodCode=snapshot.code if snapshot else code,
    ).model_dump(by_alias=True)


@app.post("/track", status_code=204)
async def save_track(payload: TrackSaveRequest) -> None:
    if not payload.code.strip():
        raise HTTPException(status_code=400, detail="Refusing to write an empty track")

    write_track(payload.code)
    await broadcast_track()


@app.get("/snapshots")
async def get_snapshots() -> dict[str, Any]:
    return SnapshotListResponse(snapshots=list_snapshots()).model_dump(by_alias=True)


@app.post("/snapshots")
async def post_snapshot(payload: SnapshotCreateRequest) -> dict[str, Any]:
    if not payload.code.strip():
        raise HTTPException(status_code=400, detail="Refusing to snapshot empty code")
    return create_snapshot(payload.code, payload.label).model_dump(by_alias=True)


@app.post("/snapshots/{snapshot_id}/revert")
async def revert_snapshot(snapshot_id: str) -> dict[str, Any]:
    snapshot = read_snapshot(snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    write_track(snapshot.code)
    await broadcast_track()
    return SnapshotRevertResponse(snapshot=snapshot, track=TrackPayload.model_validate(track_event())).model_dump(
        by_alias=True
    )


@app.get("/samples")
async def get_samples() -> dict[str, Any]:
    try:
        registry = load_sample_registry()
    except SampleRegistryError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return SampleListResponse(configured=registry.configured, samples=declared_samples(registry)).model_dump(
        by_alias=True
    )


@app.get("/agent/settings")
async def get_agent_settings() -> dict[str, Any]:
    config = load_config().agent
    default_runtime = build_run_budget(config.runtime)
    return AgentSettingsResponse(
        defaultProvider=config.provider,
        defaultModel=config.model,
        defaultRuntime=default_runtime,
        providers=list_provider_info(default_runtime),
    ).model_dump(by_alias=True)


@app.post("/agent/providers/test")
async def test_agent_provider(payload: ProviderTestRequest) -> dict[str, Any]:
    try:
        service = create_agent_service(payload.provider, model=payload.model, api_key=payload.api_key)
        await service.test_connection()
    except AgentConfigurationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return ProviderTestResponse(ok=True, message="Provider connection is ready").model_dump(by_alias=True)


@app.post("/agent/runs", status_code=202)
async def start_agent_run(
    payload: AgentRunStartRequest,
    x_agent_provider: str | None = Header(default=None),
    x_agent_model: str | None = Header(default=None),
    x_agent_api_key: str | None = Header(default=None),
) -> AgentRunPublic:
    if not payload.intent.strip():
        raise HTTPException(status_code=400, detail="Agent Run intent cannot be empty")
    if not payload.editor_version.code.strip():
        raise HTTPException(status_code=400, detail="Agent Run editor code cannot be empty")

    try:
        config = load_config()
        project_context = load_project_context(config.agent.context_file)
        service = create_agent_service(
            x_agent_provider,
            model=x_agent_model,
            api_key=x_agent_api_key,
        )
        run = await agent_runs.start(
            intent=payload.intent,
            editor_version=payload.editor_version,
            apply_mode=payload.apply_mode,
            budget=(
                payload.runtime_limits.model_copy(deep=True)
                if payload.runtime_limits is not None
                else build_run_budget(config.agent.runtime)
            ),
            provider_name=service.provider_name,
            model=service.model or service.provider_name,
            provider=service.provider,
            project_context=project_context,
        )
    except (AgentConfigurationError, AgentRuntimeTransitionError, ProjectContextError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return run.to_public()


@app.get("/agent/runs/{run_id}")
async def get_agent_run(run_id: str) -> AgentRunPublic:
    run = await agent_runs.get_public(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Agent Run not found")
    return run


@app.post("/agent/runs/{run_id}/input", status_code=202)
async def answer_agent_run(
    run_id: str,
    payload: AgentRunInputRequest,
    x_agent_provider: str | None = Header(default=None),
    x_agent_model: str | None = Header(default=None),
    x_agent_api_key: str | None = Header(default=None),
) -> AgentRunPublic:
    if not payload.question_id.strip() or not payload.answer.strip():
        raise HTTPException(status_code=400, detail="Agent Run input requires a question and answer")
    existing_run = await agent_runs.get(run_id)
    if not existing_run:
        raise HTTPException(status_code=404, detail="Agent Run not found")
    if existing_run.status != "needs_input":
        raise HTTPException(status_code=409, detail="Only paused Agent Runs may receive user input")

    try:
        service = create_agent_service(
            x_agent_provider,
            model=x_agent_model,
            api_key=x_agent_api_key,
        )
        run = await agent_runs.resume(
            run_id,
            question_id=payload.question_id,
            answer=payload.answer,
            provider_name=service.provider_name,
            model=service.model or service.provider_name,
            provider=service.provider,
        )
    except AgentConfigurationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except AgentRuntimeTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if not run:
        raise HTTPException(status_code=404, detail="Agent Run not found")
    return run.to_public()


@app.post("/agent/runs/{run_id}/editor")
async def update_agent_run_editor(
    run_id: str,
    payload: AgentRunEditorUpdateRequest,
    x_agent_provider: str | None = Header(default=None),
    x_agent_model: str | None = Header(default=None),
    x_agent_api_key: str | None = Header(default=None),
) -> AgentRunPublic:
    if not payload.base_hash.strip() or not payload.editor_version.code.strip():
        raise HTTPException(status_code=400, detail="Agent Run editor updates require non-empty code and hashes")
    existing_run = await agent_runs.get(run_id)
    if not existing_run:
        raise HTTPException(status_code=404, detail="Agent Run not found")
    try:
        if existing_run.status == "completed":
            service = create_agent_service(
                x_agent_provider,
                model=x_agent_model,
                api_key=x_agent_api_key,
            )
            run = await agent_runs.reopen_completed(
                run_id,
                base_hash=payload.base_hash,
                editor_version=payload.editor_version,
                provider_name=service.provider_name,
                model=service.model or service.provider_name,
                provider=service.provider,
            )
        else:
            run = await agent_runs.update_editor(
                run_id,
                base_hash=payload.base_hash,
                editor_version=payload.editor_version,
            )
    except AgentConfigurationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except AgentRuntimeTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if not run:
        raise HTTPException(status_code=404, detail="Agent Run not found")
    return run.to_public()


@app.post("/agent/runs/{run_id}/cancel")
async def cancel_agent_run(run_id: str) -> AgentRunPublic:
    run = await agent_runs.cancel(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Agent Run not found")
    return run.to_public()


@app.post("/agent/runs/{run_id}/stage", status_code=201)
async def acknowledge_agent_run_stage(run_id: str, payload: AgentRunStageRequest) -> dict[str, Any]:
    try:
        change = await agent_runs.acknowledge_stage(
            run_id,
            base_hash=payload.base_hash,
            editor_version=payload.editor_version,
        )
    except AgentRuntimeTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if not change:
        raise HTTPException(status_code=404, detail="Agent Run not found")
    return change.model_dump(by_alias=True)


@app.get("/changes/latest")
async def get_latest_change() -> dict[str, Any]:
    return ChangeListResponse(change=latest_change()).model_dump(by_alias=True)


@app.post("/changes/{change_id}/undo")
async def post_change_undo(change_id: str) -> dict[str, Any]:
    change = undo_change(change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    agent_audit.record_change_undone(change)
    return ChangeUndoResponse(change=change, code=change.pre_agent_code).model_dump(by_alias=True)


@app.get("/events")
async def events() -> StreamingResponse:
    queue: asyncio.Queue[SseEvent] = asyncio.Queue()
    clients.add(queue)

    async def stream():
        try:
            yield encode_sse("track", track_event())
            while True:
                event, payload = await queue.get()
                yield encode_sse(event, payload)
        finally:
            clients.discard(queue)

    return StreamingResponse(stream(), media_type="text/event-stream")
