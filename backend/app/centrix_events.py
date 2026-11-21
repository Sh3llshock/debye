"""Events centrix pushes to reltix (property-management system → Debye).

POST /api/centrix/events  {"type": "asset.error_reported", "unit_id": "unit_4b", "code": "F.28"}
  (route in triggers.py) A connected boiler reported an error: Debye writes the unit's tenant first
  (agent/proactive.py). Also /demo/trigger/boiler_error.
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel

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


# ---------------------------------------------------------------- HTTP: centrix → Debye
from fastapi import APIRouter, HTTPException  # noqa: E402
from pydantic import BaseModel  # noqa: E402

router = APIRouter(prefix="/api/centrix", tags=["centrix"])


class CentrixEvent(BaseModel):
    type: str
    unit_id: str
    code: str | None = None
    asset_id: str | None = None


@router.post("/events")
async def centrix_event(body: CentrixEvent) -> dict:
    """asset.error_reported: a boiler reported an error and Debye writes the tenant first."""
    if body.type != "asset.error_reported":
        raise HTTPException(422, f"unsupported centrix event {body.type}")
    if not body.code:
        raise HTTPException(422, "asset.error_reported needs a code")
    return await handle(AssetErrorReported(unit_id=body.unit_id, code=body.code, asset_id=body.asset_id))
