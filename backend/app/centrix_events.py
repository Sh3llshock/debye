"""Events centrix pushes to reltix (property-management system → Debye).

POST /api/centrix/events  {"type": "asset.error_reported", "unit_id": "unit_4b", "code": "F.28"}
  A connected boiler reported an error: Debye writes the unit's tenant first (agent/proactive.py).
If CENTRIX_WEBHOOK_TOKEN is set, the request needs the header X-Centrix-Token with that value.
"""
from __future__ import annotations

import hmac
import os
from typing import Literal, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/centrix", tags=["centrix"])


class AssetErrorReported(BaseModel):
    type: Literal["asset.error_reported"] = "asset.error_reported"
    unit_id: str
    code: str
    asset_id: Optional[str] = None
    reported_at: Optional[str] = None


async def handle(ev: AssetErrorReported) -> dict:
    from app.agent import proactive

    code = ev.code.strip().upper().replace(" ", "")
    if code.startswith("F") and not code.startswith("F."):
        code = "F." + code[1:]
    try:
        res = await proactive.on_asset_error(ev.unit_id, code, ev.asset_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True, "event": ev.type, "code": code, **res}


@router.post("/events")
async def centrix_event(ev: AssetErrorReported, x_centrix_token: Optional[str] = Header(None)) -> dict:
    token = os.getenv("CENTRIX_WEBHOOK_TOKEN")
    if token and not hmac.compare_digest(token, x_centrix_token or ""):
        raise HTTPException(401, "bad centrix token")
    return await handle(ev)
