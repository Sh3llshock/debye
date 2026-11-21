"""Partners on WhatsApp: the "conversational" transport of the connector spec (§4).

1. Handshake (sign-up). The company types its number, gets a one-time code (DEBYE-7KQ2X9) and a
   wa.me link, and sends that code to Debye's number from its phone. Because THEY write first:
   - the code proves they own the number (the number that sent it is the one we store),
   - the message is their opt-in (stored with time and message id),
   - the conversation is open, so Debye can answer at once (no template needed on the Cloud API).
   Debye replies with a test button; the tap coming back proves both directions work.
   pending → received → replied → verified. Only a verified number can become a WhatsApp partner.

2. Jobs. After Anna approves, the job goes out as a WhatsApp message with only the consented fields
   and three buttons (two suggested slots + decline). The partner answers by button or in plain words
   ("Ja, morgen 8–10", "nein, keine Zeit", "erledigt" + invoice PDF). Every answer becomes the same
   status_event the API partners send (partner_events_api.apply_event), so the lifecycle, the
   tenant messages and the staff page work exactly as for API and portal partners.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import secrets
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException
from sqlmodel import select

from ..channels.base import Option, normalize_phone
from ..config import now, now_iso
from ..db import get_session, next_id
from ..events import record_event
from ..models import Case, Contact, Partner, WhatsAppLink
from . import transport
from .manifest import Manifest

log = logging.getLogger("debye.wa_partner")

CODE_RE = re.compile(r"\bDEBYE-([A-Z0-9]{6})\b", re.IGNORECASE)
CODE_TTL = timedelta(minutes=30)
TEST_BUTTON = "wa_link_test"
OPEN_STATES = {"requested", "accepted", "slots_proposed", "awaiting_technician", "scheduled", "completed"}

_main_loop: asyncio.AbstractEventLoop | None = None
_tasks: set = set()


# =========================================================================== helpers

def debye_number() -> str:
    """Debye's WhatsApp number (E.164) for the wa.me link: DEBYE_WHATSAPP_NUMBER."""
    return (os.getenv("DEBYE_WHATSAPP_NUMBER") or "").strip()


def _digits(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")


def _norm(phone: str | None) -> str | None:
    d = _digits(phone)
    if not d:
        return None
    if (phone or "").strip().startswith("00"):
        d = d[2:]
    return normalize_phone(d)


def is_whatsapp(manifest: dict | Manifest | None) -> bool:
    if manifest is None:
        return False
    t = (manifest.transport if isinstance(manifest, Manifest) else manifest.get("transport")) or {}
    return t.get("type") == "conversational" and t.get("channel") == "whatsapp" and bool(t.get("address"))


def _lang(m: Manifest) -> str:
    return "en" if ((m.transport or {}).get("language") or "de") == "en" else "de"


def _t(m: Manifest, de: str, en: str) -> str:
    return en if _lang(m) == "en" else de


def _manifest(partner_id: str) -> Manifest | None:
    with get_session() as s:
        p = s.get(Partner, partner_id)
        return Manifest.model_validate(p.manifest) if p else None


def partner_for_phone(phone: str | None) -> str | None:
    """The WhatsApp partner whose verified address is this number."""
    n = _norm(phone)
    if not n:
        return None
    with get_session() as s:
        for p in s.exec(select(Partner)).all():
            t = (p.manifest or {}).get("transport") or {}
            if is_whatsapp(p.manifest) and _norm(t.get("address")) == n:
                return p.id
    return None


def _partner_contact(partner_id: str, phone: str, name: str | None = None) -> Contact:
    """The partner_staff contact behind the WhatsApp number (created on first use)."""
    phone = _norm(phone) or phone
    with get_session() as s:
        c = s.exec(select(Contact).where(Contact.phone_e164 == phone)).first()
        if c is None:
            c = Contact(id=next_id(s, Contact, "c"), role="partner_staff", name=name or partner_id,
                        phone_e164=phone, partner_id=partner_id, language="de", whatsapp_opt_in=True)
        else:
            c.partner_id = c.partner_id or partner_id
            c.whatsapp_opt_in = True
            if c.role not in ("partner_staff",):
                log.warning("number %s already belongs to a %s; not changing its role", phone, c.role)
        s.add(c)
        s.commit()
        s.refresh(c)
        return c


def _channel(phone: str):
    from ..channels.base import channel_for
    return channel_for(phone)


# =========================================================================== 1. handshake

def _view(link: WhatsAppLink) -> dict:
    num = _digits(debye_number())
    text = f"{link.code} Hallo Debye, bitte verbinden."
    expired = link.status != "verified" and link.expires_at < now_iso()
    return {
        "id": link.id, "code": link.code, "status": "expired" if expired else link.status,
        "company": link.company, "phone_entered": link.phone_entered, "phone_e164": link.phone_e164,
        "number_changed": bool(link.phone_e164 and link.phone_entered
                               and _norm(link.phone_entered) != link.phone_e164),
        "debye_number": debye_number() or None,
        "wa_link": f"https://wa.me/{num}?text={quote(text)}" if num else None,
        "message": text, "expires_at": link.expires_at,
        "steps": [
            {"id": "received", "label": "Your message reached Debye", "at": link.received_at},
            {"id": "replied", "label": "Debye's reply was delivered", "at": link.replied_at},
            {"id": "verified", "label": "Your test answer came back", "at": link.verified_at},
        ],
        "error": link.error,
    }


def start(phone: str | None, company: str | None, partner_id: str | None = None) -> dict:
    """New one-time code for the sign-up form (or to re-link an existing partner)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I
    with get_session() as s:
        while True:
            code = "DEBYE-" + "".join(secrets.choice(alphabet) for _ in range(6))
            if not s.exec(select(WhatsAppLink).where(WhatsAppLink.code == code)).first():
                break
        link = WhatsAppLink(id="wal_" + secrets.token_hex(6), code=code, company=(company or "").strip() or None,
                            phone_entered=_norm(phone), partner_id=partner_id, created_at=now_iso(),
                            expires_at=(now() + CODE_TTL).isoformat(timespec="seconds"))
        s.add(link)
        s.commit()
        s.refresh(link)
        return _view(link)


def status(link_id: str) -> dict | None:
    with get_session() as s:
        link = s.get(WhatsAppLink, link_id)
        return _view(link) if link else None


def verified_link(link_id: str | None) -> WhatsAppLink | None:
    if not link_id:
        return None
    with get_session() as s:
        link = s.get(WhatsAppLink, link_id)
        return link if link and link.status == "verified" else None


def transport_from_link(link: WhatsAppLink, partner_id: str, language: str = "de") -> dict:
    return {"type": "conversational", "channel": "whatsapp", "address": link.phone_e164,
            "language": language, "verified_at": link.verified_at, "link_id": link.id,
            "opt_in": {"at": link.received_at, "message_id": link.message_id, "channel": link.channel},
            "url": f"/partner/{partner_id}"}


def attach_to_partner(link_id: str, partner_id: str, contact_name: str | None = None) -> None:
    """After sign-up: bind the verified number to the partner and create its staff contact."""
    with get_session() as s:
        link = s.get(WhatsAppLink, link_id)
        if not link:
            return
        link.partner_id = partner_id
        s.add(link)
        s.commit()
        phone, name = link.phone_e164, contact_name or link.profile_name
    if phone:
        _partner_contact(partner_id, phone, name)


def _find_link_by_code(code: str) -> WhatsAppLink | None:
    with get_session() as s:
        return s.exec(select(WhatsAppLink).where(WhatsAppLink.code == code.upper())).first()


async def try_handshake(msg) -> bool:
    """Router hook, before anything else: a sign-up code or the test-button answer. True = handled."""
    phone = _norm(msg.from_phone)
    bid = msg.button_id or ""
    if bid.startswith(TEST_BUTTON + ":"):
        return await _on_test_answer(msg, bid.split(":", 1)[1], phone)
    m = CODE_RE.search(msg.text or "")
    if not m:
        # a typed "ok"/"1" instead of the button, from a number that is mid-handshake
        if (msg.text or "").strip() and len(msg.text) < 40 and phone:
            try:
                with get_session() as s:
                    link = s.exec(select(WhatsAppLink).where(WhatsAppLink.phone_e164 == phone,
                                                             WhatsAppLink.status == "replied")).first()
            except Exception:  # no handshake table (agent unit tests with a stub backend)
                link = None
            if link and link.expires_at >= now_iso():
                return await _on_test_answer(msg, link.id, phone)
        return False
    link = _find_link_by_code("DEBYE-" + m.group(1))
    ch = _channel_for_msg(msg)
    if link is None or (link.status != "verified" and link.expires_at < now_iso()):
        await _send_text(ch, phone, "Dieser Code ist unbekannt oder abgelaufen. Bitte starten Sie die "
                                    "Verbindung auf der Anmeldeseite neu. / This code is unknown or expired.")
        return True
    if link.status == "verified":
        await _send_text(ch, phone, "Diese Nummer ist bereits mit Debye verbunden. ✅")
        return True
    with get_session() as s:
        link = s.get(WhatsAppLink, link.id)
        link.status, link.phone_e164 = "received", phone
        link.channel, link.profile_name = msg.channel, msg.profile_name
        link.message_id, link.received_at = msg.wa_message_id, now_iso()
        s.add(link)
        s.commit()
        link_id, company = link.id, link.company
    record_event(None, "partner", "partner.whatsapp_received",
                 f"{company or phone}: WhatsApp sign-up message received from {phone}",
                 {"link_id": link_id, "phone": phone})
    text = (f"✅ Hallo{(' ' + company) if company else ''}! Ihre Nachricht ist bei Debye angekommen.\n"
            "Letzter Schritt: Tippen Sie auf „Test bestätigen“, damit wir sehen, dass Antworten "
            "in beide Richtungen funktionieren.")
    try:
        await ch.send_buttons(phone, text, [Option(f"{TEST_BUTTON}:{link_id}", "Test bestätigen")])
        err = None
    except Exception as e:  # the line is not usable: show it on the sign-up page
        log.exception("handshake reply to %s failed", phone)
        err = f"Reply could not be delivered ({type(e).__name__})"
    with get_session() as s:
        link = s.get(WhatsAppLink, link_id)
        if err:
            link.error = err
        else:
            link.status, link.replied_at = "replied", now_iso()
        s.add(link)
        s.commit()
    return True


async def _on_test_answer(msg, link_id: str, phone: str | None) -> bool:
    ch = _channel_for_msg(msg)
    with get_session() as s:
        link = s.get(WhatsAppLink, link_id)
        if link is None or link.phone_e164 != phone or link.status not in ("replied", "received", "verified"):
            return False
        already = link.status == "verified"
        if not already:
            link.status, link.verified_at = "verified", now_iso()
            s.add(link)
            s.commit()
        partner_id, company = link.partner_id, link.company
    if not already:
        record_event(None, "partner", "partner.whatsapp_verified",
                     f"{company or phone}: WhatsApp verified ({phone}), replies work both ways",
                     {"link_id": link_id, "phone": phone, "partner_id": partner_id})
        if partner_id:  # re-link of an existing partner: switch its transport now
            _relink_partner(partner_id, link_id)
    await _send_text(ch, phone, "🎉 Verbunden! Neue Aufträge kommen ab jetzt hier per WhatsApp. "
                                "Sie antworten einfach, z. B. „Ja, morgen 8–10“.")
    return True


def _relink_partner(partner_id: str, link_id: str) -> None:
    with get_session() as s:
        p = s.get(Partner, partner_id)
        link = s.get(WhatsAppLink, link_id)
        if not p or not link:
            return
        lang = ((p.manifest or {}).get("transport") or {}).get("language") or "de"
        p.manifest = {**p.manifest, "transport": transport_from_link(link, partner_id, lang)}
        s.add(p)
        s.commit()
    attach_to_partner(link_id, partner_id)


def _channel_for_msg(msg):
    from ..channels.base import get_channel
    try:
        return get_channel(msg.channel)
    except KeyError:
        return _channel(msg.from_phone)


async def _send_text(ch, phone: str, text: str) -> None:
    try:
        await ch.send_text(phone, text)
    except Exception:
        log.exception("send to %s failed", phone)


# =========================================================================== 2. jobs: outbound

def queue_offer(case_id: str, partner_id: str) -> None:
    """Called from services.dispatch_job (sync). Runs the async send on the app's loop."""
    coro = offer_job(case_id, partner_id)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        t = loop.create_task(coro)
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)
    elif _main_loop is not None and _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, _main_loop)
    else:
        asyncio.run(coro)


def remember_loop() -> None:
    global _main_loop
    try:
        _main_loop = asyncio.get_running_loop()
    except RuntimeError:
        pass


def _when(slot: dict, lang: str = "de") -> str:
    from .. import services
    return services.case_label_slot(slot["start"], slot["end"], lang)


def _context_lines(m: Manifest, body: dict) -> list[str]:
    ctx = body.get("context") or {}
    case = body.get("case") or {}
    lines = []
    asset = ctx.get("asset") or {}
    device = " ".join(x for x in (asset.get("make"), asset.get("model")) if x)
    what = case.get("summary") or case.get("title") or ""
    code = ctx.get("error_code") or case.get("error_code")
    shown_code = (_t(m, "Fehler ", "error ") + code) if code and code.lower() not in what.lower() else ""
    lines.append(" · ".join(x for x in (what, device, shown_code) if x))
    where = ctx.get("address")
    floor = ctx.get("unit_floor")
    if where or floor is not None:
        lines.append(" · ".join(x for x in (where, (_t(m, f"{floor}. OG", f"floor {floor}") if floor not in (None, "")
                                                   else "")) if x))
    if body.get("cost_cap_eur"):
        lines.append(_t(m, f"Kostenrahmen bis €{body['cost_cap_eur']:.0f}", f"Budget up to €{body['cost_cap_eur']:.0f}"))
    photos = ctx.get("photos") or []
    if photos:
        lines.append(_t(m, f"📷 {len(photos)} Foto(s) folgen", f"📷 {len(photos)} photo(s) follow"))
    return lines


async def offer_job(case_id: str, partner_id: str) -> dict | None:
    """The job card on WhatsApp: consented fields only, 2 slot buttons + decline."""
    m = _manifest(partner_id)
    if m is None or not is_whatsapp(m):
        return None
    address = (m.transport or {}).get("address")
    with get_session() as s:
        case = s.get(Case, case_id)
        body = transport.build_order(s, case, m)
    hints = body.get("slot_hints") or transport.slot_hints()
    urgent = (body.get("priority") == "urgent")
    head = _t(m, "🔧 Neuer Auftrag über Debye", "🔧 New job via Debye") + (_t(m, " · DRINGEND", " · URGENT") if urgent else "")
    text = "\n".join([head, *_context_lines(m, body), "",
                      _t(m, "Passt einer dieser Termine? Oder antworten Sie einfach, z. B. „Ja, Montag 10–12“.",
                         "Does one of these times work? Or just reply, e.g. \"Yes, Monday 10-12\".")])
    lang = _lang(m)
    options = [Option(f"wa_job_slot:{case_id}:{i}", _when(h, lang)[:20]) for i, h in enumerate(hints[:2])]
    options.append(Option(f"wa_job_decline:{case_id}", _t(m, "Ablehnen", "Decline")))
    order = {"order_ref": body["order_ref"], "partner_order_id": None, "status": "requested",
             "transport": "whatsapp", "address": address, "sent_at": body["sent_at"],
             "context_keys": sorted(body.get("context") or {}), "slot_hints": hints[:2]}
    contact = _partner_contact(partner_id, address, m.name)
    from ..agent import outbound as out
    error = None
    try:
        await out.buttons(contact, case_id, text, options)
        for p in (body.get("context") or {}).get("photos") or []:
            path = _doc_path(p.get("url"))
            if path:
                await out.media(contact, case_id, "image", path, p.get("filename"))
    except Exception as e:
        error = f"WhatsApp to {address} failed ({type(e).__name__})"
        log.exception("job offer %s to %s failed", case_id, partner_id)
    with get_session() as s:
        case = s.get(Case, case_id)
        case.data = {**(case.data or {}), "partner_order": {**order, **({"error": error} if error else {})}}
        case.updated_at = now_iso()
        s.add(case)
        s.commit()
    if error:
        record_event(case_id, "system", "job.send_failed", f"Job to {m.name} not delivered: {error}",
                     {"partner_id": partner_id, "order_ref": order["order_ref"], "error": error})
    else:
        record_event(case_id, "debye", "order.sent", f"Job sent to {m.name} on WhatsApp ({address})",
                     {"partner_id": partner_id, "order_ref": order["order_ref"], "transport": "whatsapp",
                      "context_keys": order["context_keys"]})
    return order


def _doc_path(url: str | None) -> str | None:
    if not url or not url.startswith("/files/"):
        return None
    from ..models import Document
    with get_session() as s:
        d = s.get(Document, url.rsplit("/", 1)[-1])
        return d.path if d and Path(d.path).exists() else None


async def on_tenant_picked_slot(case_id: str) -> None:
    """flow.on_slot hook: the tenant picked one of the partner's times → ask the partner to confirm."""
    with get_session() as s:
        case = s.get(Case, case_id)
        if not case or not case.partner_id:
            return
        p = s.get(Partner, case.partner_id)
        if not p or not is_whatsapp(p.manifest):
            return
        m = Manifest.model_validate(p.manifest)
        st, slot = case.status, {"start": case.slot_start, "end": case.slot_end}
        tech = ((case.data or {}).get("technician") or {}).get("name")
        tenant = s.get(Contact, case.reporter_contact_id) if case.reporter_contact_id else None
    if not slot["start"]:
        return
    contact = _partner_contact(m.partner_id, m.transport["address"], m.name)
    from ..agent import outbound as out
    who = (tenant.name.split()[0] if tenant and tenant.name else _t(m, "Der Mieter", "The tenant"))
    when = _when(slot, _lang(m))
    if st == "awaiting_technician":
        await out.buttons(contact, case_id,
                          _t(m, f"📅 {who} hat {when} gewählt" + (f" für {tech}" if tech else "") + ". Bestätigen Sie den Termin?",
                             f"📅 {who} picked {when}" + (f" for {tech}" if tech else "") + ". Confirm the visit?"),
                          [Option(f"wa_job_confirm:{case_id}", _t(m, "Bestätigen", "Confirm"))])
    else:
        await _booked_message(m, case_id, contact)


async def _booked_message(m: Manifest, case_id: str, contact) -> None:
    """After the booking: the details that are shared just in time (consented only)."""
    from ..agent import outbound as out
    with get_session() as s:
        case = s.get(Case, case_id)
        body = transport.build_order(s, case, m)
        slot = {"start": case.slot_start, "end": case.slot_end}
    ctx = body.get("context") or {}
    bits = [_t(m, f"✅ Gebucht: {_when(slot, _lang(m))}", f"✅ Booked: {_when(slot, _lang(m))}")]
    if ctx.get("address"):
        bits.append(ctx["address"])
    if ctx.get("tenant_name") or ctx.get("tenant_phone"):
        bits.append(" · ".join(x for x in (ctx.get("tenant_name"), ctx.get("tenant_phone")) if x))
    acc = ctx.get("access_details")
    if isinstance(acc, dict) and acc:
        names = {"key_safe_code": ("Schlüsseltresor", "Key safe"), "intercom_name": ("Klingel", "Doorbell"),
                 "parking_note": ("Parken", "Parking")}
        for k, v in acc.items():
            de, en = names.get(k, (k.replace("_", " "), k.replace("_", " ")))
            bits.append(f"🔑 {_t(m, de, en)}: {v}")
    bits.append(_t(m, "Nach dem Einsatz einfach „erledigt“ schreiben und die Rechnung als PDF schicken.",
                   "After the visit just write \"done\" and send the invoice as a PDF."))
    await out.text(contact, case_id, "\n".join(bits))


# =========================================================================== 2. jobs: inbound

_DAY = (r"übermorgen|uebermorgen|heute|morgen|today|tomorrow|montag|dienstag|mittwoch|donnerstag|freitag|samstag|"
        r"sonntag|monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|mo|di|mi|do|fr|sa")
_SLOT_RE = re.compile(
    rf"(?:(?<![a-zäöüß])({_DAY})\b\.?[^\d\n]{{0,14}}?)?(?<![\d:.])(\d{{1,2}})(?:[:.](\d{{2}}))?\s*(?:uhr|h)?\s*"
    rf"(?:-|–|—|bis|to|until)\s*(\d{{1,2}})(?:[:.](\d{{2}}))?(?!\d)", re.IGNORECASE)
_WEEKDAY = {"mo": 0, "montag": 0, "monday": 0, "mon": 0, "di": 1, "dienstag": 1, "tuesday": 1, "tue": 1,
            "mi": 2, "mittwoch": 2, "wednesday": 2, "wed": 2, "do": 3, "donnerstag": 3, "thursday": 3, "thu": 3,
            "fr": 4, "freitag": 4, "friday": 4, "fri": 4, "sa": 5, "samstag": 5, "saturday": 5, "sat": 5,
            "sonntag": 6, "sunday": 6}
_REL = {"heute": 0, "today": 0, "morgen": 1, "tomorrow": 1, "übermorgen": 2, "uebermorgen": 2}
_DECLINE_RE = re.compile(r"^\s*(nein|no\b|nope|ablehnen|leider nicht|leider nein|keine zeit|geht nicht|kann nicht|"
                         r"decline|can'?t)", re.IGNORECASE)
_DONE_RE = re.compile(r"\b(erledigt|fertig|repariert|abgeschlossen|done|finished|fixed)\b", re.IGNORECASE)
_YES_RE = re.compile(r"^\s*(ja|jo|yes|ok|okay|passt|gerne|annehmen|übernehmen|uebernehmen|machen wir|klar|"
                     r"bestätig|bestaetig|confirm|top|👍)", re.IGNORECASE)


def parse_slots(text: str) -> list[dict]:
    """'Ja, morgen 8–10', 'Montag 10-12 oder 14-16', 'tomorrow 14:00-16:00' → [{start, end}] (demo clock)."""
    out, day = [], None
    today = now()
    for mt in _SLOT_RE.finditer(text or ""):
        word, h0, m0, h1, m1 = mt.groups()
        if word:
            w = word.lower()
            if w in _REL:
                day = (today + timedelta(days=_REL[w])).date()
            else:
                ahead = (_WEEKDAY[w] - today.weekday()) % 7 or 7
                day = (today + timedelta(days=ahead)).date()
        d = day or (today + timedelta(days=1)).date()
        a, b = int(h0), int(h1)
        if not (0 <= a < b <= 23):
            continue
        st = today.replace(year=d.year, month=d.month, day=d.day, hour=a, minute=int(m0 or 0), second=0, microsecond=0)
        en = st.replace(hour=b, minute=int(m1 or 0))
        if st <= today:
            continue
        out.append({"start": st.isoformat(timespec="seconds"), "end": en.isoformat(timespec="seconds")})
    return out[:3]


def interpret(text: str | None, case_status: str, has_pdf: bool = False) -> dict:
    """Plain words → {intent, slots, reason}. Deterministic first; the model only for leftovers."""
    t = (text or "").strip()
    if has_pdf and (case_status in ("completed", "scheduled") or _DONE_RE.search(t)):
        return {"intent": "done", "slots": [], "reason": ""}
    if _DECLINE_RE.search(t):
        return {"intent": "decline", "slots": [], "reason": t}
    if _DONE_RE.search(t):
        return {"intent": "done", "slots": [], "reason": ""}
    slots = parse_slots(t)
    if slots:
        return {"intent": "accept", "slots": slots, "reason": ""}
    if _YES_RE.search(t):
        return {"intent": "confirm" if case_status == "awaiting_technician" else "accept", "slots": [], "reason": ""}
    if t.endswith("?"):
        return {"intent": "question", "slots": [], "reason": t}
    return {"intent": "unclear", "slots": [], "reason": ""}


async def _llm_interpret(text: str, case_status: str) -> dict | None:
    """Optional: one strict structured-output call for replies the rules don't catch."""
    if not os.getenv("OPENAI_API_KEY") or (os.getenv("LLM_PROVIDER") or "openai").lower() != "openai":
        return None
    try:
        from openai import AsyncOpenAI
        from ..media import openai_base_url
        schema = {"type": "object", "additionalProperties": False, "required": ["intent", "slots", "reason"],
                  "properties": {
                      "intent": {"type": "string", "enum": ["accept", "decline", "done", "confirm", "question", "unclear"]},
                      "slots": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                           "required": ["start", "end"],
                                                           "properties": {"start": {"type": "string"},
                                                                          "end": {"type": "string"}}}},
                      "reason": {"type": "string"}}}
        client = AsyncOpenAI(base_url=openai_base_url(), timeout=8, max_retries=0)
        r = await client.chat.completions.create(
            model=os.getenv("OPENAI_CHAT_MODEL") or "gpt-6-luna",
            messages=[{"role": "system", "content":
                       f"A craftsman answers a repair job on WhatsApp. Now: {now_iso()} (Europe/Berlin). "
                       f"Job status: {case_status}. Classify the reply. accept = takes the job (slots = the times "
                       "he offers as ISO-8601 with +01:00, empty if none); decline = refuses (reason); done = job "
                       "finished; confirm = confirms the booked visit; question = asks something (reason = the "
                       "question). Never invent times."},
                      {"role": "user", "content": text}],
            response_format={"type": "json_schema", "json_schema": {"name": "reply", "strict": True, "schema": schema}})
        return json.loads(r.choices[0].message.content or "{}")
    except Exception:
        log.exception("partner reply interpretation failed")
        return None


def _bookable(partner_id: str, slots: list[dict]) -> list[dict]:
    """The offered times one technician can actually do (the largest set), so a reply like
    "morgen 14–16 oder übermorgen 9–11" isn't refused because one of them clashes."""
    from ..models import Technician
    from .technicians import is_free
    with get_session() as s:
        techs = s.exec(select(Technician).where(Technician.partner_id == partner_id)).all()
    if not techs:
        return slots
    best: list[dict] = []
    for t in techs:
        ok = [sl for sl in slots if is_free(t.busy, sl)]
        if len(ok) > len(best):
            best = ok
    return best


def _active_case(partner_id: str) -> Case | None:
    with get_session() as s:
        cases = s.exec(select(Case).where(Case.partner_id == partner_id).order_by(Case.updated_at.desc())).all()
        for c in cases:
            if c.status in OPEN_STATES and ((c.data or {}).get("partner_order") or {}).get("transport") == "whatsapp":
                return c
    return None


def _ev(case: Case, partner_id: str, status: str, data: dict | None = None, documents=None):
    from ..partner_events_api import EventDocument, StatusEvent
    return StatusEvent(order_ref=transport.order_ref(case.id), partner_id=partner_id, status=status,
                       at=now_iso(), data=data or {}, documents=[EventDocument(**d) for d in (documents or [])])


def _doc(path: str, kind: str, mime: str, name: str | None = None) -> dict:
    return {"kind": kind, "filename": name or Path(path).name, "mime": mime,
            "base64": base64.b64encode(Path(path).read_bytes()).decode()}


async def handle_message(contact, partner_id: str, msg, text: str | None, files: list[tuple[str, str, str | None]]) -> None:
    """A message from a WhatsApp partner. files: [(local_path, mime, filename)]."""
    from .. import services
    from ..agent import outbound as out
    m = _manifest(partner_id)
    bid = msg.button_id or ""
    case = None
    if bid.startswith("wa_job_"):
        cid = bid.split(":")[1] if ":" in bid else None
        case = services.get_case(cid) if cid else None
    case = case or _active_case(partner_id)
    shown = msg.button_title or text or ("📎 " + ", ".join(f[2] or Path(f[0]).name for f in files) if files else "")
    if case is None:
        await out.text(contact, None, _t(m, "Danke! Im Moment ist kein offener Auftrag für Sie da.",
                                         "Thanks! There's no open job for you right now."))
        return
    record_event(case.id, "partner", "partner.whatsapp", f"{m.name} (WhatsApp): „{shown}“",
                 {"partner_id": partner_id, "text": shown, "button_id": bid or None})

    pdfs = [f for f in files if f[1] == "application/pdf" or (f[2] or f[0]).lower().endswith(".pdf")]
    photos = [f for f in files if f[1].startswith("image/")]
    if bid.startswith("wa_job_slot:"):
        idx = int(bid.split(":")[2]) if bid.count(":") >= 2 and bid.split(":")[2].isdigit() else 0
        hints = ((case.data or {}).get("partner_order") or {}).get("slot_hints") or transport.slot_hints()
        intent = {"intent": "accept", "slots": [hints[min(idx, len(hints) - 1)]], "reason": ""}
    elif bid.startswith("wa_job_decline:"):
        intent = {"intent": "decline", "slots": [], "reason": ""}
    elif bid.startswith("wa_job_confirm:"):
        intent = {"intent": "confirm", "slots": [], "reason": ""}
    else:
        intent = interpret(text, case.status, has_pdf=bool(pdfs))
        if intent["intent"] == "unclear" and text and not files:
            intent = await _llm_interpret(text, case.status) or intent
        if intent["intent"] == "unclear" and photos and not text:
            intent = {"intent": "photo", "slots": [], "reason": ""}

    try:
        await _act(m, case, intent, text, photos, pdfs, contact)
    except HTTPException as e:
        log.info("partner reply not applied (%s): %s", e.status_code, e.detail)
        await out.text(contact, case.id, _t(m, f"Das ging gerade nicht: {e.detail}", f"That didn't work: {e.detail}"))
    except Exception:
        log.exception("partner WhatsApp reply failed")
        await out.text(contact, case.id, _t(m, "Da ist etwas schiefgelaufen. Die Hausverwaltung ist informiert.",
                                            "Something went wrong. The property manager has been told."))


async def _act(m: Manifest, case: Case, intent: dict, text, photos, pdfs, contact) -> None:
    from .. import notify, services
    from ..agent import outbound as out
    from ..partner_events_api import apply_event
    pid, kind = m.partner_id, intent.get("intent")
    st = case.status
    lang = _lang(m)

    if kind == "decline":
        await apply_event(m, _ev(case, pid, "declined", {"reason": intent.get("reason") or "declined on WhatsApp"}),
                          via="WhatsApp")
        await out.text(contact, case.id, _t(m, "Alles klar, danke für die schnelle Antwort! Wir fragen den nächsten Partner.",
                                            "Got it, thanks for the quick answer! We'll ask the next partner."))
        return

    if kind == "accept":
        slots = [x for x in intent.get("slots") or [] if x.get("start") and x.get("end")]
        if st not in ("requested", "accepted", "slots_proposed"):
            await out.text(contact, case.id, _t(m, "Der Auftrag ist schon weiter, danke!", "That job has moved on already, thanks!"))
            return
        if slots:
            free = _bookable(pid, slots)
            if not free:
                await out.text(contact, case.id, _t(m, "Zu diesen Zeiten ist laut Kalender kein Techniker frei. Welche andere Zeit geht?",
                                                    "No technician is free at those times in your calendar. What other time works?"))
                return
            slots = free
        if st == "requested" or slots:
            await apply_event(m, _ev(case, pid, "accepted", {"slots": slots} if slots else {}), via="WhatsApp")
        if slots:
            whens = " oder ".join(_when(x, lang) for x in slots) if lang == "de" else " or ".join(_when(x, lang) for x in slots)
            await out.text(contact, case.id, _t(m, f"👍 Danke, angenommen! Ich biete dem Mieter {whens} an und melde mich, sobald er gewählt hat.",
                                                f"👍 Thanks, accepted! I'm offering the tenant {whens} and will tell you once they pick."))
        else:
            hints = transport.slot_hints()
            with get_session() as s:
                c = s.get(Case, case.id)
                c.data = {**(c.data or {}), "partner_order": {**((c.data or {}).get("partner_order") or {}), "slot_hints": hints[:2]}}
                s.add(c)
                s.commit()
            await out.buttons(contact, case.id, _t(m, "👍 Danke, angenommen! Wann können Sie? Tippen Sie einen Termin oder schreiben Sie z. B. „Montag 10–12“.",
                                                   "👍 Thanks, accepted! When can you come? Tap a time or write e.g. \"Monday 10-12\"."),
                              [Option(f"wa_job_slot:{case.id}:{i}", _when(h, lang)[:20]) for i, h in enumerate(hints[:2])])
        return

    if kind == "confirm":
        if st != "awaiting_technician":
            await out.text(contact, case.id, _t(m, "Danke! Es gibt gerade nichts zu bestätigen.", "Thanks! Nothing to confirm right now."))
            return
        tech_id = ((case.data or {}).get("technician") or {}).get("tech_id")
        try:
            result = services.technician_confirm(case.id, tech_id)
        except Exception as e:
            raise HTTPException(409, str(getattr(e, "message", e)))
        await notify.notify_tenant(case.id, "technician_confirmed",
                                   {"technician_name": result["technician"]["name"], "tech_id": tech_id,
                                    "slot": result["slot"]})
        await _booked_message(m, case.id, contact)
        return

    if kind == "done":
        docs = [_doc(p, "photo", mime, name) for p, mime, name in photos[:1]] + \
               [_doc(p, "invoice", "application/pdf", name) for p, _mime, name in pdfs[:1]]
        if st == "completed" and pdfs:
            await apply_event(m, _ev(case, pid, "invoiced", {}, [d for d in docs if d["kind"] == "invoice"]), via="WhatsApp")
        elif st == "scheduled":
            await apply_event(m, _ev(case, pid, "completed", {"notes": (text or "").strip()}, docs), via="WhatsApp")
        elif st == "awaiting_technician":
            await out.text(contact, case.id, _t(m, "Bitte bestätigen Sie zuerst den Termin.", "Please confirm the visit first."))
            return
        else:
            await out.text(contact, case.id, _t(m, "Danke! Der Auftrag ist noch nicht gebucht.", "Thanks! The job isn't booked yet."))
            return
        fresh = services.get_case(case.id)
        inv = (fresh.data or {}).get("invoice") or {}
        check = (fresh.data or {}).get("price_check") or {}
        if inv:
            ok = check.get("result") in ("ok", "pass", "within", None)
            amount = inv.get("gross_eur")
            await out.text(contact, case.id, _t(m,
                f"🧾 Rechnung erhalten{f': €{amount:.2f}' if isinstance(amount, (int, float)) else ''} · "
                + ("im Kostenrahmen ✓. Danke für den schnellen Einsatz!" if ok else "liegt über dem Rahmen, die Hausverwaltung prüft sie."),
                f"🧾 Invoice received{f': €{amount:.2f}' if isinstance(amount, (int, float)) else ''} · "
                + ("within budget ✓. Thanks for the quick job!" if ok else "it's above budget, the property manager will check it.")))
        else:
            await out.text(contact, case.id, _t(m, "✅ Danke, als erledigt gespeichert! Bitte schicken Sie noch die Rechnung als PDF.",
                                                "✅ Thanks, marked as done! Please send the invoice as a PDF."))
        return

    if kind == "question":
        q = (intent.get("reason") or text or "").strip()
        await apply_event(m, _ev(case, pid, "needs_info", {"question": q}), via="WhatsApp")
        await out.text(contact, case.id, _t(m, "Gute Frage, ich kläre das und melde mich.", "Good question, I'll find out and get back to you."))
        return

    if kind == "photo":
        for p, mime, name in photos:
            services.attach_document(case.id, "photo", Path(p).name, mime, p)
        await out.text(contact, case.id, _t(m, "📷 Foto gespeichert, danke!", "📷 Photo saved, thanks!"))
        return

    # unclear: re-prompt with what fits the status
    if st == "requested":
        hints = ((case.data or {}).get("partner_order") or {}).get("slot_hints") or transport.slot_hints()
        await out.buttons(contact, case.id, _t(m, "Übernehmen Sie den Auftrag? Tippen Sie einen Termin oder schreiben Sie z. B. „Ja, morgen 8–10“.",
                                               "Will you take the job? Tap a time or write e.g. \"Yes, tomorrow 8-10\"."),
                          [*[Option(f"wa_job_slot:{case.id}:{i}", _when(h, lang)[:20]) for i, h in enumerate(hints[:2])],
                           Option(f"wa_job_decline:{case.id}", _t(m, "Ablehnen", "Decline"))])
    elif st == "awaiting_technician":
        await out.buttons(contact, case.id, _t(m, "Bestätigen Sie den Termin?", "Confirm the visit?"),
                          [Option(f"wa_job_confirm:{case.id}", _t(m, "Bestätigen", "Confirm"))])
    elif st == "scheduled":
        await out.text(contact, case.id, _t(m, "Nach dem Einsatz einfach „erledigt“ schreiben und die Rechnung als PDF schicken.",
                                            "After the visit just write \"done\" and send the invoice as a PDF."))
    else:
        await out.text(contact, case.id, _t(m, "Danke! Ich habe das an die Hausverwaltung weitergegeben.",
                                            "Thanks! I've passed that on to the property manager."))
