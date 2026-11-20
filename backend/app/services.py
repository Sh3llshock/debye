"""What the agent (and the APIs) call. Signatures per interfaces §3.3; everything is sync.

Case status lifecycle:
  new → approval_pending (staff approve every job, APPROVAL_POLICY=always) → requested → accepted
      → slots_proposed → awaiting_technician
      → scheduled
      → completed → invoiced → closed
  side states: rejected (staff rejected, partner never contacted), partner_declined (back to ranking),
      reopened (tenant says not fixed)

Services record only the events of their own state changes; conversational events
(triage.answer, ...) are recorded by the agent/router.

Extras beyond the contract (safe to use): message_seen, add_tenant_input, propose_slots,
partner_accept, partner_decline, record_completion, approve_case, case_label_slot.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlmodel import select

from . import rules
from .config import TZ, now, now_iso, settings
from .db import get_session, next_id
from .events import publish_sync, record_event
from .models import (Asset, Case, CaseContact, Consent, Contact, Contract, Document, Message,
                     Partner, Property, Technician, Unit)
from .partners.manifest import Manifest
from .partners.ranking import rank

OPEN_STATUSES_EXCLUDED = {"closed", "cancelled", "rejected"}


class NotFound(Exception):
    pass


# --------------------------------------------------------------------------- helpers

def _get(s, model, id_: str | None):
    obj = s.get(model, id_) if id_ else None
    if obj is None:
        raise NotFound(f"{model.__name__} {id_} not found")
    return obj


def _patch_data(case: Case, **kv) -> None:
    case.data = {**(case.data or {}), **kv}


def _save_case(s, case: Case) -> Case:
    case.updated_at = now_iso()
    s.add(case)
    s.commit()
    s.refresh(case)
    return case


def get_case(case_id: str) -> Case | None:
    with get_session() as s:
        return s.get(Case, case_id)


def get_partner_manifest(partner_id: str) -> Manifest | None:
    with get_session() as s:
        p = s.get(Partner, partner_id)
        return Manifest.model_validate(p.manifest) if p else None


def _tenant_for_unit(s, unit_id: str | None) -> Contact | None:
    if not unit_id:
        return None
    return s.exec(select(Contact).where(Contact.unit_id == unit_id,
                                        Contact.role == "tenant")).first()


def _lease_for_unit(s, unit_id: str | None) -> Contract | None:
    if not unit_id:
        return None
    return s.exec(select(Contract).where(Contract.unit_id == unit_id,
                                         Contract.type == "lease")).first()


def _case_title(case_type: str, asset: Asset | None) -> str:
    if case_type == "repair.heating":
        return "No heating – central boiler" if asset and asset.unit_id is None else "Heating problem"
    return case_type.replace(".", " ").capitalize()


# Plain-English meaning of boiler error codes for the pages (judges don't know what F.28 is).
ERROR_LABELS_EN = {
    "F.22": "Water pressure too low",
    "F.28": "Ignition failed: no flame at start-up",
    "F.29": "Flame lost during operation",
}
_ERROR_SHORT_EN = {
    "F.22": "water pressure too low",
    "F.28": "ignition failed",
    "F.29": "flame lost during operation",
}


def _norm_code(code: str | None) -> str:
    c = (code or "").strip().upper().replace(" ", "")
    if c.startswith("F") and len(c) > 1 and c[1] != ".":
        c = "F." + c[1:]  # "F28" → "F.28"
    return c


def error_label(code: str | None, known: dict | None = None) -> str | None:
    """'F.28' → 'Ignition failed: no flame at start-up'. Falls back to the asset's
    known_error_codes, then to 'Error code <code>'. None if there is no code."""
    if not code:
        return None
    c = _norm_code(code)
    if c in ERROR_LABELS_EN:
        return ERROR_LABELS_EN[c]
    known = {_norm_code(k): v for k, v in (known or {}).items()}
    return known.get(c) or f"Error code {code}"


def error_phrase(code: str | None, known: dict | None = None) -> str | None:
    """For event summaries, meaning first: 'Boiler error: ignition failed (F.28)'."""
    if not code:
        return None
    short = _ERROR_SHORT_EN.get(_norm_code(code))
    if not short:
        label = error_label(code, known) or ""
        short = label[:1].lower() + label[1:]
    return f"Boiler error: {short} ({code})"


GERMAN_DAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


EN_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
EN_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def slot_clock(start: str, end: str) -> str:
    """'Sat 08:00–10:00' (for staff/technician event summaries)."""
    s = datetime.fromisoformat(start).astimezone(TZ)
    e = datetime.fromisoformat(end).astimezone(TZ)
    return f"{EN_DAYS[s.weekday()]} {s:%H:%M}–{e:%H:%M}"


def case_label_slot(start: str, end: str, language: str = "de") -> str:
    """de: 'Morgen 8–10' / 'Heute 14–16' / 'Do 26.11. 8–10'.
    en: 'Tomorrow 8–10' / 'Today 14–16' / 'Thu 26 Nov, 8–10'."""
    s = datetime.fromisoformat(start).astimezone(TZ)
    e = datetime.fromisoformat(end).astimezone(TZ)
    today = now().date()
    hours = f"{s.hour}" + (f":{s.minute:02d}" if s.minute else "") + "–" + \
            f"{e.hour}" + (f":{e.minute:02d}" if e.minute else "")
    delta = (s.date() - today).days
    if language == "en":
        if delta == 0:
            day = "Today"
        elif delta == 1:
            day = "Tomorrow"
        else:
            return f"{EN_DAYS[s.weekday()]} {s.day} {EN_MONTHS[s.month - 1]}, {hours}"
        return f"{day} {hours}"
    if delta == 0:
        day = "Heute"
    elif delta == 1:
        day = "Morgen"
    else:
        day = f"{GERMAN_DAYS[s.weekday()]} {s.day:02d}.{s.month:02d}."
    return f"{day} {hours}"


# --------------------------------------------------------------------------- contract §3.3

def get_contact_by_phone(phone_e164: str) -> Contact | None:
    phone = (phone_e164 or "").strip().replace(" ", "")
    if phone and not phone.startswith("+"):
        phone = "+" + phone  # WhatsApp webhooks send numbers without "+"
    with get_session() as s:
        return s.exec(select(Contact).where(Contact.phone_e164 == phone)).first()


def get_unit_context(unit_id: str) -> dict:
    with get_session() as s:
        unit = _get(s, Unit, unit_id)
        prop = s.get(Property, unit.property_id)
        assets = s.exec(select(Asset).where(Asset.property_id == unit.property_id)).all()
        assets = [a for a in assets if a.unit_id in (None, unit_id)]
        tenant = _tenant_for_unit(s, unit_id)
        lease = _lease_for_unit(s, unit_id)
        open_cases = [c for c in s.exec(select(Case).where(Case.property_id == unit.property_id)).all()
                      if c.status not in OPEN_STATUSES_EXCLUDED]
        return {
            "property": prop.model_dump() if prop else None,
            "unit": unit.model_dump(),
            "assets": [a.model_dump() for a in assets],
            "tenant": tenant.model_dump() if tenant else None,
            "lease": lease.model_dump() if lease else None,
            "open_cases": [{"case_id": c.id, "type": c.type, "status": c.status,
                            "asset_id": c.asset_id, "unit_id": c.unit_id, "title": c.title,
                            "summary": c.summary, "error_code": c.error_code,
                            "error_label": error_label(c.error_code),
                            "created_at": c.created_at} for c in open_cases],
        }


def find_open_case_for_asset(asset_id: str) -> Case | None:
    with get_session() as s:
        cases = s.exec(select(Case).where(Case.asset_id == asset_id)
                       .order_by(Case.created_at.desc())).all()
        for c in cases:
            if c.status not in OPEN_STATUSES_EXCLUDED:
                return c
        return None


PREFILLED_FROM_CENTRIX = [
    "tenant name", "phone", "address", "unit", "floor", "building year", "heating type",
    "boiler make", "boiler model", "boiler installed", "last service", "lease",
    "cost bearer", "framework partner",
]


DIAGNOSIS_KEYS = ("cause_id", "label", "confidence", "reasoning", "questions_asked", "outcome")


def _clean_diagnosis(diagnosis: dict | None) -> dict | None:
    if not diagnosis:
        return None
    d = {k: diagnosis.get(k) for k in DIAGNOSIS_KEYS if k in diagnosis}
    d["questions_asked"] = list(d.get("questions_asked") or [])
    return d


def case_trade(case: Case) -> str | None:
    """The trade the case needs (heating | plumbing | electrical | ...). Default: from the case type."""
    t = (case.data or {}).get("trade")
    if t:
        return t
    return case.type.split(".")[-1] if case.type and case.type.startswith("repair.") else None


def open_case(reporter_contact_id: str, type: str, priority: str, summary: str,
              symptoms: str, error_code: str | None, asset_id: str | None,
              trade: str | None = None, diagnosis: dict | None = None) -> Case:
    """trade: which trade the job needs (heating | plumbing | electrical), from the diagnosis.
    diagnosis: {cause_id, label, confidence, reasoning, questions_asked[]} (see docs/diagnosis.md)."""
    diagnosis = _clean_diagnosis(diagnosis)
    with get_session() as s:
        reporter = _get(s, Contact, reporter_contact_id)
        unit = s.get(Unit, reporter.unit_id) if reporter.unit_id else None
        asset = s.get(Asset, asset_id) if asset_id else None
        property_id = (unit.property_id if unit else None) or (asset.property_id if asset else None)
        if asset is None and type.startswith("repair.heating") and property_id:
            asset = s.exec(select(Asset).where(Asset.property_id == property_id,
                                               Asset.type.in_(["gas_boiler", "heat_pump"]))).first()
        # pre-visit estimate against the framework partner's prices (if any)
        fw = s.exec(select(Contract).where(Contract.type == "framework")).first()
        estimate = rules.estimate_cost(s, error_code, fw.partner_id if fw else None)
        ts = now_iso()
        case = Case(
            id=next_id(s, Case, "case"), type=type, title=_case_title(type, asset),
            status="new", priority=priority or "normal", summary=summary or "",
            symptoms=symptoms or "", error_code=error_code, property_id=property_id,
            unit_id=reporter.unit_id, asset_id=asset.id if asset else None,
            reporter_contact_id=reporter.id, cost_bearer="landlord",
            estimated_cost_eur=estimate, created_at=ts, updated_at=ts,
            data={"prefilled_fields": PREFILLED_FROM_CENTRIX, "tenant_inputs": [],
                  **({"trade": trade} if trade else {}),
                  **({"diagnosis": diagnosis} if diagnosis else {})},
        )
        s.add(case)
        s.add(CaseContact(case_id=case.id, contact_id=reporter.id, relation="reporter"))
        # attach any not-yet-linked media this reporter sent in the last minutes
        s.commit()
        s.refresh(case)
        first = reporter.name.split()[0]
        known = asset.known_error_codes if asset else None
    phrase = error_phrase(error_code, known)
    record_event(case.id, "debye", "case.created",
                 f"Case opened from {first}'s report" + (f". {phrase}" if phrase else ""),
                 {"priority": case.priority, "error_code": error_code,
                  "error_label": error_label(error_code, known), "asset_id": case.asset_id,
                  "estimated_cost_eur": estimate, "trade": trade})
    if diagnosis:
        _record_diagnosis_event(case.id, diagnosis, trade)
    _claim_orphan_media(case.id, reporter_contact_id)
    return get_case(case.id)


def set_case_error_code(case_id: str, code: str) -> Case:
    """Set the boiler error code read later (e.g. from a photo). Records one event
    'Boiler error: <label> (<code>)' that the staff page picks up live. Same code again → no-op.
    While the job isn't dispatched yet, the cost estimate is recomputed for the new code."""
    code = (code or "").strip()
    if not code:
        raise rules.RuleViolation("invalid_error_code", "error code is empty")
    code = _norm_code(code) if _norm_code(code) in ERROR_LABELS_EN else code
    with get_session() as s:
        case = _get(s, Case, case_id)
        if case.error_code == code:
            return case
        previous = case.error_code
        case.error_code = code
        if case.status in ("new", "awaiting_approval") and not case.partner_id:
            fw = s.exec(select(Contract).where(Contract.type == "framework")).first()
            case.estimated_cost_eur = rules.estimate_cost(s, code, fw.partner_id if fw else None)
        asset = s.get(Asset, case.asset_id) if case.asset_id else None
        known = asset.known_error_codes if asset else None
        _save_case(s, case)
        estimate = case.estimated_cost_eur
    record_event(case_id, "debye", "case.error_code", error_phrase(code, known),
                 {"error_code": code, "error_label": error_label(code, known),
                  "previous_error_code": previous, "estimated_cost_eur": estimate})
    return get_case(case_id)


def _record_diagnosis_event(case_id: str, diagnosis: dict, trade: str | None) -> None:
    conf = diagnosis.get("confidence")
    conf_txt = f", {conf:.0%} sure" if isinstance(conf, (int, float)) and conf <= 1 else \
        (f", {conf}" if conf else "")
    who = f" → {trade}" if trade else ""
    record_event(case_id, "debye", "diagnosis.recorded",
                 f"Likely cause: {diagnosis.get('label') or diagnosis.get('cause_id')}{conf_txt}{who}",
                 {**diagnosis, "trade": trade})


def set_case_diagnosis(case_id: str, diagnosis: dict, trade: str | None = None) -> Case:
    """Record (or update) the diagnosis after the case was opened; optionally set the trade."""
    diagnosis = _clean_diagnosis(diagnosis) or {}
    with get_session() as s:
        case = _get(s, Case, case_id)
        _patch_data(case, diagnosis=diagnosis, **({"trade": trade} if trade else {}))
        _save_case(s, case)
        trade = trade or (case.data or {}).get("trade")
    _record_diagnosis_event(case_id, diagnosis, trade)
    return get_case(case_id)


def notify_caretaker(case_id: str, reason: str) -> dict:
    """Hand the case to the reltix caretaker (no partner, no approval): e.g. top up system pressure.
    Records "Caretaker Peter Wolf notified: <reason>"."""
    import re
    with get_session() as s:
        case = _get(s, Case, case_id)
        ct = s.exec(select(Contact).where(Contact.role == "caretaker")).first()
        if ct is None:
            raise rules.RuleViolation("no_caretaker", "no caretaker in centrix")
        name = re.sub(r"\s*\(.*?\)\s*$", "", ct.name).strip()
        info = {"contact_id": ct.id, "name": name, "phone_e164": ct.phone_e164,
                "reason": reason, "notified_at": now_iso()}
        _patch_data(case, caretaker=info)
        _save_case(s, case)
    record_event(case_id, "debye", "caretaker.notified", f"Caretaker {name} notified: {reason}", info)
    return {"case_id": case_id, "caretaker": info}


def _claim_orphan_media(case_id: str, contact_id: str) -> None:
    """Messages/documents the reporter sent before the case existed get linked to it."""
    with get_session() as s:
        case = s.get(Case, case_id)
        msgs = s.exec(select(Message).where(Message.contact_id == contact_id,
                                            Message.case_id == None)).all()  # noqa: E711
        doc_ids = set()
        for m in msgs:
            m.case_id = case_id
            doc_ids |= set(m.media_ids or [])
            s.add(m)
        for d_id in doc_ids:
            d = s.get(Document, d_id)
            if d and d.case_id is None:
                d.case_id = case_id
                d.unit_id = d.unit_id or case.unit_id
                s.add(d)
        s.commit()


def link_contact_to_case(case_id: str, contact_id: str, relation: str) -> None:
    with get_session() as s:
        case = _get(s, Case, case_id)
        contact = _get(s, Contact, contact_id)
        existing = s.get(CaseContact, (case_id, contact_id))
        if existing:
            existing.relation = relation
            s.add(existing)
        else:
            s.add(CaseContact(case_id=case_id, contact_id=contact_id, relation=relation))
        s.commit()
        unit = contact.unit_id
    record_event(case_id, "debye", "case.linked_reporter",
                 f"{contact.name} ({unit}) reported the same problem – linked to this case",
                 {"contact_id": contact_id, "unit_id": unit, "relation": relation})
    _claim_orphan_media(case_id, contact_id)


def attach_document(case_id: str, kind: str, filename: str, mime: str, path: str,
                    extracted: dict | None = None) -> Document:
    with get_session() as s:
        case = s.get(Case, case_id) if case_id else None
        doc = Document(id=next_id(s, Document, "doc"), case_id=case_id or None,
                       unit_id=case.unit_id if case else None, kind=kind, filename=filename,
                       mime=mime, path=str(path), extracted=extracted, created_at=now_iso())
        s.add(doc)
        s.commit()
        s.refresh(doc)
    if case_id:
        record_event(case_id, "system", "document.attached", f"{kind.capitalize()} {filename} attached",
                     {"document_id": doc.id, "kind": kind, "filename": filename,
                      "url": f"/files/{doc.id}", "unit_id": doc.unit_id})
    return doc


def record_consent(contact_id: str, partner_id: str, case_id: str, fields: list[str],
                   purpose: str, channel: str) -> Consent:
    with get_session() as s:
        _get(s, Contact, contact_id)
        partner = _get(s, Partner, partner_id)
        consent = Consent(id=next_id(s, Consent, "consent"), contact_id=contact_id,
                          partner_id=partner_id, case_id=case_id,
                          data_shared=[rules.norm_field(f) for f in fields], purpose=purpose,
                          channel=channel, given_at=now_iso())
        s.add(consent)
        s.commit()
        s.refresh(consent)
        name = partner.manifest.get("name", partner_id)
    record_event(case_id, "tenant", "consent.recorded",
                 f"Consent given to share {', '.join(consent.data_shared)} with {name}",
                 consent.model_dump())
    return consent


def rank_partners(case_id: str) -> list[dict]:
    with get_session() as s:
        case = _get(s, Case, case_id)
        prop = s.get(Property, case.property_id) if case.property_id else None
        unit = s.get(Unit, case.unit_id) if case.unit_id else None
        asset = s.get(Asset, case.asset_id) if case.asset_id else None
        tenant = s.get(Contact, case.reporter_contact_id) if case.reporter_contact_id else None
        ctx = {
            "property": prop.model_dump() if prop else {},
            "unit": unit.model_dump(exclude={"meters"}) if unit else {},
            "asset": asset.model_dump(exclude={"known_error_codes"}) if asset else {},
            "tenant": tenant.model_dump() if tenant else {},
            "case": {"type": case.type, "error_code": case.error_code},
        }
        manifests = [Manifest.model_validate(p.manifest)
                     for p in s.exec(select(Partner).where(Partner.active == True)).all()]  # noqa: E712
        fw_ids = {c.partner_id for c in s.exec(select(Contract).where(Contract.type == "framework")).all()}
        declined = set((case.data or {}).get("declined_by", []))
        full = [r for r in rank(case.type, ctx, manifests, fw_ids, case.property_id, trade=case_trade(case))
                if r["partner_id"] not in declined]
        top = [r for r in full if r["eligible"]][:3]
        _patch_data(case, ranking=top)
        _save_case(s, case)
    record_event(case_id, "debye", "partner.ranked",
                 f"Ranked {len(top)} partners – {top[0]['name']} first" if top else "No eligible partner",
                 {"ranking": top})
    return [{"partner_id": r["partner_id"], "name": r["name"], "score": r["score"],
             "reasons": r["reasons"]} for r in top]


def dispatch_job(case_id: str, partner_id: str) -> dict:
    """Code-gated: needs consent + staff approval (APPROVAL_POLICY=always, default) or
    estimate ≤ limit (APPROVAL_POLICY=limit). Without approval the job is NOT sent: the case goes to
    approval_pending and rules.RuleViolation("approval_required") is raised (the caller tells the tenant).
    Raises rules.RuleViolation("consent_missing" | "approval_required")."""
    with get_session() as s:
        case = _get(s, Case, case_id)
        partner = _get(s, Partner, partner_id)
        name = partner.manifest.get("name", partner_id)
        try:
            approval = rules.check_dispatch(s, case, partner_id)
        except rules.RuleViolation as rv:
            if rv.code == "approval_required" and case.status != "approval_pending":
                approval = rules.approval_status(s, case, partner_id)
                _patch_data(case, pending_partner_id=partner_id,
                            approval={**approval, "granted": False})
                case.status = "approval_pending"
                _save_case(s, case)
                est = case.estimated_cost_eur or 0
                record_event(case_id, "system", "approval.required",
                             f"Waiting for staff approval: {name}, est. €{est:.0f}",
                             {"partner_id": partner_id, "partner_name": name,
                              "estimated_cost_eur": est, **approval})
            raise
        case.partner_id = partner_id
        case.status = "requested"
        _patch_data(case, approval={**approval, "granted": approval.get("granted", False)},
                    pending_partner_id=None)
        _save_case(s, case)
        transport = partner.manifest.get("transport", {})
        asset = s.get(Asset, case.asset_id) if case.asset_id else None
        phrase = error_phrase(case.error_code, asset.known_error_codes if asset else None)
    record_event(case_id, "debye", "job.sent", f"Job sent to {name}" + (f". {phrase}" if phrase else ""),
                 {"partner_id": partner_id, "transport": transport.get("type"),
                  "url": transport.get("url")})
    return {"case_id": case_id, "partner_id": partner_id, "partner_name": name,
            "status": "requested", "approval": approval}


def approve_case(case_id: str, actor: str = "staff") -> dict:
    """PM approves; if a partner was waiting, the job is dispatched right away."""
    with get_session() as s:
        case = _get(s, Case, case_id)
        approval = {**(case.data or {}).get("approval", {}), "granted": True,
                    "granted_at": now_iso()}
        _patch_data(case, approval=approval)
        pending = (case.data or {}).get("pending_partner_id")
        if case.status in ("approval_pending", "awaiting_approval"):
            case.status = "new"
        _save_case(s, case)
        est = case.estimated_cost_eur or 0
        p = s.get(Partner, pending) if pending else None
        partner_name = p.manifest.get("name") if p else None
    record_event(case_id, actor, "approval.granted",
                 f"Staff approved the job" + (f" for {partner_name}" if partner_name else "") + f" (est. €{est:.0f})",
                 {"estimated_cost_eur": est, "partner_id": pending, "partner_name": partner_name})
    result = {"case_id": case_id, "approved": True, "dispatched": None, "partner_name": partner_name}
    if pending:
        result["dispatched"] = dispatch_job(case_id, pending)
    return result


def reject_case(case_id: str, reason: str = "", actor: str = "staff") -> dict:
    """Staff reject a job waiting for approval: the partner is never contacted → status rejected."""
    with get_session() as s:
        case = _get(s, Case, case_id)
        if case.status not in ("approval_pending", "awaiting_approval"):
            raise rules.RuleViolation("not_pending_approval",
                                      f"case is {case.status}, only jobs waiting for approval can be rejected")
        pending = (case.data or {}).get("pending_partner_id")
        p = s.get(Partner, pending) if pending else None
        partner_name = p.manifest.get("name") if p else None
        _patch_data(case, approval={**(case.data or {}).get("approval", {}), "granted": False,
                                    "rejected": True, "reason": reason, "rejected_at": now_iso()},
                    pending_partner_id=None)
        case.status = "rejected"
        _save_case(s, case)
    record_event(case_id, actor, "approval.rejected",
                 "Staff rejected the job" + (f" for {partner_name}" if partner_name else "") +
                 (f": {reason}" if reason else ""),
                 {"partner_id": pending, "partner_name": partner_name, "reason": reason})
    return {"case_id": case_id, "status": "rejected", "partner_name": partner_name, "reason": reason}


def partner_accept(case_id: str, partner_id: str) -> Case:
    with get_session() as s:
        case = _get(s, Case, case_id)
        if case.partner_id != partner_id:
            raise rules.RuleViolation("not_assigned", "this job is not assigned to you")
        case.status = "accepted"
        _save_case(s, case)
        name = s.get(Partner, partner_id).manifest.get("name", partner_id)
    record_event(case_id, "partner", "job.accepted", f"{name} accepted the job",
                 {"partner_id": partner_id})
    return get_case(case_id)


def partner_decline(case_id: str, partner_id: str, reason: str) -> Case:
    with get_session() as s:
        case = _get(s, Case, case_id)
        if case.partner_id != partner_id:
            raise rules.RuleViolation("not_assigned", "this job is not assigned to you")
        declined = list((case.data or {}).get("declined_by", []))
        if partner_id not in declined:
            declined.append(partner_id)
        _patch_data(case, declined_by=declined, decline_reason=reason)
        case.partner_id = None
        case.status = "partner_declined"
        _save_case(s, case)
        name = s.get(Partner, partner_id).manifest.get("name", partner_id)
    record_event(case_id, "partner", "job.declined",
                 f"{name} declined" + (f": {reason}" if reason else ""),
                 {"partner_id": partner_id, "reason": reason})
    return get_case(case_id)


def get_technicians(partner_id: str) -> list[dict]:
    """[{tech_id, name, skills, free_slots:[{start,end}]}] – free = next 3 days,
    08–10 / 10–12 / 14–16 minus busy."""
    from .partners.technicians import free_slots
    with get_session() as s:
        techs = s.exec(select(Technician).where(Technician.partner_id == partner_id)
                       .order_by(Technician.id)).all()
        return [{"tech_id": t.id, "name": t.name, "skills": t.skills, "phone_e164": t.phone_e164,
                 "free_slots": free_slots(t.busy)} for t in techs]


def get_technician(tech_id: str) -> Technician | None:
    with get_session() as s:
        return s.get(Technician, tech_id)


def _tenant_language(s, case: Case) -> str:
    c = s.get(Contact, case.reporter_contact_id) if case.reporter_contact_id else None
    return (c.language if c else None) or "en"


def _pick_technician(s, case: Case, partner_id: str, slots: list[dict]):
    """Auto-assign: among the partner's technicians free in every slot, prefer skills matching
    the asset brand, then the trade (heating), then the fewest booked jobs. None if nobody is free."""
    from .partners.technicians import is_free
    asset = s.get(Asset, case.asset_id) if case.asset_id else None
    brand = (asset.make or "").lower() if asset else ""
    trade = case_trade(case) or ""
    best, best_key = None, None
    techs = s.exec(select(Technician).where(Technician.partner_id == partner_id)).all()
    skilled = [t for t in techs if trade and trade in {k.lower() for k in t.skills or []}]
    if skilled:  # only technicians with the needed trade (no heating-only tech on a plumbing job)
        techs = skilled
    for t in techs:
        if not all(is_free(t.busy, sl) for sl in slots):
            continue
        skills = {k.lower() for k in t.skills or []}
        jobs = sum(1 for b in t.busy if str(b.get("reason", "")).startswith("job"))
        if trade in ("heating", ""):
            key = (brand in skills, trade in skills, -jobs, t.id)
        else:  # plumbing/electrical: the trade skill decides, brand doesn't matter
            key = (trade in skills, False, -jobs, t.id)
        if best_key is None or key[:3] > best_key[:3] or (key[:3] == best_key[:3] and t.id < best_key[3]):
            best, best_key = t, key
    reason = None
    if best:
        bits = []
        if trade in ("heating", ""):
            if best_key[0]:
                bits.append(f"{asset.make}-skilled")
            if best_key[1]:
                bits.append(f"{trade} trade")
        elif best_key[0]:
            bits.append(f"{trade} trade")
        bits.append("free in all proposed slots")
        reason = ", ".join(bits)
    return best, reason


def suggest_technician(case_id: str, partner_id: str) -> dict | None:
    """For the staff approval card: the technician auto-assign would pick for the earliest free slot.
    {"technician": {tech_id, name}, "slot": {start, end, label}} or None (partner has no technicians)."""
    from .partners.technicians import free_slots
    with get_session() as s:
        case = s.get(Case, case_id)
        if not case:
            return None
        techs = s.exec(select(Technician).where(Technician.partner_id == partner_id)).all()
        slots = sorted({(sl["start"], sl["end"]) for t in techs for sl in free_slots(t.busy)})
        for start, end in slots:
            slot = {"start": start, "end": end}
            tech, _ = _pick_technician(s, case, partner_id, [slot])
            if tech:
                return {"technician": {"tech_id": tech.id, "name": tech.name},
                        "slot": {**slot, "label": case_label_slot(start, end, _tenant_language(s, case))}}
    return None


def propose_slots(case_id: str, partner_id: str, slots: list[dict],
                  tech_id: str | None = None) -> list[dict]:
    """slots: [{start, end}] ISO → stored with labels; returns [{start, end, label}].
    Technician flow: with tech_id the technician must belong to the partner and be free in
    every slot (else RuleViolation). Without tech_id the dispatcher auto-assigns the best free
    technician (brand skill → trade → fewest bookings). Stored on the case as data.technician."""
    from .partners.technicians import is_free
    labelled = []
    for sl in slots:
        start = datetime.fromisoformat(sl["start"])
        end = datetime.fromisoformat(sl["end"])
        if start.tzinfo is None:
            start = start.replace(tzinfo=TZ)
        if end.tzinfo is None:
            end = end.replace(tzinfo=TZ)
        st, en = start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")
        labelled.append({"start": st, "end": en})
    tech_view = None
    with get_session() as s:
        case = _get(s, Case, case_id)
        if case.partner_id != partner_id:
            raise rules.RuleViolation("not_assigned", "this job is not assigned to you")
        if tech_id:
            tech = s.get(Technician, tech_id)
            if not tech or tech.partner_id != partner_id:
                raise rules.RuleViolation("unknown_technician",
                                          f"technician {tech_id} not found for {partner_id}")
            busy = [sl for sl in labelled if not is_free(tech.busy, sl)]
            if busy:
                raise rules.RuleViolation(
                    "technician_busy",
                    f"{tech.name} is busy at {slot_clock(busy[0]['start'], busy[0]['end'])}")
            tech_view = {"tech_id": tech.id, "name": tech.name}
            assigned = {"auto": False, "reason": "chosen by the dispatcher"}
        else:
            tech, reason = _pick_technician(s, case, partner_id, labelled)
            has_techs = s.exec(select(Technician).where(Technician.partner_id == partner_id)).first()
            if tech is None and has_techs:
                raise rules.RuleViolation("no_technician_free",
                                          "no technician is free in all proposed slots")
            if tech is not None:
                tech_view = {"tech_id": tech.id, "name": tech.name}
                assigned = {"auto": True, "reason": reason}
        lang = _tenant_language(s, case)
        for sl in labelled:
            sl["label"] = case_label_slot(sl["start"], sl["end"], lang)
        extra = {"technician": tech_view} if tech_view else {}
        _patch_data(case, proposed_slots=labelled, **extra)
        case.status = "slots_proposed"
        _save_case(s, case)
    if tech_view:
        verb = "auto-assigned" if assigned["auto"] else "assigned"
        record_event(case_id, "partner", "technician.assigned",
                     f"Dispatcher {verb} {tech_view['name']}" +
                     (f" ({assigned['reason']})" if assigned["auto"] and assigned["reason"] else ""),
                     {**tech_view, **assigned})
    who = f" with {tech_view['name']}" if tech_view else ""
    record_event(case_id, "partner", "slot.proposed",
                 "Proposed " + " or ".join(sl["label"] for sl in labelled) + who,
                 {"slots": labelled, "technician": tech_view})
    return labelled


def confirm_slot(case_id: str, slot_index: int) -> dict:
    """slot_index is 1-based, matching the WhatsApp list ids slot_1, slot_2, ... (interfaces §3.3)."""
    with get_session() as s:
        case = _get(s, Case, case_id)
        slots = (case.data or {}).get("proposed_slots") or []
        if not 1 <= slot_index <= len(slots):
            raise rules.RuleViolation("invalid_slot", f"slot {slot_index} does not exist")
        slot = slots[slot_index - 1]
        case.slot_start, case.slot_end = slot["start"], slot["end"]
        tech = (case.data or {}).get("technician")
        # technician flow: the technician still has to confirm on the phone page
        case.status = "awaiting_technician" if tech else "scheduled"
        _save_case(s, case)
        partner_name = None
        if case.partner_id:
            partner_name = s.get(Partner, case.partner_id).manifest.get("name")
        status = case.status
    add_tenant_input(case_id, f"tap: {slot['label']}")
    summary = f"Tenant picked {slot['label']}"
    if tech:
        summary += f" – waiting for {tech['name']} to confirm"
    record_event(case_id, "tenant", "slot.confirmed", summary, {"slot": slot, "technician": tech})
    return {"case_id": case_id, "slot": slot, "partner_name": partner_name, "status": status,
            "technician": tech}


def technician_confirm(case_id: str, tech_id: str) -> dict:
    """Technician confirms the slot the tenant picked: books it on the calendar → scheduled."""
    with get_session() as s:
        case = _get(s, Case, case_id)
        tech = _get(s, Technician, tech_id)
        assigned = ((case.data or {}).get("technician") or {}).get("tech_id")
        if assigned != tech_id:
            raise rules.RuleViolation("not_assigned", "this job is not assigned to you")
        if case.status != "awaiting_technician" or not case.slot_start:
            raise rules.RuleViolation("not_awaiting_technician",
                                      f"job is {case.status}; the tenant has to pick a slot first")
        slot = {"start": case.slot_start, "end": case.slot_end}
        tech.busy = [*tech.busy, {**slot, "reason": f"job {case_id}"}]
        # the label the tenant saw (tenant's language), so WhatsApp texts can reuse it
        picked = next((sl for sl in (case.data or {}).get("proposed_slots") or []
                       if sl.get("start") == slot["start"]), None)
        slot["label"] = (picked or {}).get("label") or case_label_slot(
            slot["start"], slot["end"], _tenant_language(s, case))
        s.add(tech)
        case.status = "scheduled"
        _patch_data(case, technician={"tech_id": tech.id, "name": tech.name,
                                      "confirmed_at": now_iso()})
        _save_case(s, case)
        name = tech.name
    when = slot_clock(slot["start"], slot["end"])
    record_event(case_id, "partner", "technician.confirmed", f"Technician {name} confirmed {when}",
                 {"tech_id": tech_id, "technician_name": name, "slot": slot})
    return {"case_id": case_id, "status": "scheduled", "slot": slot,
            "technician": {"tech_id": tech_id, "name": name}}


async def record_completion(case_id: str, partner_id: str, notes: str,
                            photo: tuple[str, str, bytes] | None,
                            invoice: tuple[str, str, bytes] | None) -> dict:
    """Partner marks done: store photo + PDF, extract + price-check the invoice,
    attach both to case and unit. (filename, mime, bytes) tuples."""
    from . import media  # late import: agent-whatsapp replaces this module

    with get_session() as s:
        case = _get(s, Case, case_id)
        if case.partner_id != partner_id:
            raise rules.RuleViolation("not_assigned", "this job is not assigned to you")
        case.status = "completed"
        _patch_data(case, completion={"notes": notes, "completed_at": now_iso()})
        _save_case(s, case)
        name = s.get(Partner, partner_id).manifest.get("name", partner_id)
    record_event(case_id, "partner", "job.completed", f"{name} marked the job done" +
                 (f": {notes}" if notes else ""), {"notes": notes})

    out: dict = {"photo": None, "invoice": None, "price_check": None}
    folder = Path(settings.storage_dir) / case_id
    folder.mkdir(parents=True, exist_ok=True)
    if photo:
        fname, mime, data = photo
        base = Path(fname).name
        p = folder / (base if base.startswith("after") else f"after_{base}")
        p.write_bytes(data)
        out["photo"] = attach_document(case_id, "photo", p.name, mime or "image/jpeg", str(p)).id
    if invoice:
        fname, mime, data = invoice
        p = folder / Path(fname).name
        p.write_bytes(data)
        extracted = await media.extract_invoice(str(p))
        with get_session() as s:
            check = rules.price_check(s, partner_id, extracted)
        doc = attach_document(case_id, "invoice", p.name, mime or "application/pdf", str(p),
                              {**extracted, "price_check": check})
        out["invoice"] = doc.id
        out["price_check"] = check
        with get_session() as s:
            case = s.get(Case, case_id)
            case.status = "invoiced"
            _patch_data(case, invoice={"document_id": doc.id, **extracted}, price_check=check)
            _save_case(s, case)
        gross = extracted.get("gross_eur")
        record_event(case_id, "debye", "invoice.checked",
                     f"Invoice {extracted.get('invoice_number')} €{gross} – price check {check['result']}",
                     {"document_id": doc.id, "price_check": check, "invoice": extracted})
    return out


def tenant_confirms_fixed(case_id: str, fixed: bool) -> dict:
    add_tenant_input(case_id, "tap: fixed" if fixed else "tap: not fixed")
    if fixed:
        record_event(case_id, "tenant", "tenant.confirmed_fixed", "Tenant confirmed: warm again")
        with get_session() as s:
            case = _get(s, Case, case_id)
            resolution = ((case.data or {}).get("completion") or {}).get("notes") or "Repaired"
        return close_case(case_id, resolution)
    with get_session() as s:
        case = _get(s, Case, case_id)
        case.status = "reopened"
        _save_case(s, case)
    record_event(case_id, "tenant", "case.reopened", "Tenant says it is still not working")
    return {"case_id": case_id, "status": "reopened"}


def close_case(case_id: str, resolution: str) -> dict:
    """Writes the result payload (technical-plan §12) to the case and as a report on the unit."""
    with get_session() as s:
        case = _get(s, Case, case_id)
        partner = s.get(Partner, case.partner_id) if case.partner_id else None
        links = s.exec(select(CaseContact).where(CaseContact.case_id == case_id)).all()
        affected_units = []
        for l in links:
            c = s.get(Contact, l.contact_id)
            if c and c.unit_id and c.unit_id not in affected_units:
                affected_units.append(c.unit_id)
        consent = None
        if case.partner_id:
            consent = s.exec(select(Consent).where(Consent.case_id == case_id,
                                                   Consent.partner_id == case.partner_id)
                             .order_by(Consent.given_at.desc())).first()
        inv = (case.data or {}).get("invoice") or {}
        check = (case.data or {}).get("price_check") or {}
        result = {
            "unit_id": case.unit_id,
            "contact_id": case.reporter_contact_id,
            "service_job": {
                "partner": partner.manifest.get("name") if partner else None,
                "technician": ((case.data or {}).get("technician") or {}).get("name"),
                "category": case.type,
                "case_id": case.id,
                "status": "closed",
                "visit": {"start": case.slot_start, "end": case.slot_end},
                "resolution": resolution,
                "invoice": {"number": inv.get("invoice_number"), "gross_eur": inv.get("gross_eur"),
                            "document_id": inv.get("document_id"),
                            "price_check": check.get("result")} if inv else None,
                "affected_units": affected_units,
                "consent": {"data_shared": consent.data_shared, "given_at": consent.given_at,
                            "channel": consent.channel} if consent else None,
            },
        }
        case.status = "closed"
        case.closed_at = now_iso()
        _patch_data(case, result=result, resolution=resolution)
        _save_case(s, case)
    folder = Path(settings.storage_dir) / case_id
    folder.mkdir(parents=True, exist_ok=True)
    report = folder / f"report_{case_id}.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    attach_document(case_id, "report", report.name, "application/json", str(report), result)
    record_event(case_id, "debye", "case.closed", f"Case closed: {resolution}",
                 {"result": result})
    return result


def get_case_contacts(case_id: str) -> list[Contact]:
    """Reporter first, then affected tenants."""
    with get_session() as s:
        links = s.exec(select(CaseContact).where(CaseContact.case_id == case_id)).all()
        links = sorted(links, key=lambda l: l.relation != "reporter")
        return [c for c in (s.get(Contact, l.contact_id) for l in links) if c]


# --------------------------------------------------------------------------- extras

def add_tenant_input(case_id: str, label: str) -> None:
    """Zero-forms counter: record one tenant input (voice note, tap, photo)."""
    with get_session() as s:
        case = s.get(Case, case_id)
        if not case:
            return
        inputs = list((case.data or {}).get("tenant_inputs", []))
        inputs.append(label)
        _patch_data(case, tenant_inputs=inputs)
        _save_case(s, case)


def log_message(contact_id: str | None, case_id: str | None, channel: str, direction: str,
                text: str | None, wa_message_id: str | None = None,
                media_ids: list[str] | None = None) -> Message:
    """Store a WhatsApp message and publish message.in / message.out for the staff page."""
    with get_session() as s:
        msg = Message(id=next_id(s, Message, "msg"), case_id=case_id, contact_id=contact_id,
                      channel=channel, direction=direction, wa_message_id=wa_message_id,
                      text=text, media_ids=media_ids or [], ts=now_iso())
        s.add(msg)
        s.commit()
        s.refresh(msg)
        contact = s.get(Contact, contact_id) if contact_id else None
    payload = {"ts": msg.ts, "direction": direction,
               "contact": contact.name if contact else None, "contact_id": contact_id,
               "text": text, "media": [{"document_id": d, "url": f"/files/{d}"} for d in msg.media_ids],
               "message_id": msg.id}
    publish_sync("message.in" if direction == "in" else "message.out", case_id, payload)
    return msg


def message_seen(wa_message_id: str) -> bool:
    """Dedupe helper for webhook retries."""
    if not wa_message_id:
        return False
    with get_session() as s:
        return s.exec(select(Message).where(Message.wa_message_id == wa_message_id)).first() is not None
