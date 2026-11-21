"""FastAPI app: APIs, SSE, files, demo controls, agent routers (if present), built frontend at /.

Run from backend/:  uvicorn app.main:app --reload
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import demo, events, onboard_api, partner_api, staff_api, tech_api
from .config import settings
from .db import get_session
from .models import Document
from .seed import seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("debye")



@asynccontextmanager
async def lifespan(app: FastAPI):
    events.bind_loop(asyncio.get_running_loop())
    seed(reset=settings.reseed_on_boot)
    yield


app = FastAPI(title="Debye (AI assistant)", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(events.router)
app.include_router(staff_api.router)
app.include_router(onboard_api.router)
app.include_router(partner_api.list_router)
app.include_router(partner_api.router)
app.include_router(tech_api.router)
app.include_router(demo.router)

# Agent-whatsapp routers (interfaces §3.3b). Guarded until the agent PR lands.
try:
    from app.channels.whatsapp import router as whatsapp_router  # /webhooks/whatsapp (+ /_outbox)
    app.include_router(whatsapp_router)
except ImportError as e:
    log.warning("whatsapp router not mounted: %s", e)
try:
    from app.channels.webchat import router as webchat_router  # /ws/chat/{id}, /chat/{id}
    app.include_router(webchat_router)
except ImportError as e:
    log.warning("webchat router not mounted: %s", e)
try:
    from app.channels.web import router as web_router  # /api/tenant/* (tenant web portal)
    app.include_router(web_router)
except ImportError as e:
    log.warning("tenant web router not mounted: %s", e)
try:
    from app.voice import router as voice_router  # /api/voice/*, /call (ElevenLabs calls)
    app.include_router(voice_router)
except ImportError as e:
    log.warning("voice router not mounted: %s", e)

@app.get("/healthz")
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "demo_mode": settings.demo_mode}


@app.get("/files/{document_id}")
def get_file(document_id: str):
    with get_session() as s:
        d = s.get(Document, document_id)
    if not d or not Path(d.path).exists():
        raise HTTPException(404, "file not found")
    return FileResponse(d.path, media_type=d.mime, filename=d.filename,
                        content_disposition_type="inline")


# --- built frontend (SPA): /staff, /partner/... all serve index.html -------------------
_dist = Path(settings.frontend_dist)


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith(("api/", "files/", "demo/", "webhooks/", "ws/", "chat/")):  # noqa: E501
        raise HTTPException(404, "not found")
    if not _dist.exists():
        return {"service": "Debye backend", "hint": "frontend/dist not built; see /docs"}
    candidate = (_dist / full_path).resolve()
    if full_path and candidate.is_file() and _dist.resolve() in candidate.parents:
        return FileResponse(candidate)
    return FileResponse(_dist / "index.html")
