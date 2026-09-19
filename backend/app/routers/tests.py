"""Tests starten, abbrechen und live zusehen."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..deps import DbSession, UiAccess
from ..meldungen import fehler
from ..services import settings_service
from ..services.runner import Busy, result_dict, runner
from ..services.settings_service import SOURCES

router = APIRouter(prefix="/api/tests", tags=["tests"], dependencies=[UiAccess])

KEEPALIVE_SECONDS = 15


class StartIn(BaseModel):
    source: str = Field(default="cloudflare")
    server_id: str | None = Field(default=None, max_length=80)


def start_test(db: Any, source: str, server_id: str | None, trigger: str) -> dict[str, Any]:
    """⚠️ Nur aus ``async def`` aufrufen: Der Test laeuft als Aufgabe in der Ereignisschleife weiter."""
    if source not in SOURCES:
        raise fehler("unknown_source", "This source does not exist.", 422)
    if not settings_service.source_enabled(db, source):
        raise fehler("source_disabled", "This source is turned off.", 409, source=source)
    try:
        result = runner.start(db, source, server_id, trigger=trigger)
    except Busy as exc:
        raise fehler("busy", "A test is already running.", 409) from exc
    return result_dict(result)


@router.post("", status_code=202, summary="Start a test now")
async def start(payload: StartIn, db: DbSession) -> dict[str, Any]:
    return start_test(db, payload.source, payload.server_id, "manual")


@router.post("/cancel", summary="Cancel the running test")
async def cancel() -> dict[str, bool]:
    return {"cancelled": runner.cancel()}


@router.get("/live", summary="What is running right now")
def live() -> dict[str, Any]:
    return runner.live.snapshot() if runner.live else {"type": "snapshot", "running": False}


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, separators=(',', ':'))}\n\n"


@router.get("/stream", summary="Live progress as server-sent events")
async def stream(request: Request) -> StreamingResponse:
    queue = runner.subscribe()

    async def events() -> AsyncIterator[str]:
        try:
            yield _sse(runner.live.snapshot() if runner.live else {"type": "snapshot", "running": False})
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                except TimeoutError:
                    # Ein Kommentar haelt Proxys davon ab, die Verbindung als tot zu schliessen.
                    yield ": keepalive\n\n"
                    continue
                yield _sse(event)
        finally:
            runner.unsubscribe(queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        # X-Accel-Buffering: nginx wuerde den Strom sonst sammeln und erst am Ende schicken.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
