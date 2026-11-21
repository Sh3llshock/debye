"""Events webhook for API partners (connector-spec §3/§4): POST /api/partners/{partner_id}/events.

The partner's system reports each lifecycle step as a signed status_event. The webhook checks the
HMAC (401), the event shape (422), the order (404) and the lifecycle transition (409), then calls
the SAME service functions the partner page uses, so staff/tenant/partner pages update the same way.

deliver: requested → accepted → scheduled → in_progress → completed → invoiced → closed
sell:    offered   → accepted → signed    → active                              → closed
any:     → declined | needs_info | cancelled
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ValidationError
from sqlmodel import select

from . import notify, rules, services
from .config import now_iso, settings
from .db import get_session
from .events import record_event
from .models import Case, Partner
from .partners import transport
from .partners.manifest import Manifest

log = logging.getLogger("debye.partner_events")

router = APIRouter(tags=["partner-events"])

DELIVER = ["requested", "accepted", "scheduled", "in_progress", "completed", "invoiced", "closed"]
SELL = ["offered", "accepted", "signed", "active", "closed"]
ANY = {"declined", "needs_info", "cancelled"}
TERMINAL = {"declined", "cancelled", "closed"}
MAX_DOC_BYTES = 10 * 1024 * 1024

# Debye case.status → deliver lifecycle state
CASE_TO_LIFECYCLE = {
    "requested": "requested", "accepted": "accepted", "slots_proposed": "accepted",
    "awaiting_technician": "accepted", "scheduled": "scheduled", "completed": "completed",
    "invoiced": "invoiced", "closed": "closed", "partner_declined": "declined",
    "cancelled": "cancelled", "rejected": "cancelled",
}


class EventDocument(BaseModel):
    kind: str
    filename: str
    mime: str = "application/octet-stream"
    url: str | None = None
    base64: str | None = None


class StatusEvent(BaseModel):
    order_ref: str
    partner_id: str
    status: str
    at: str | None = None
    data: dict = {}
    documents: list[EventDocument] = []


# --------------------------------------------------------------------------- lifecycle

def current_state(case: Case, kind: str) -> str:
    order = (case.data or {}).get("partner_order") or {}
    stored = order.get("status")
    if kind == "sell":
        return stored or "offered"
    derived = CASE_TO_LIFECYCLE.get(case.status, stored or "requested")
    if stored == "in_progress" and derived == "scheduled":
        return "in_progress"
    return derived


def allowed(current: str, new: str, kind: str, data: dict) -> bool:
    if current in TERMINAL:
        return False
    if new in ANY:
        return True
    order = SELL if kind == "sell" else DELIVER
    if new not in order or current not in order:
        return False
    i, j = order.index(current), order.index(new)
    if kind == "deliver":
        if new == current == "accepted":
            return bool(data.get("slots"))  # re-propose times
        if current == "scheduled" and new == "completed":
            return True  # in_progress is optional
        if new == "scheduled" and current == "accepted":
            return True
    return j == i + 1


def _set_order_status(case_id: str, status: str, extra: dict | None = None) -> None:
    with get_session() as s:
        case = s.get(Case, case_id)
        order = {**((case.data or {}).get("partner_order") or {}), "status": status,
                 "updated_at": now_iso(), **(extra or {})}
        history = list(order.get("history") or []) + [{"status": status, "at": now_iso()}]
        order["history"] = history[-30:]
        case.data = {**(case.data or {}), "partner_order": order}
        case.updated_at = now_iso()
        s.add(case)
        s.commit()


# --------------------------------------------------------------------------- documents

def _doc_bytes(doc: EventDocument, manifest: Manifest) -> bytes:
    if doc.base64:
        try:
            raw = base64.b64decode(doc.base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, f"document {doc.filename}: invalid base64")
    elif doc.url:
        # only from the partner's own host (no SSRF through the webhook)
        base = urlparse((manifest.transport or {}).get("base_url") or "")
        u = urlparse(doc.url)
        if u.scheme not in ("http", "https") or (u.hostname, u.port) != (base.hostname, base.port):
            raise HTTPException(422, f"document {doc.filename}: url must be on {base.netloc}")
        try:
            r = httpx.get(doc.url, timeout=10.0)
            r.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(422, f"document {doc.filename}: could not fetch {doc.url}")
        raw = r.content
    else:
        raise HTTPException(422, f"document {doc.filename}: url or base64 required")
    if len(raw) > MAX_DOC_BYTES:
        raise HTTPException(422, f"document {doc.filename}: larger than 10 MB")
    return raw


def _docs(ev: StatusEvent, manifest: Manifest) -> dict[str, list[tuple[str, str, bytes]]]:
    out: dict[str, list] = {}
    for d in ev.documents:
        name = Path(d.filename).name or "document"
        out.setdefault(d.kind, []).append((name, d.mime, _doc_bytes(d, manifest)))
    return out


async def record_invoice(case_id: str, partner_id: str, invoice: tuple[str, str, bytes],
                         extracted: dict | None) -> dict:
    """Invoice on its own (the `invoiced` event): store, extract if needed, price-check → invoiced."""
    from . import media
    fname, mime, data = invoice
    folder = Path(settings.storage_dir) / case_id
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / fname
    p.write_bytes(data)
    if not extracted:
        extracted = await media.extract_invoice(str(p))
    with get_session() as s:
        check = rules.price_check(s, partner_id, extracted)
    doc = services.attach_document(case_id, "invoice", p.name, mime or "application/pdf", str(p),
                                   {**extracted, "price_check": check})
    with get_session() as s:
        case = s.get(Case, case_id)
        case.status = "invoiced"
        case.data = {**(case.data or {}), "invoice": {"document_id": doc.id, **extracted},
                     "price_check": check}
        case.updated_at = now_iso()
        s.add(case)
        s.commit()
    record_event(case_id, "debye", "invoice.checked",
                 f"Invoice {extracted.get('invoice_number')} €{extracted.get('gross_eur')} – "
                 f"price check {check['result']}",
                 {"document_id": doc.id, "price_check": check, "invoice": extracted})
    return {"invoice": doc.id, "price_check": check}


# --------------------------------------------------------------------------- handlers

def _find_case(s, partner_id: str, ref: str) -> Case | None:
    for c in s.exec(select(Case).order_by(Case.created_at.desc())).all():
        order = (c.data or {}).get("partner_order") or {}
        if order.get("order_ref") == ref and c.partner_id == partner_id:
            return c
    return None


def _guard(fn, *args):
    try:
        return fn(*args)
    except rules.RuleViolation as rv:
        raise HTTPException(409, rv.message)
    except services.NotFound as nf:
        raise HTTPException(404, str(nf))


async def _deliver(ev: StatusEvent, case: Case, m: Manifest) -> None:
    cid, pid, st = case.id, m.partner_id, ev.status
    data = ev.data or {}
    if st == "accepted":
        if case.status == "requested":
            _guard(services.partner_accept, cid, pid)
            await notify.notify_tenant(cid, "job_accepted", {"partner_id": pid, "partner_name": m.name})
        slots = data.get("slots") or []
        if slots:
            try:
                labelled = services.propose_slots(cid, pid, [{"start": x["start"], "end": x["end"]}
                                                             for x in slots])
            except (KeyError, TypeError, ValueError):
                raise HTTPException(422, "slots: [{start, end}] ISO times required")
            except rules.RuleViolation as rv:
                raise HTTPException(409, rv.message)
            await notify.notify_tenant(cid, "slots_proposed", {"slots": labelled, "partner_name": m.name})
    elif st == "scheduled":
        if case.status != "scheduled":
            start = data.get("slot_start")
            slots = (case.data or {}).get("proposed_slots") or []
            idx = next((i for i, x in enumerate(slots, 1) if x.get("start") == start), None)
            if not idx:
                raise HTTPException(409, "no proposed slot matches slot_start; propose slots first")
            _guard(services.confirm_slot, cid, idx)
    elif st == "in_progress":
        record_event(cid, "partner", "job.in_progress", f"{m.name}: technician on site", {"partner_id": pid})
    elif st == "completed":
        docs = _docs(ev, m)
        photo = (docs.get("photo") or [None])[0]
        invoice = (docs.get("invoice") or [None])[0]
        try:
            result = await services.record_completion(cid, pid, data.get("notes", ""), photo, invoice,
                                                      data.get("invoice") if invoice else None)
        except rules.RuleViolation as rv:
            raise HTTPException(409, rv.message)
        for name, mime, raw in docs.get("visit_report") or []:
            _attach_raw(cid, "report", name, mime, raw)
        await notify.notify_tenant(cid, "job_completed", {"notes": data.get("notes", ""), **result})
        if invoice:
            _set_order_status(cid, "invoiced")
    elif st == "invoiced":
        invoice = (_docs(ev, m).get("invoice") or [None])[0]
        if not invoice:
            raise HTTPException(422, "invoiced needs an invoice document")
        await record_invoice(cid, pid, invoice, data.get("invoice"))
    elif st == "closed":
        record_event(cid, "partner", "order.closed", f"{m.name} closed order {ev.order_ref}", {"partner_id": pid})


def _attach_raw(case_id: str, kind: str, name: str, mime: str, raw: bytes) -> None:
    folder = Path(settings.storage_dir) / case_id
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_bytes(raw)
    services.attach_document(case_id, kind, p.name, mime, str(p))


async def _any(ev: StatusEvent, case: Case, m: Manifest) -> None:
    cid, pid = case.id, m.partner_id
    data = ev.data or {}
    if ev.status in ("declined", "cancelled"):
        reason = data.get("reason") or ("cancelled by the partner" if ev.status == "cancelled" else "")
        if case.partner_id == pid:
            _guard(services.partner_decline, cid, pid, reason)
            await notify.notify_tenant(cid, "partner_declined", {"partner_id": pid, "reason": reason})
        else:
            record_event(cid, "partner", f"order.{ev.status}", f"{m.name} {ev.status} the order"
                         + (f": {reason}" if reason else ""), {"partner_id": pid, "reason": reason})
    elif ev.status == "needs_info":
        q = (data.get("question") or data.get("text") or "").strip()
        if not q:
            raise HTTPException(422, "needs_info needs data.question")
        with get_session() as s:
            c = s.get(Case, cid)
            c.data = {**(c.data or {}), "open_question": {"text": q, "partner_id": pid, "asked_at": now_iso()}}
            s.add(c)
            s.commit()
        record_event(cid, "partner", "job.needs_info", f"{m.name} asks: {q}", {"partner_id": pid, "question": q})


@router.post("/api/partners/{partner_id}/events")
async def partner_event(partner_id: str, request: Request) -> dict:
    raw = await request.body()
    with get_session() as s:
        p = s.get(Partner, partner_id)
        if not p:
            raise HTTPException(404, f"partner {partner_id} not found")
        m = Manifest.model_validate(p.manifest)
    if (m.transport or {}).get("type") != "api":
        raise HTTPException(404, f"{partner_id} has no API transport")
    if not transport.verify(raw, request.headers.get(transport.SIGNATURE_HEADER), transport.secret_for(m)):
        raise HTTPException(401, "bad or missing signature")
    try:
        ev = StatusEvent.model_validate(json.loads(raw or b"{}"))
    except (ValueError, ValidationError) as e:
        raise HTTPException(422, f"invalid status_event: {e}")
    if ev.partner_id != partner_id:
        raise HTTPException(422, "partner_id does not match the URL")
    return await apply_event(m, ev)


async def apply_event(m: Manifest, ev: StatusEvent, via: str = "API") -> dict:
    """One lifecycle step from a partner, whatever the transport (API webhook or WhatsApp reply):
    order lookup (404), transition check (409), then the same services the partner page uses.
    Raises HTTPException; the WhatsApp transport turns its detail into a reply."""
    partner_id = m.partner_id
    if ev.status not in set(DELIVER) | set(SELL) | ANY:
        raise HTTPException(422, f"unknown status {ev.status}")
    with get_session() as s:
        case = _find_case(s, partner_id, ev.order_ref)
        if not case:
            raise HTTPException(404, f"order {ev.order_ref} not found for {partner_id}")
        current = current_state(case, m.kind)
        if not allowed(current, ev.status, m.kind, ev.data or {}):
            raise HTTPException(409, f"transition {current} → {ev.status} not allowed")
    record_event(case.id, "partner", "partner.event",
                 f"{m.name} reported {ev.status} for {ev.order_ref}" + (f" via {via}" if via != "API" else ""),
                 {"partner_id": partner_id, "order_ref": ev.order_ref, "status": ev.status,
                  "at": ev.at, "from": current, "via": via})
    if ev.status in ANY:
        await _any(ev, case, m)
    elif m.kind == "sell":
        from . import triggers  # sell lifecycle: accepted → signed → active (service_contract)
        await triggers.on_sell_event(ev, case, m)
    else:
        await _deliver(ev, case, m)
    stored = (((services.get_case(case.id).data or {}).get("partner_order")) or {}).get("status")
    if ev.status != "needs_info" and not (ev.status == "completed" and stored == "invoiced"):
        _set_order_status(case.id, ev.status)
    fresh = services.get_case(case.id)
    return {"ok": True, "order_ref": ev.order_ref, "status": current_state(fresh, m.kind),
            "case_status": fresh.status}
