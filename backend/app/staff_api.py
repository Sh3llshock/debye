"""Staff page API (interfaces §4) – the centrix stand-in."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from . import notify, rules, services
from .db import get_session
from .models import (Asset, Case, CaseContact, CaseEvent, Consent, Contact, Document, Message,
                     Partner, Property, Unit)

router = APIRouter(prefix="/api/staff", tags=["staff"])


# --------------------------------------------------------------------------- serializers

def doc_view(d: Document) -> dict:
    return {"document_id": d.id, "kind": d.kind, "filename": d.filename, "mime": d.mime,
            "url": f"/files/{d.id}", "case_id": d.case_id, "unit_id": d.unit_id,
            "created_at": d.created_at, "extracted": d.extracted or {}}


def case_summary(s, c: Case) -> dict:
    prop = s.get(Property, c.property_id) if c.property_id else None
    partner = s.get(Partner, c.partner_id) if c.partner_id else None
    return {
        "case_id": c.id, "type": c.type, "title": c.title, "status": c.status,
        "priority": c.priority, "unit_id": c.unit_id,
        "error_code": c.error_code, "error_label": services.error_label(c.error_code),
        "trade": services.case_trade(c),
        "resolution": (c.data or {}).get("resolution"),
        "saving_eur": (c.data or {}).get("saving_eur"),
        # invoice above the approved amount (or prices above the list): staff should look
        "price_flagged": ((c.data or {}).get("price_check") or {}).get("result") == "flagged",
        "technician": ({"tech_id": c.data["technician"]["tech_id"], "name": c.data["technician"]["name"]}
                       if (c.data or {}).get("technician") else None),
        "address": prop.address if prop else None,
        "partner": {"partner_id": partner.id, "name": partner.manifest.get("name")} if partner else None,
        "created_at": c.created_at, "updated_at": c.updated_at,
    }


def _approval_card(s, c: Case, approval: dict) -> dict:
    """approval block for the staff card: partner + estimate, and while pending a suggested
    technician/slot (what auto-assign would pick for the earliest free slot)."""
    data = c.data or {}
    out = {"required": approval.get("required", False), "rule": approval.get("rule"),
           "granted": approval.get("granted", False), "rejected": bool(approval.get("rejected")),
           "reason": approval.get("reason"), "amount_eur": c.estimated_cost_eur,
           "granted_by": approval.get("granted_by"), "granted_at": approval.get("granted_at"),
           "rejected_by": approval.get("rejected_by"),
           "partner": None, "suggested_technician": None, "suggested_slot": None,
           "trade": services.case_trade(c), "diagnosis": None}
    diag = data.get("diagnosis")
    if diag:
        out["diagnosis"] = {"cause_id": diag.get("cause_id"), "label": diag.get("label"),
                            "confidence": diag.get("confidence"), "reasoning": diag.get("reasoning"),
                            "outcome": diag.get("outcome"), "estimated_cost_eur": diag.get("estimated_cost_eur")}
    pid = c.partner_id or data.get("pending_partner_id") or \
        ((data.get("ranking") or [{}])[0].get("partner_id"))
    p = s.get(Partner, pid) if pid else None
    if p:
        out["partner"] = {"partner_id": p.id, "name": p.manifest.get("name")}
    if c.status in ("approval_pending", "awaiting_approval") and p:
        sug = services.suggest_technician(c.id, p.id)
        if sug:
            out["suggested_technician"], out["suggested_slot"] = sug["technician"], sug["slot"]
    return out


def case_detail(s, c: Case) -> dict:
    out = case_summary(s, c)
    data = c.data or {}
    links = s.exec(select(CaseContact).where(CaseContact.case_id == c.id)).all()
    reporters = []
    for l in links:
        ct = s.get(Contact, l.contact_id)
        if ct:
            reporters.append({"contact_id": ct.id, "name": ct.name, "unit_id": ct.unit_id,
                              "relation": l.relation})
    reporters.sort(key=lambda r: r["relation"] != "reporter")
    asset = s.get(Asset, c.asset_id) if c.asset_id else None
    approval = data.get("approval")
    if not approval:
        pid = c.partner_id or data.get("pending_partner_id") or \
            ((data.get("ranking") or [{}])[0].get("partner_id"))
        approval = rules.approval_status(s, c, pid) if pid else {"required": False, "rule": "not evaluated yet"}
    consents = s.exec(select(Consent).where(Consent.case_id == c.id)).all()
    docs = s.exec(select(Document).where(Document.case_id == c.id)).all()
    events = s.exec(select(CaseEvent).where(CaseEvent.case_id == c.id).order_by(CaseEvent.ts, CaseEvent.id)).all()
    msgs = s.exec(select(Message).where(Message.case_id == c.id).order_by(Message.ts, Message.id)).all()
    contact_names = {}
    for m in msgs:
        if m.contact_id and m.contact_id not in contact_names:
            ct = s.get(Contact, m.contact_id)
            contact_names[m.contact_id] = ct.name if ct else m.contact_id
    out.update({
        "summary": c.summary, "symptoms": c.symptoms,
        "trade": services.case_trade(c),
        "diagnosis": data.get("diagnosis"),
        "caretaker": data.get("caretaker"),
        "resolution": data.get("resolution"),
        "saving_eur": data.get("saving_eur"),
        "reporters": reporters,
        "asset": {"asset_id": asset.id, "type": asset.type, "make": asset.make, "model": asset.model,
                  "error_code": c.error_code,
                  "error_label": services.error_label(c.error_code, asset.known_error_codes),
                  # kept for older frontend code; same text as error_label
                  "error_meaning": services.error_label(c.error_code, asset.known_error_codes)} if asset
        else {"error_code": c.error_code, "error_label": services.error_label(c.error_code)},
        "cost_bearer": c.cost_bearer,
        "estimated_cost_eur": c.estimated_cost_eur,
        "approval": _approval_card(s, c, approval),
        "slot": {"start": c.slot_start, "end": c.slot_end} if c.slot_start else None,
        "technician": ({"tech_id": data["technician"]["tech_id"], "name": data["technician"]["name"]}
                       if data.get("technician") else None),
        "proposed_slots": data.get("proposed_slots") or [],
        "zero_forms": {"prefilled": data.get("prefilled_fields", []),
                       "tenant_inputs": data.get("tenant_inputs", [])},
        "ranking": data.get("ranking") or [],
        "consents": [{"consent_id": k.id, "contact_id": k.contact_id, "partner_id": k.partner_id,
                      "data_shared": k.data_shared, "given_at": k.given_at, "channel": k.channel,
                      "purpose": k.purpose, "revoked_at": k.revoked_at} for k in consents],
        "documents": [doc_view(d) for d in docs],
        "events": [{"id": e.id, "ts": e.ts, "actor": e.actor, "kind": e.kind, "summary": e.summary,
                    "data": e.data} for e in events],
        "messages": [{"ts": m.ts, "direction": m.direction,
                      "contact": contact_names.get(m.contact_id), "contact_id": m.contact_id,
                      "text": m.text,
                      "media": [{"document_id": d, "url": f"/files/{d}"} for d in (m.media_ids or [])]}
                     for m in msgs],
        "price_check": data.get("price_check"),
        "result": data.get("result"),
        "closed_at": c.closed_at,
        "created_at": c.created_at,
    })
    return out


def unit_summary(s, u: Unit) -> dict:
    prop = s.get(Property, u.property_id)
    tenant = s.exec(select(Contact).where(Contact.unit_id == u.id, Contact.role == "tenant")).first()
    cases = s.exec(select(Case).where(Case.unit_id == u.id)).all()
    return {"unit_id": u.id, "property_id": u.property_id, "address": prop.address if prop else None,
            "floor": u.floor, "size_sqm": u.size_sqm, "rooms": u.rooms,
            "tenant": {"contact_id": tenant.id, "name": tenant.name} if tenant else None,
            "open_cases": sum(1 for c in cases if c.status not in services.OPEN_STATUSES_EXCLUDED)}


def unit_detail(s, u: Unit) -> dict:
    out = unit_summary(s, u)
    prop = s.get(Property, u.property_id)
    assets = [a for a in s.exec(select(Asset).where(Asset.property_id == u.property_id)).all()
              if a.unit_id in (None, u.id)]
    tenant = s.exec(select(Contact).where(Contact.unit_id == u.id, Contact.role == "tenant")).first()
    from .models import Contract
    lease = s.exec(select(Contract).where(Contract.unit_id == u.id, Contract.type == "lease")).first()
    docs = s.exec(select(Document).where(Document.unit_id == u.id)).all()
    # cases touching this unit: own cases + cases where a contact of this unit is linked
    case_ids = {c.id for c in s.exec(select(Case).where(Case.unit_id == u.id)).all()}
    unit_contacts = [c.id for c in s.exec(select(Contact).where(Contact.unit_id == u.id)).all()]
    if unit_contacts:
        for l in s.exec(select(CaseContact).where(CaseContact.contact_id.in_(unit_contacts))).all():
            case_ids.add(l.case_id)
    cases = sorted((s.get(Case, i) for i in case_ids), key=lambda c: c.created_at, reverse=True)
    out.update({
        "property": prop.model_dump() if prop else None,
        "unit": u.model_dump(),
        "assets": [a.model_dump() for a in assets],
        "tenant": tenant.model_dump() if tenant else None,
        "lease": lease.model_dump() if lease else None,
        "documents": [doc_view(d) for d in sorted(docs, key=lambda d: d.created_at or "", reverse=True)],
        "cases": [case_summary(s, c) for c in cases],
    })
    from .triggers import unit_service_contracts  # sell partners' results (reltix shape)
    out["service_contracts"] = unit_service_contracts(s, u.id)
    return out


# --------------------------------------------------------------------------- routes

@router.get("/units")
def list_units() -> list[dict]:
    with get_session() as s:
        return [unit_summary(s, u) for u in s.exec(select(Unit).order_by(Unit.id)).all()]


@router.get("/units/{unit_id}")
def get_unit(unit_id: str) -> dict:
    with get_session() as s:
        u = s.get(Unit, unit_id)
        if not u:
            raise HTTPException(404, f"unit {unit_id} not found")
        return unit_detail(s, u)


@router.get("/cases")
def list_cases() -> list[dict]:
    with get_session() as s:
        cases = s.exec(select(Case).order_by(Case.created_at.desc(), Case.id.desc())).all()
        return [case_summary(s, c) for c in cases]


@router.get("/cases/{case_id}")
def get_case(case_id: str) -> dict:
    with get_session() as s:
        c = s.get(Case, case_id)
        if not c:
            raise HTTPException(404, f"case {case_id} not found")
        return case_detail(s, c)


class ApproveBody(BaseModel):
    staff_name: str | None = None  # who clicked; default: the seeded property manager


@router.post("/cases/{case_id}/approve")
async def approve(case_id: str, body: ApproveBody | None = None) -> dict:
    if services.get_case(case_id) is None:
        raise HTTPException(404, f"case {case_id} not found")
    try:
        result = services.approve_case(case_id, staff_name=body.staff_name if body else None)
    except rules.RuleViolation as rv:
        raise HTTPException(409, rv.message)
    await notify.notify_tenant(case_id, "approval_granted",
                               {"partner_name": result.get("partner_name"),
                                "dispatched": result.get("dispatched")})
    with get_session() as s:
        return case_detail(s, s.get(Case, case_id))


class RejectBody(BaseModel):
    reason: str = ""
    staff_name: str | None = None


@router.post("/cases/{case_id}/reject")
async def reject(case_id: str, body: RejectBody | None = None) -> dict:
    if services.get_case(case_id) is None:
        raise HTTPException(404, f"case {case_id} not found")
    reason = body.reason if body else ""
    try:
        result = services.reject_case(case_id, reason, staff_name=body.staff_name if body else None)
    except rules.RuleViolation as rv:
        raise HTTPException(409, rv.message)
    await notify.notify_tenant(case_id, "approval_rejected",
                               {"partner_name": result.get("partner_name"), "reason": reason})
    with get_session() as s:
        return case_detail(s, s.get(Case, case_id))


# --------------------------------------------------------------------------- partner review (feature 1)

def partner_application(s, p: Partner) -> dict:
    from .partners import verification
    checks = services.partner_precheck(s, p)
    onb = (p.manifest or {}).get("onboarding") or {}
    return {"partner_id": p.id, "name": p.manifest.get("name"), "status": p.status or "active",
            "applied_at": onb.get("at"), "company": onb.get("company") or {},
            "manifest": p.manifest, "review": p.review or {},
            "documents": [{**doc_view(d), "doc_type": (d.extracted or {}).get("doc_type"),
                           "label": verification.DOC_TYPES.get((d.extracted or {}).get("doc_type"), d.filename)}
                          for d in services.partner_documents(s, p.id)],
            "precheck": checks, "precheck_result": verification.summary(checks)}


@router.get("/partners/applications")
def partner_applications() -> list[dict]:
    """Partners waiting for review (self-onboarded on /partners/join), newest first."""
    with get_session() as s:
        ps = [p for p in s.exec(select(Partner)).all() if (p.status or "active") == "pending_review"]
        out = [partner_application(s, p) for p in ps]
    return sorted(out, key=lambda a: a.get("applied_at") or "", reverse=True)


@router.get("/partners/{partner_id}/application")
def partner_application_detail(partner_id: str) -> dict:
    with get_session() as s:
        p = s.get(Partner, partner_id)
        if not p:
            raise HTTPException(404, f"partner {partner_id} not found")
        return partner_application(s, p)


class PartnerDecisionBody(BaseModel):
    reason: str = ""
    staff_name: str | None = None


@router.post("/partners/{partner_id}/approve")
def approve_partner(partner_id: str, body: PartnerDecisionBody | None = None) -> dict:
    try:
        return services.approve_partner(partner_id, staff_name=body.staff_name if body else None)
    except services.NotFound as nf:
        raise HTTPException(404, str(nf))
    except rules.RuleViolation as rv:
        raise HTTPException(409, rv.message)


@router.post("/partners/{partner_id}/reject")
def reject_partner(partner_id: str, body: PartnerDecisionBody) -> dict:
    try:
        return services.reject_partner(partner_id, body.reason, staff_name=body.staff_name)
    except services.NotFound as nf:
        raise HTTPException(404, str(nf))
    except rules.RuleViolation as rv:
        raise HTTPException(422 if rv.code == "reason_required" else 409, rv.message)
