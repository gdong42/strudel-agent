from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .tracks import read_track, write_track


class TrackSaveRequest(BaseModel):
    code: str


app = FastAPI(title="Strudel Agent")
clients: set[asyncio.Queue[dict[str, Any]]] = set()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def track_event() -> dict[str, Any]:
    return {"code": read_track(), "updatedAt": int(time.time() * 1000)}


def encode_sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def broadcast_track() -> None:
    payload = track_event()
    for queue in list(clients):
        await queue.put(payload)


@app.get("/track")
async def get_track() -> dict[str, Any]:
    return track_event()


@app.post("/track", status_code=204)
async def save_track(payload: TrackSaveRequest) -> None:
    if not payload.code.strip():
        raise HTTPException(status_code=400, detail="Refusing to write an empty track")

    write_track(payload.code)
    await broadcast_track()


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
