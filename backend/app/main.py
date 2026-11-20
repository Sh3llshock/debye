"""FastAPI app: APIs, SSE, files, demo controls, agent routers (if present), built frontend at /.

Run from backend/:  uvicorn app.main:app --reload
"""
from __future__ import annotations

import asyncio
import importlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import demo, events, partner_api, staff_api
from .config import settings
from .db import get_session
from .models import Document
from .seed import seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("debye")

# Modules owned by agent-whatsapp. Each may expose `router = APIRouter()`; included if present.
OPTIONAL_ROUTER_MODULES = ["app.channels.whatsapp", "app.channels.webchat", "app.router"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    events.bind_loop(asyncio.get_running_loop())
    seed()
    yield


app = FastAPI(title="Debye (AI assistant)", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(events.router)
app.include_router(staff_api.router)
app.include_router(partner_api.router)
app.include_router(demo.router)

for mod_name in OPTIONAL_ROUTER_MODULES:
    try:
        mod = importlib.import_module(mod_name)
    except ModuleNotFoundError as e:
        if e.name and mod_name.startswith(e.name):
            continue  # module not written yet
        log.exception("failed to import %s", mod_name)
        continue
    except Exception:
        log.exception("failed to import %s", mod_name)
        continue
    r = getattr(mod, "router", None)
    if isinstance(r, APIRouter):
        app.include_router(r)
        log.info("included router from %s", mod_name)


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
    if full_path.startswith(("api/", "files/", "demo/", "webhooks/", "ws/")):
        raise HTTPException(404, "not found")
    if not _dist.exists():
        return {"service": "Debye backend", "hint": "frontend/dist not built; see /docs"}
    candidate = (_dist / full_path).resolve()
    if full_path and candidate.is_file() and _dist.resolve() in candidate.parents:
        return FileResponse(candidate)
    return FileResponse(_dist / "index.html")
