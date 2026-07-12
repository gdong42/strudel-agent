from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .agent import AgentConfigurationError, AgentResponseError, create_agent_service
from .changes import create_change, latest_change, undo_change
from .models import (
    ChangeListResponse,
    ChangeRequest,
    ChangeUndoResponse,
    LOCAL_PROJECT_ID,
    LOCAL_SESSION_ID,
    RuntimeState,
    SnapshotCreateRequest,
    SnapshotListResponse,
    SnapshotRevertResponse,
    TrackPayload,
    TrackSaveRequest,
)
from .providers.base import ProviderError
from .snapshots import create_snapshot, latest_snapshot, list_snapshots, read_snapshot
from .tracks import read_track, write_track


app = FastAPI(title="Strudel Agent")
clients: set[asyncio.Queue[dict[str, Any]]] = set()

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
    payload = track_event()
    for queue in list(clients):
        await queue.put(payload)


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


@app.post("/changes")
async def post_change(payload: ChangeRequest) -> dict[str, Any]:
    if not payload.intent.strip():
        raise HTTPException(status_code=400, detail="Change intent cannot be empty")
    if not payload.current_code.strip():
        raise HTTPException(status_code=400, detail="Current code cannot be empty")
    try:
        generated = await create_agent_service().create_change(payload)
    except AgentConfigurationError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except (AgentResponseError, ProviderError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return create_change(payload, generated).model_dump(by_alias=True)


@app.get("/changes/latest")
async def get_latest_change() -> dict[str, Any]:
    return ChangeListResponse(change=latest_change()).model_dump(by_alias=True)


@app.post("/changes/{change_id}/undo")
async def post_change_undo(change_id: str) -> dict[str, Any]:
    change = undo_change(change_id)
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    return ChangeUndoResponse(change=change, code=change.pre_agent_code).model_dump(by_alias=True)


@app.get("/events")
async def events() -> StreamingResponse:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    clients.add(queue)

    async def stream():
        try:
            yield encode_sse("track", track_event())
            while True:
                payload = await queue.get()
                yield encode_sse("track", payload)
        finally:
            clients.discard(queue)

    return StreamingResponse(stream(), media_type="text/event-stream")
