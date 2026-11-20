"""Technician phone page API (interfaces §Technician flow). Consented context only."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from . import notify, rules, services
from .db import get_session
from .models import Case, Partner, Technician
from .partner_api import job_detail, job_summary

router = APIRouter(prefix="/api/tech", tags=["technician"])

TECH_STATUSES = {"slots_proposed", "awaiting_technician", "scheduled", "completed", "invoiced",
                 "closed", "reopened"}


def _tech(s, tech_id: str) -> Technician:
    t = s.get(Technician, tech_id)
    if not t:
        raise HTTPException(404, f"technician {tech_id} not found")
    return t


def _assigned(c: Case | None, tech_id: str) -> bool:
    return bool(c) and ((c.data or {}).get("technician") or {}).get("tech_id") == tech_id


def _tech_view(s, c: Case, tech: Technician, detail: bool) -> dict:
    base = (job_detail if detail else job_summary)(s, c, tech.partner_id)
    base["chosen_slot"] = {"start": c.slot_start, "end": c.slot_end} if c.slot_start else None
    base["needs_confirmation"] = c.status == "awaiting_technician"
    return base


@router.get("/{tech_id}")
def get_tech(tech_id: str) -> dict:
    with get_session() as s:
        t = _tech(s, tech_id)
        p = s.get(Partner, t.partner_id)
        return {"tech_id": t.id, "name": t.name, "partner_id": t.partner_id,
                "partner_name": p.manifest.get("name") if p else None, "skills": t.skills}


@router.get("/{tech_id}/jobs")
def list_jobs(tech_id: str) -> list[dict]:
    with get_session() as s:
        tech = _tech(s, tech_id)
        cases = s.exec(select(Case).order_by(Case.created_at.desc())).all()
        return [_tech_view(s, c, tech, detail=False) for c in cases
                if _assigned(c, tech_id) and c.status in TECH_STATUSES]


@router.get("/{tech_id}/jobs/{case_id}")
def get_job(tech_id: str, case_id: str) -> dict:
    with get_session() as s:
        tech = _tech(s, tech_id)
        c = s.get(Case, case_id)
        if not _assigned(c, tech_id):
            raise HTTPException(404, f"job {case_id} not found for {tech_id}")
        return _tech_view(s, c, tech, detail=True)


@router.post("/{tech_id}/jobs/{case_id}/confirm")
async def confirm(tech_id: str, case_id: str) -> dict:
    with get_session() as s:
        _tech(s, tech_id)
        if not _assigned(s.get(Case, case_id), tech_id):
            raise HTTPException(404, f"job {case_id} not found for {tech_id}")
    try:
        result = services.technician_confirm(case_id, tech_id)
    except rules.RuleViolation as rv:
        raise HTTPException(409, rv.message)
    await notify.notify_tenant(case_id, "technician_confirmed",
                               {"technician_name": result["technician"]["name"],
                                "tech_id": tech_id, "slot": result["slot"]})
    return get_job(tech_id, case_id)
