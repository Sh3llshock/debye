"""Demo controls (only when DEMO_MODE=1).

POST /demo/reset                 drop + re-seed DB, clear storage, reset clock
POST /demo/skip-to-tomorrow      move the demo clock one day forward
POST /demo/trigger/{name}        scripted steps (body: optional JSON), see TRIGGERS
POST /demo/sim-media             upload a file → {"media_id": "sim-..."} (for a remote server where
                                 the simulator's local:<path> media ids can't be read)
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Body, File, HTTPException, UploadFile

from . import notify, rules, services
from .config import advance_clock, now_iso, settings
from .db import get_session
from .events import publish, record_event
from .models import Case, Contact, Document
from .partners.manifest import Manifest
from .seed import seed

router = APIRouter(prefix="/demo", tags=["demo"])

SIM_DIR_NAME = "sim"


def _require_demo() -> None:
    if not settings.demo_mode:
        raise HTTPException(404, "demo mode is off")


def sim_media_path(media_id: str) -> Path:
    return Path(settings.storage_dir) / SIM_DIR_NAME / media_id


def _reset_agent_state() -> None:
    """Clear agent-whatsapp's in-memory conversation state and fake-send outbox, if present.
    Without this, conversations keep pointing at case ids from before the reset."""
    import importlib
    import logging
    for mod_name, fn_name in (("app.agent.state", "reset_all"),
                              ("app.channels.whatsapp", "clear_outbox")):
        try:
            fn = getattr(importlib.import_module(mod_name), fn_name, None)
        except ImportError:
            continue
        if callable(fn):
            try:
                fn()
            except Exception:
                logging.getLogger("debye.demo").exception("%s.%s failed", mod_name, fn_name)


@router.post("/reset")
async def reset() -> dict:
    _require_demo()
    seed(reset=True)
    _reset_agent_state()
    await publish("demo.reset", None, {"ts": now_iso()})
    return {"ok": True}


@router.post("/skip-to-tomorrow")
async def skip_to_tomorrow() -> dict:
    _require_demo()
    advance_clock(timedelta(days=1))
    record_event(None, "system", "clock.skipped", "Demo clock moved to tomorrow", {"now": now_iso()})
    return {"ok": True, "now": now_iso()}


@router.post("/sim-media")
async def sim_media(file: UploadFile = File(...)) -> dict:
    _require_demo()
    suffix = Path(file.filename or "").suffix
    media_id = f"sim-{uuid.uuid4().hex[:12]}{suffix}"
    p = sim_media_path(media_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(await file.read())
    return {"media_id": media_id, "mime": file.content_type, "filename": file.filename}


# --------------------------------------------------------------------------- triggers

def _latest_open_case() -> Case | None:
    from sqlmodel import select
    with get_session() as s:
        for c in s.exec(select(Case).order_by(Case.created_at.desc(), Case.id.desc())).all():
            if c.status not in services.OPEN_STATUSES_EXCLUDED:
                return c
    return None


def _case_id(body: dict) -> str:
    cid = body.get("case_id")
    if not cid:
        c = _latest_open_case()
        if not c:
            raise HTTPException(404, "no open case")
        cid = c.id
    if not services.get_case(cid):
        raise HTTPException(404, f"case {cid} not found")
    return cid


def _store_sim_media(media_ids: list[str], contact: Contact, kind_hint: str | None = None) -> list[str]:
    """Turn uploaded sim media into document rows (what the real router does for WA media)."""
    import shutil
    docs = []
    for mid in media_ids:
        if mid.startswith("local:"):  # simulator convention (interfaces §3.3b): read from disk
            src = Path(mid[len("local:"):])
            if not src.exists():
                continue
            p = sim_media_path(f"local-{uuid.uuid4().hex[:8]}-{src.name}")
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, p)
        else:
            p = sim_media_path(mid)
        if not p.exists():
            continue
        suffix = p.suffix.lower()
        kind, mime = {".jpg": ("photo", "image/jpeg"), ".jpeg": ("photo", "image/jpeg"),
                      ".png": ("photo", "image/png"), ".ogg": ("audio", "audio/ogg"),
                      ".pdf": ("invoice", "application/pdf")}.get(suffix, ("photo", "application/octet-stream"))
        d = services.attach_document("", kind_hint or kind, p.name, mime, str(p))
        with get_session() as s:
            doc = s.get(Document, d.id)
            doc.unit_id = contact.unit_id
            s.add(doc)
            s.commit()
        docs.append(d.id)
    return docs


async def t_tenant_report(body: dict) -> dict:
    """Lena: voice note + photo → case (F.28) → ranking. Body: contact_id, text, media_ids."""
    from . import media
    contact_id = body.get("contact_id", "c_202")
    with get_session() as s:
        contact = s.get(Contact, contact_id)
    if not contact:
        raise HTTPException(404, f"contact {contact_id} not found")
    media_ids = body.get("media_ids") or []
    doc_ids = _store_sim_media(media_ids, contact)
    text = body.get("text") or await media.transcribe("voice.ogg")
    services.log_message(contact.id, None, "whatsapp", "in", f"🎤 {text}", None, doc_ids)
    ctx = services.get_unit_context(contact.unit_id)
    asset = next((a for a in ctx["assets"] if a["type"] == "gas_boiler"), None)
    existing = services.find_open_case_for_asset(asset["id"]) if asset else None
    if existing:
        services.link_contact_to_case(existing.id, contact.id, "affected")
        return {"case_id": existing.id, "duplicate_of": existing.id}
    case = services.open_case(contact.id, "repair.heating", "urgent",
                              "Heizung komplett kalt, Kessel zeigt F.28",
                              text, body.get("error_code", "F.28"), asset["id"] if asset else None)
    services.add_tenant_input(case.id, "voice note")
    if doc_ids:
        services.add_tenant_input(case.id, "photo")
    services.log_message(contact.id, case.id, "whatsapp", "out", "Danke! Sind alle Heizkörper kalt?")
    services.add_tenant_input(case.id, "tap: Überall kalt")
    services.log_message(contact.id, case.id, "whatsapp", "in", "Überall kalt")
    ranking = services.rank_partners(case.id)
    return {"case_id": case.id, "ranking": ranking}


async def t_neighbour_report(body: dict) -> dict:
    body = {"contact_id": "c_203", "text": "Bei uns im 1. Stock ist die Heizung auch kalt.", **body}
    return await t_tenant_report(body)


async def t_consent(body: dict) -> dict:
    """Tenant taps consent for the top-ranked (or given) partner → dispatch."""
    case_id = _case_id(body)
    case = services.get_case(case_id)
    partner_id = body.get("partner_id")
    if not partner_id:
        ranking = (case.data or {}).get("ranking") or services.rank_partners(case_id)
        if not ranking:
            raise HTTPException(409, "no eligible partner")
        partner_id = ranking[0]["partner_id"]
    m: Manifest = services.get_partner_manifest(partner_id)
    fields = body.get("fields") or [rules.norm_field(f) for f in m.consent_fields]
    services.record_consent(case.reporter_contact_id, partner_id, case_id, fields,
                            body.get("purpose", "heating repair visit"), "whatsapp")
    services.add_tenant_input(case_id, "tap: consent")
    services.log_message(case.reporter_contact_id, case_id, "whatsapp", "in", "✅ Ja, teilen")
    try:
        return {"dispatched": services.dispatch_job(case_id, partner_id)}
    except rules.RuleViolation as rv:
        return {"dispatched": None, "blocked": rv.code, "detail": rv.message}


async def t_pick_slot(body: dict) -> dict:
    case_id = _case_id(body)
    case = services.get_case(case_id)
    idx = int(body.get("index", 1))  # 1-based
    slots = (case.data or {}).get("proposed_slots") or []
    if 1 <= idx <= len(slots):
        services.log_message(case.reporter_contact_id, case_id, "whatsapp", "in", slots[idx - 1]["label"])
    try:
        return services.confirm_slot(case_id, idx)
    except rules.RuleViolation as rv:
        raise HTTPException(409, rv.message)


async def t_fixed(body: dict) -> dict:
    case_id = _case_id(body)
    case = services.get_case(case_id)
    fixed = bool(body.get("fixed", True))
    services.log_message(case.reporter_contact_id, case_id, "whatsapp", "in", "👍 Ja, warm!" if fixed else "Nein, noch kalt")
    return services.tenant_confirms_fixed(case_id, fixed)


async def t_expensive_repair(body: dict) -> dict:
    """Bump the estimate above the auto-approve limit so the approval card shows."""
    case_id = _case_id(body)
    with get_session() as s:
        c = s.get(Case, case_id)
        c.estimated_cost_eur = float(body.get("estimated_cost_eur", 620))
        s.add(c)
        s.commit()
    record_event(case_id, "debye", "estimate.updated",
                 f"Estimate updated to €{float(body.get('estimated_cost_eur', 620)):.0f} (heat exchanger)",
                 {"estimated_cost_eur": float(body.get("estimated_cost_eur", 620))})
    return {"case_id": case_id}


async def t_notify(body: dict) -> dict:
    """Re-send a tenant notification (for testing notify.py): {case_id, event, data}."""
    case_id = _case_id(body)
    await notify.notify_tenant(case_id, body.get("event", "job_accepted"), body.get("data", {}))
    return {"ok": True}


TRIGGERS = {
    "tenant_report": t_tenant_report,
    "neighbour_report": t_neighbour_report,
    "consent": t_consent,
    "pick_slot": t_pick_slot,
    "fixed": t_fixed,
    "expensive_repair": t_expensive_repair,
    "notify": t_notify,
}


@router.post("/trigger/{name}")
async def trigger(name: str, body: dict | None = Body(None)) -> dict:
    _require_demo()
    fn = TRIGGERS.get(name)
    if not fn:
        raise HTTPException(404, f"unknown trigger {name}; known: {sorted(TRIGGERS)}")
    return await fn(body or {})
