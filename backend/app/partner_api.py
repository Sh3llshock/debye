"""Partner page API (interfaces §4). The partner sees only consented context."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import select

from . import notify, rules, services
from .db import get_session
from .models import Asset, Case, CaseEvent, Contact, Document, Partner, Property, Unit

router = APIRouter(prefix="/api/partner", tags=["partner"])
list_router = APIRouter(tags=["partner"])  # GET /api/partners (staff "Partners" page)

VISIBLE_STATUSES = {"requested", "accepted", "slots_proposed", "awaiting_technician", "scheduled",
                    "completed", "invoiced", "closed", "reopened"}
PARTNER_EVENT_KINDS = {"job.sent", "job.accepted", "job.declined", "slot.proposed",
                       "slot.confirmed", "technician.confirmed", "job.completed", "invoice.checked",
                       "case.closed", "case.reopened", "tenant.confirmed_fixed"}


def technician_view(c: Case) -> dict | None:
    t = (c.data or {}).get("technician")
    return {"tech_id": t["tech_id"], "name": t["name"]} if t else None


def _partner(s, partner_id: str) -> Partner:
    p = s.get(Partner, partner_id)
    if not p:
        raise HTTPException(404, f"partner {partner_id} not found")
    return p


def _job_case(s, partner_id: str, case_id: str) -> Case:
    c = s.get(Case, case_id)
    declined = (c.data or {}).get("declined_by", []) if c else []
    if not c or (c.partner_id != partner_id and partner_id not in declined):
        raise HTTPException(404, f"job {case_id} not found for {partner_id}")
    return c


def _job_status(c: Case, partner_id: str) -> str:
    if c.partner_id != partner_id and partner_id in (c.data or {}).get("declined_by", []):
        return "declined"
    return c.status


def job_summary(s, c: Case, partner_id: str) -> dict:
    prop = s.get(Property, c.property_id) if c.property_id else None
    unit = s.get(Unit, c.unit_id) if c.unit_id else None
    asset = s.get(Asset, c.asset_id) if c.asset_id else None
    fields = rules.consented_fields(s, c.id, partner_id)
    return {
        "case_id": c.id, "type": c.type, "title": c.title, "status": _job_status(c, partner_id),
        "priority": c.priority,
        "address": prop.address if prop and "address" in fields else None,
        "postcode": prop.postcode if prop else None,
        "floor": unit.floor if unit else None,
        "asset": {"type": asset.type, "make": asset.make, "model": asset.model} if asset else None,
        "error_code": c.error_code,
        "error_label": services.error_label(c.error_code, asset.known_error_codes if asset else None),
        "slot": {"start": c.slot_start, "end": c.slot_end} if c.slot_start else None,
        "technician": technician_view(c),
        "created_at": c.created_at, "updated_at": c.updated_at,
    }


def _approval_view(a: dict) -> dict:
    """Partner-facing approval line, e.g. "Approved by reltix staff (Anna Becker)"."""
    if a.get("granted"):
        who = a.get("granted_by")
        text = "Approved by reltix staff" + (f" ({who})" if who else "")
    elif a and not a.get("required", True):
        text = "Approved automatically (" + (a.get("rule") or "framework limit") + ")"
    else:
        text = None
    return {"granted": bool(a.get("granted")) or (bool(a) and not a.get("required", True)),
            "granted_by": a.get("granted_by"), "granted_at": a.get("granted_at"), "text": text}


def job_detail(s, c: Case, partner_id: str) -> dict:
    out = job_summary(s, c, partner_id)
    fields = rules.consented_fields(s, c.id, partner_id)
    data = c.data or {}
    asset = s.get(Asset, c.asset_id) if c.asset_id else None
    tenant = s.get(Contact, c.reporter_contact_id) if c.reporter_contact_id else None
    tenant_view = None
    if tenant and ({"name", "phone"} & fields):
        tenant_view = {"name": tenant.name if "name" in fields else None,
                       "phone": tenant.phone_e164 if "phone" in fields else None}
    docs = s.exec(select(Document).where(Document.case_id == c.id)).all()
    photos = [d for d in docs if d.kind == "photo"]
    partner_docs = [d for d in docs if d.kind in ("invoice", "report")]
    # tenant photos only with consent; the partner's own "after_" photos always
    visible_photos = [d for d in photos if "photos" in fields or d.filename.startswith("after_")]
    events = s.exec(select(CaseEvent).where(CaseEvent.case_id == c.id)
                    .order_by(CaseEvent.ts, CaseEvent.id)).all()
    out.update({
        "summary": c.summary,
        "symptoms": c.symptoms,
        "asset": ({"type": asset.type, "make": asset.make, "model": asset.model,
                   "installed": asset.installed, "last_service": asset.last_service,
                   "error_label": services.error_label(c.error_code, asset.known_error_codes),
                   "error_meaning": services.error_label(c.error_code, asset.known_error_codes)}
                  if asset else None),
        "tenant": tenant_view,
        "consented_fields": sorted(fields),
        "photos": [{"document_id": d.id, "url": f"/files/{d.id}", "filename": d.filename}
                   for d in visible_photos],
        "proposed_slots": data.get("proposed_slots") or [],
        "confirmed_slot": out["slot"],
        "estimated_cost_eur": c.estimated_cost_eur,
        "documents": [{"document_id": d.id, "kind": d.kind, "filename": d.filename,
                       "url": f"/files/{d.id}", "extracted": d.extracted or {}} for d in partner_docs],
        "completion": data.get("completion"),
        "approval": _approval_view(data.get("approval") or {}),
        "price_check": data.get("price_check"),
        "events": [{"ts": e.ts, "actor": e.actor, "kind": e.kind, "summary": e.summary}
                   for e in events if e.kind in PARTNER_EVENT_KINDS],
    })
    return out


def _detail(case_id: str, partner_id: str) -> dict:
    with get_session() as s:
        return job_detail(s, s.get(Case, case_id), partner_id)


def _guard(fn, *args):
    try:
        return fn(*args)
    except rules.RuleViolation as rv:
        raise HTTPException(409, rv.message)
    except services.NotFound as nf:
        raise HTTPException(404, str(nf))


# --------------------------------------------------------------------------- routes

def _partner_view(s, p: Partner, with_counts: bool = False) -> dict:
    staff = s.exec(select(Contact).where(Contact.partner_id == p.id)).all()
    review = p.review or {}
    out = {**p.manifest, "active": p.active, "status": p.status or "active",
           "review": {"reviewer": review.get("reviewer"), "decided_at": review.get("decided_at"),
                      "reason": review.get("reason")},
           "staff": [{"contact_id": c.id, "name": c.name} for c in staff]}
    if with_counts:
        from .models import Technician
        cases = s.exec(select(Case).where(Case.partner_id == p.id)).all()
        out["open_jobs"] = sum(1 for c in cases if c.status not in services.OPEN_STATUSES_EXCLUDED)
        out["total_jobs"] = len(cases)
        out["technicians"] = [{"tech_id": t.id, "name": t.name, "skills": t.skills}
                              for t in s.exec(select(Technician).where(Technician.partner_id == p.id)
                                              .order_by(Technician.id)).all()]
    return out


@list_router.get("/api/partners")
def list_partners() -> list[dict]:
    """One entry per partner: the manifest + {active, staff, open_jobs, total_jobs, technicians}."""
    with get_session() as s:
        return [_partner_view(s, p, with_counts=True)
                for p in s.exec(select(Partner).order_by(Partner.id)).all()]


@router.get("/{partner_id}")
def get_partner(partner_id: str) -> dict:
    with get_session() as s:
        return _partner_view(s, _partner(s, partner_id))


@router.get("/{partner_id}/jobs")
def list_jobs(partner_id: str) -> list[dict]:
    with get_session() as s:
        _partner(s, partner_id)
        cases = s.exec(select(Case).order_by(Case.created_at.desc())).all()
        out = []
        for c in cases:
            mine = c.partner_id == partner_id and c.status in VISIBLE_STATUSES
            declined = partner_id in (c.data or {}).get("declined_by", [])
            if mine or declined:
                out.append(job_summary(s, c, partner_id))
        return out


@router.get("/{partner_id}/jobs/{case_id}")
def get_job(partner_id: str, case_id: str) -> dict:
    with get_session() as s:
        _partner(s, partner_id)
        return job_detail(s, _job_case(s, partner_id, case_id), partner_id)


@router.post("/{partner_id}/jobs/{case_id}/accept")
async def accept(partner_id: str, case_id: str) -> dict:
    with get_session() as s:
        _job_case(s, partner_id, case_id)
    _guard(services.partner_accept, case_id, partner_id)
    with get_session() as s:
        name = s.get(Partner, partner_id).manifest.get("name")
    await notify.notify_tenant(case_id, "job_accepted", {"partner_id": partner_id, "partner_name": name})
    return _detail(case_id, partner_id)


class DeclineBody(BaseModel):
    reason: str = ""


@router.post("/{partner_id}/jobs/{case_id}/decline")
async def decline(partner_id: str, case_id: str, body: DeclineBody | None = None) -> dict:
    with get_session() as s:
        _job_case(s, partner_id, case_id)
    reason = body.reason if body else ""
    _guard(services.partner_decline, case_id, partner_id, reason)
    await notify.notify_tenant(case_id, "partner_declined", {"partner_id": partner_id, "reason": reason})
    return _detail(case_id, partner_id)


class Slot(BaseModel):
    start: str
    end: str


class SlotsBody(BaseModel):
    tech_id: str | None = None  # optional: without it the dispatcher auto-assigns the best free technician
    slots: list[Slot]


@router.get("/{partner_id}/technicians")
def technicians(partner_id: str) -> list[dict]:
    with get_session() as s:
        _partner(s, partner_id)
    return services.get_technicians(partner_id)


@router.post("/{partner_id}/jobs/{case_id}/slots")
async def slots(partner_id: str, case_id: str, body: SlotsBody) -> dict:
    with get_session() as s:
        _job_case(s, partner_id, case_id)
    if not body.slots:
        raise HTTPException(422, "at least one slot required")
    try:
        labelled = services.propose_slots(case_id, partner_id,
                                          [sl.model_dump() for sl in body.slots], body.tech_id)
    except rules.RuleViolation as rv:
        raise HTTPException(409, rv.message)
    except ValueError as e:
        raise HTTPException(422, f"bad slot time: {e}")
    with get_session() as s:
        name = s.get(Partner, partner_id).manifest.get("name")
    tech_id = ((services.get_case(case_id).data or {}).get("technician") or {}).get("tech_id")
    tech = services.get_technician(tech_id) if tech_id else None
    await notify.notify_tenant(case_id, "slots_proposed",
                               {"slots": labelled, "partner_name": name,
                                "technician_name": tech.name if tech else None})
    return _detail(case_id, partner_id)


@router.post("/{partner_id}/jobs/{case_id}/complete")
async def complete(partner_id: str, case_id: str,
                   notes: str = Form(""),
                   photo: UploadFile | None = File(None),
                   invoice: UploadFile | None = File(None)) -> dict:
    with get_session() as s:
        _job_case(s, partner_id, case_id)
    photo_t = (photo.filename or "photo.jpg", photo.content_type, await photo.read()) if photo else None
    invoice_t = (invoice.filename or "invoice.pdf", invoice.content_type, await invoice.read()) if invoice else None
    try:
        result = await services.record_completion(case_id, partner_id, notes, photo_t, invoice_t)
    except rules.RuleViolation as rv:
        raise HTTPException(409, rv.message)
    await notify.notify_tenant(case_id, "job_completed", {"notes": notes, **result})
    return _detail(case_id, partner_id)
