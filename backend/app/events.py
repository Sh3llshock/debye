"""In-process event bus + SSE stream at /api/stream (interfaces §3.2).

The stream needs a portal token and is filtered per viewer (app.auth.can_see_event).
Every SSE `data:` line is JSON {"type", "case_id", "event"}.
record_event() is sync and thread-safe: it works from FastAPI's threadpool, from async
endpoints, and from tests/scripts with no running loop (then it only writes the row).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .config import now_iso
from .db import get_session, next_id
from .models import Case, CaseEvent

log = logging.getLogger("debye.events")

_subscribers: set[asyncio.Queue] = set()
_loop: asyncio.AbstractEventLoop | None = None

ACTORS = {"debye", "tenant", "partner", "staff", "system"}


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Called on app startup so sync code in worker threads can publish."""
    global _loop
    _loop = loop


def _broadcast(message: dict) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(message)
        except asyncio.QueueFull:
            log.warning("SSE subscriber queue full, dropping event")


def publish_sync(type: str, case_id: str | None, payload: dict) -> None:
    message = {"type": type, "case_id": case_id, "event": payload}
    loop = _loop
    if loop is None or loop.is_closed():
        return
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:
        _broadcast(message)
    else:
        loop.call_soon_threadsafe(_broadcast, message)


async def publish(type: str, case_id: str | None, payload: dict) -> None:
    publish_sync(type, case_id, payload)


def record_event(case_id: str | None, actor: str, kind: str, summary: str,
                 data: dict | None = None) -> CaseEvent:
    if actor not in ACTORS:
        actor = "system"
    with get_session() as s:
        ev = CaseEvent(id=next_id(s, CaseEvent, "ev"), case_id=case_id, ts=now_iso(),
                       actor=actor, kind=kind, summary=summary, data=data or {})
        s.add(ev)
        if case_id:
            case = s.get(Case, case_id)
            if case:
                case.updated_at = ev.ts
                s.add(case)
        s.commit()
        s.refresh(ev)
    publish_sync(kind, case_id, ev.model_dump())
    return ev


router = APIRouter()


@router.get("/api/stream")
async def stream(request: Request) -> StreamingResponse:
    """Needs a portal token (?token=, EventSource cannot send headers). Staff get every event; a
    partner/technician only events of their own jobs; a tenant only their cases and own chat lines."""
    from .auth import can_see_event, require

    who = require(request)
    q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    _subscribers.add(q)

    async def gen() -> AsyncIterator[str]:
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if can_see_event(who, msg):
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
        finally:
            _subscribers.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
