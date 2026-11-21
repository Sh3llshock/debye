"""centrix moments → partners (connector-spec §2 `triggers`, §7 result).

A centrix event (e.g. tenant.move_in {unit_id, contact_id, move_in_date}) is matched against every
active partner manifest whose `triggers` contain it, filtered with the manifest's `eligibility`
rules (partners/eligibility.evaluate), and opens one case of the manifest's `category` per eligible
partner. Nothing here knows about fibre: the manifest decides the offers, the context fields, the
transport and the lifecycle.

Sell flow (kind "sell"):  offered → (tenant picks an offer, consents) → order via transport
→ accepted → signed → active. On active the result is written to the unit in reltix's shape:
{unit_id, contact_id, service_contract: {partner, category, product, status, start,
 monthly_price_eur, consent: {data_shared, given_at, channel}}}
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from . import rules, services
from .config import now, now_iso, settings
from .db import get_session, next_id
from .events import record_event
from .models import Case, CaseContact, Consent, Contact, Contract, Partner, Property, Unit
from .partners import transport
from .partners.eligibility import evaluate, flatten
from .partners.manifest import Manifest

log = logging.getLogger("debye.triggers")

router = APIRouter(prefix="/api/centrix", tags=["centrix"])

KNOWN_EVENTS = {"tenant.move_in"}
OPEN = {"offered", "ordered", "accepted", "signed"}


def _context(s, unit: Unit, contact: Contact | None) -> dict:
    prop = s.get(Property, unit.property_id)
    return {"property": prop.model_dump() if prop else {},
            "unit": unit.model_dump(exclude={"meters"}),
            "tenant": contact.model_dump() if contact else {}}


def matching_partners(s, event: str, ctx: dict) -> list[tuple[Manifest, bool, list[str]]]:
    flat = flatten(ctx)
    out = []
    for p in s.exec(select(Partner).where(Partner.active == True).order_by(Partner.id)).all():  # noqa: E712
        m = Manifest.model_validate(p.manifest)
        if event in m.triggers:
            ok, why = evaluate(m, flat)
            out.append((m, ok, why))
    return out


def fire(event: str, payload: dict) -> dict:
    """Returns {event, opened: [case_id], skipped: [{partner_id, reasons}]}. Idempotent per
    unit + partner while an offer is still open."""
    if event not in KNOWN_EVENTS:
        raise ValueError(f"unknown event {event}")
    unit_id = payload.get("unit_id")
    with get_session() as s:
        unit = s.get(Unit, unit_id) if unit_id else None
        if not unit:
            raise services.NotFound(f"Unit {unit_id} not found")
        contact = s.get(Contact, payload["contact_id"]) if payload.get("contact_id") else \
            s.exec(select(Contact).where(Contact.unit_id == unit.id, Contact.role == "tenant")).first()
        if not contact:
            raise services.NotFound(f"no tenant for {unit_id}")
        move_in = payload.get("move_in_date") or contact.move_in or now().date().isoformat()
        if contact.move_in != move_in:  # centrix is the source of truth for the move-in date
            contact.move_in = move_in
            s.add(contact)
            s.commit()
            s.refresh(contact)
        ctx = _context(s, unit, contact)
        candidates = matching_partners(s, event, ctx)
        contact_id, first = contact.id, contact.name.split()[0]
    record_event(None, "system", f"trigger.{event}",
                 f"centrix: {first} moves into {unit_id} on {move_in}",
                 {"event": event, "unit_id": unit_id, "contact_id": contact_id, "move_in_date": move_in,
                  "partners": [m.partner_id for m, _, _ in candidates]})
    opened, skipped = [], []
    for m, ok, why in candidates:
        if not ok:
            skipped.append({"partner_id": m.partner_id, "reasons": why})
            continue
        cid = _open_offer_case(m, unit_id, contact_id, event, move_in)
        if cid:
            opened.append(cid)
        else:
            skipped.append({"partner_id": m.partner_id, "reasons": ["offer already open"]})
    return {"event": event, "unit_id": unit_id, "contact_id": contact_id, "opened": opened,
            "skipped": skipped}


def _open_offer_case(m: Manifest, unit_id: str, contact_id: str, event: str, move_in: str) -> str | None:
    offers = [o for o in (m.model_extra or {}).get("offers") or [] if o.get("offer_id")]
    with get_session() as s:
        dup = s.exec(select(Case).where(Case.unit_id == unit_id, Case.partner_id == m.partner_id,
                                        Case.type == m.category)).all()
        if any(c.status in OPEN for c in dup):
            return None
        unit = s.get(Unit, unit_id)
        ts = now_iso()
        case = Case(id=next_id(s, Case, "case"), type=m.category, title=f"{_category_label(m)} at move-in",
                    status="offered", priority="normal",
                    summary=f"{m.name} offers {', '.join(o['title'] for o in offers) or 'a contract'}",
                    property_id=unit.property_id, unit_id=unit_id, reporter_contact_id=contact_id,
                    partner_id=m.partner_id, cost_bearer="tenant", created_at=ts, updated_at=ts,
                    data={"sell": {"trigger": event, "move_in_date": move_in, "offers": offers,
                                   "chosen": None}})
        s.add(case)
        s.add(CaseContact(case_id=case.id, contact_id=contact_id, relation="reporter"))
        s.commit()
        cid = case.id
    record_event(cid, "debye", "offer.created",
                 f"{m.name} is eligible for {unit_id} ({m.category}); offering "
                 + " / ".join(f"{o['title']} €{o.get('monthly_price_eur')}/month" for o in offers),
                 {"partner_id": m.partner_id, "partner_name": m.name, "offers": offers, "trigger": event})
    return cid


def _category_label(m: Manifest) -> str:
    return {"telecom.internet": "Internet", "energy.electricity": "Electricity",
            "insurance.household": "Household insurance"}.get(m.category, m.category)


# --------------------------------------------------------------------------- tenant steps

def manifest_for(case: Case) -> Manifest:
    m = services.get_partner_manifest(case.partner_id)
    if not m:
        raise services.NotFound(f"Partner {case.partner_id} not found")
    return m


def choose_offer(case_id: str, offer_id: str | None) -> dict:
    """offer_id None = "No thanks" (case closed, nothing shared)."""
    with get_session() as s:
        case = s.get(Case, case_id)
        if not case or case.status != "offered":
            raise rules.RuleViolation("not_offered", f"case {case_id} has no open offer")
        sell = dict((case.data or {}).get("sell") or {})
        if offer_id is None:
            case.status, case.closed_at = "closed", now_iso()
            case.data = {**(case.data or {}), "sell": {**sell, "declined": True},
                         "resolution": "Tenant declined the offer"}
            case.updated_at = now_iso()
            s.add(case)
            s.commit()
            chosen = None
        else:
            chosen = next((o for o in sell.get("offers") or [] if o["offer_id"] == offer_id), None)
            if not chosen:
                raise rules.RuleViolation("unknown_offer", f"offer {offer_id} not found")
            case.data = {**(case.data or {}), "sell": {**sell, "chosen": chosen}}
            case.updated_at = now_iso()
            s.add(case)
            s.commit()
    services.add_tenant_input(case_id, f"tap: {chosen['title'] if chosen else 'No thanks'}")
    record_event(case_id, "tenant", "offer.chosen" if chosen else "offer.declined",
                 f"Tenant picked {chosen['title']}" if chosen else "Tenant said no thanks",
                 {"offer": chosen})
    return {"case_id": case_id, "chosen": chosen}


def consent_fields(m: Manifest) -> list[str]:
    return [rules.norm_field(k) for k in m.consent_fields]


def place_order(case_id: str) -> dict | None:
    """After the tenant's consent: order through the manifest's transport (no staff approval:
    the tenant signs their own contract)."""
    with get_session() as s:
        case = s.get(Case, case_id)
        m = manifest_for(case)
        chosen = ((case.data or {}).get("sell") or {}).get("chosen")
        if not chosen:
            raise rules.RuleViolation("no_offer", "pick an offer first")
        if not rules.can_share(s, case_id, m.partner_id, consent_fields(m)):
            raise rules.RuleViolation("consent_missing", "tenant consent missing")
        case.status = "ordered"
        case.updated_at = now_iso()
        s.add(case)
        s.commit()
    record_event(case_id, "debye", "order.placed", f"Ordering {chosen['title']} from {m.name}",
                 {"partner_id": m.partner_id, "offer": chosen})
    order = transport.send_order(m, case_id, offer_id=chosen["offer_id"])
    return order


# --------------------------------------------------------------------------- partner events

async def on_sell_event(ev, case: Case, m: Manifest) -> None:
    """Called by partner_events_api for kind "sell": accepted → signed → active (→ closed)."""
    from .agent import flow
    from .partner_events_api import _docs, _attach_raw
    cid, data = case.id, ev.data or {}
    chosen = ((case.data or {}).get("sell") or {}).get("chosen") or {}
    if ev.status in ("accepted", "signed"):
        _set_status(cid, ev.status)
        for name, mime, raw in (_docs(ev, m).get("contract") or []) + (_docs(ev, m).get("confirmation") or []):
            _attach_raw(cid, "service_contract", name, mime, raw)
        record_event(cid, "partner", f"order.{ev.status}",
                     f"{m.name}: {chosen.get('title', 'order')} {ev.status}", {"partner_id": m.partner_id})
        await flow.tell_sell_update(cid, ev.status, m.name, chosen, data)
    elif ev.status == "active":
        result = write_service_contract(cid, m, chosen, data)
        await flow.tell_sell_update(cid, "active", m.name, chosen, {**data, "start": result["service_contract"]["start"]})
    elif ev.status == "closed":
        record_event(cid, "partner", "order.closed", f"{m.name} closed the order", {"partner_id": m.partner_id})


def _set_status(case_id: str, status: str) -> None:
    with get_session() as s:
        c = s.get(Case, case_id)
        c.status = status
        c.updated_at = now_iso()
        s.add(c)
        s.commit()


def write_service_contract(case_id: str, m: Manifest, chosen: dict, data: dict) -> dict:
    """reltix's result shape, stored as a service Contract on the unit, on the case and as a JSON
    document on the unit."""
    with get_session() as s:
        case = s.get(Case, case_id)
        consent = s.exec(select(Consent).where(Consent.case_id == case_id, Consent.partner_id == m.partner_id)
                         .order_by(Consent.given_at.desc())).first()
        start = data.get("start") or ((case.data or {}).get("sell") or {}).get("move_in_date") or now().date().isoformat()
        result = {
            "unit_id": case.unit_id,
            "contact_id": case.reporter_contact_id,
            "service_contract": {
                "partner": m.name,
                "category": m.category,
                "product": data.get("product") or chosen.get("title"),
                "status": "active",
                "start": start,
                "monthly_price_eur": data.get("monthly_price_eur", chosen.get("monthly_price_eur")),
                "consent": ({"data_shared": consent.data_shared, "given_at": consent.given_at,
                             "channel": consent.channel} if consent else None),
            },
        }
        s.add(Contract(id=next_id(s, Contract, "ct_svc"), type="service", unit_id=case.unit_id,
                       contact_id=case.reporter_contact_id, partner_id=m.partner_id,
                       data={**result, "case_id": case_id,
                             "partner_order_id": ((case.data or {}).get("partner_order") or {}).get("partner_order_id")}))
        case.status = "closed"
        case.closed_at = now_iso()
        case.data = {**(case.data or {}), "result": result,
                     "resolution": f"{result['service_contract']['product']} active from {start}"}
        case.updated_at = now_iso()
        s.add(case)
        s.commit()
    folder = Path(settings.storage_dir) / case_id
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f"service_contract_{case_id}.json"
    f.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    services.attach_document(case_id, "service_record", f.name, "application/json", str(f), result)
    sc = result["service_contract"]
    record_event(case_id, "debye", "service_contract.active",
                 f"{sc['product']} by {m.name} active from {start} (€{sc['monthly_price_eur']}/month), linked to {result['unit_id']}",
                 {"result": result})
    return result


def unit_service_contracts(s, unit_id: str) -> list[dict]:
    """For the staff unit page and the tenant portal: reltix-shaped results, newest first."""
    rows = s.exec(select(Contract).where(Contract.unit_id == unit_id, Contract.type == "service")).all()
    out = []
    for c in sorted(rows, key=lambda c: c.id, reverse=True):
        d = c.data or {}
        if "service_contract" in d:
            out.append({"contract_id": c.id, "unit_id": d.get("unit_id"), "contact_id": d.get("contact_id"),
                        "service_contract": d["service_contract"], "case_id": d.get("case_id")})
    return out


# --------------------------------------------------------------------------- API

class CentrixEvent(BaseModel):
    type: str
    unit_id: str
    contact_id: str | None = None
    move_in_date: str | None = None


async def fire_and_offer(event: str, payload: dict) -> dict:
    from .agent import flow
    try:
        res = fire(event, payload)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except services.NotFound as e:
        raise HTTPException(404, str(e))
    for cid in res["opened"]:
        await flow.send_offers(cid)
    return res


@router.post("/events")
async def centrix_event(body: CentrixEvent) -> dict:
    """centrix → Debye: a moment partners can be relevant for (staff unit page "Move-in" button)."""
    return await fire_and_offer(body.type, body.model_dump(exclude={"type"}))
