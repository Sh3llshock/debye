"""Deterministic tenant flow steps.

Used by the router for button taps (interfaces §3.6), by notify_tenant, by
agent tools, and as the scripted fallback when Claude is slow or down. Nothing
here calls the LLM, so the critical taps are instant and unbreakable.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from pathlib import Path
from app.channels.base import Option

from . import _backend as be
from . import error_codes
from . import outbound as out
from . import state as st

log = logging.getLogger("debye.flow")

DEFAULT_PARTNER_NAME = "der Heizungsbetrieb"


# ---------------------------------------------------------------- helpers
def unit_context_for(contact) -> dict:
    unit_id = be.attr(contact, "unit_id")
    return be.get_unit_context(unit_id) if unit_id else {}


def heating_asset_id(ctx: dict) -> str | None:
    assets = ctx.get("assets") or (ctx.get("property") or {}).get("assets") or []
    for a in assets:
        if be.attr(a, "type") in ("gas_boiler", "heat_pump", "boiler", "district_heating"):
            return be.attr(a, "id") or be.attr(a, "asset_id")
    return be.attr(assets[0], "id") if assets else None


def case_id_of(case) -> str | None:
    return be.attr(case, "id") or be.attr(case, "case_id")


def first_name(contact) -> str:
    name = be.attr(contact, "name") or ""
    return name.split(" ")[0] if name else ""


def tenant_contacts(case_id: str, reporter_only: bool = False) -> list:
    contacts = [c for c in be.get_case_contacts(case_id) if be.attr(c, "phone_e164")]
    if reporter_only:
        rid = st.case_state(case_id).reporter_contact_id
        rep = [c for c in contacts if rid and be.attr(c, "id") == rid]
        rep = rep or [c for c in contacts if be.attr(c, "relation") == "reporter"]
        return rep[:1] or contacts[:1]  # reporter is linked first
    return contacts


def partner_label(case_id: str) -> str:
    return st.case_state(case_id).partner_name or DEFAULT_PARTNER_NAME


def tenant_input(contact, label: str) -> None:
    """Counts a resident input (voice note, photo, tap) for the zero-forms counter."""
    conv = st.conversation(be.attr(contact, "id"))
    if conv.case_id:
        be.add_tenant_input(conv.case_id, label)
    else:
        conv.pending_inputs.append(label)


def _flush_inputs(conv: st.Conversation) -> None:
    for label in conv.pending_inputs:
        be.add_tenant_input(conv.case_id, label)
    conv.pending_inputs.clear()


# ---------------------------------------------------------------- case opening / triage
async def ensure_case(
    contact,
    *,
    summary: str,
    symptoms: str,
    error_code: str | None = None,
    priority: str = "urgent",
    type_: str = "repair.heating",
) -> dict:
    """Opens a case or links the contact to the open one for the same central asset.

    Returns {"case_id", "duplicate": bool}.
    """
    conv = st.conversation(be.attr(contact, "id"))
    if conv.case_id:
        return {"case_id": conv.case_id, "duplicate": False, "already_open": True}
    ctx = unit_context_for(contact)
    asset_id = heating_asset_id(ctx)
    existing = None
    if asset_id:
        try:
            existing = be.find_open_case_for_asset(asset_id)
        except Exception:
            log.exception("find_open_case_for_asset failed")
    if existing is not None:
        cid = case_id_of(existing)
        be.link_contact_to_case(cid, be.attr(contact, "id"), "affected")
        conv.case_id, conv.step = cid, st.DISPATCHED
        _flush_inputs(conv)
        return {"case_id": cid, "duplicate": True}
    from .priority import enforce_priority

    model_priority = priority
    priority, raised = enforce_priority(priority, type_, summary, symptoms, " ".join(conv.tenant_texts[-3:]))
    if raised:
        log.info("priority %s -> %s (%s)", model_priority, priority, raised)
    case = be.open_case(
        reporter_contact_id=be.attr(contact, "id"),
        type=type_,
        priority=priority,
        summary=summary,
        symptoms=symptoms,
        error_code=error_code,
        asset_id=asset_id,
    )
    cid = case_id_of(case)
    st.case_state(cid).reporter_contact_id = be.attr(contact, "id")
    conv.case_id, conv.step = cid, st.TRIAGE
    _flush_inputs(conv)
    return {"case_id": cid, "duplicate": False}


async def send_duplicate_notice(contact, case_id: str) -> None:
    name = first_name(contact)
    await out.text(
        contact,
        case_id,
        f"Danke{', ' + name if name else ''}! Die Heizung im Haus ist schon gemeldet und ein Techniker ist "
        "informiert. Ich halte dich auf dem Laufenden. 🔧",
    )


def _asked_recently(conv: st.Conversation, step: str, seconds: float = 20) -> bool:
    t = conv.asked_at.get(step)
    return t is not None and time.monotonic() - t < seconds


async def ask_cold(contact, case_id: str, prefix: str = "") -> None:
    conv = st.conversation(be.attr(contact, "id"))
    conv.step = st.TRIAGE
    conv.asked_at[st.TRIAGE] = time.monotonic()
    await out.buttons(
        contact,
        case_id,
        (prefix + " " if prefix else "") + "Sind alle Heizkörper kalt oder nur einer?",
        [Option(f"cold_all:{case_id}", "Überall kalt"), Option(f"cold_some:{case_id}", "Nur ein Raum")],
    )


async def on_cold(contact, case_id: str, all_cold: bool) -> None:
    cs = st.case_state(case_id)
    cs.triage_answer = "all" if all_cold else "some"
    be.add_tenant_input(case_id, "tap: Überall kalt" if all_cold else "tap: Nur ein Raum")
    be.record_event(
        case_id,
        "tenant",
        "triage.answer",
        "Alle Heizkörper kalt" if all_cold else "Nur ein Raum kalt",
        {"all_radiators_cold": all_cold},
    )
    try:
        ranking = be.rank_partners(case_id)
    except Exception:
        log.exception("rank_partners failed")
        ranking = []
    if ranking:
        top = ranking[0]
        cs.partner_id, cs.partner_name = be.attr(top, "partner_id"), be.attr(top, "name")
    await request_consent(contact, case_id)


async def request_consent(contact, case_id: str) -> None:
    cs = st.case_state(case_id)
    conv = st.conversation(be.attr(contact, "id"))
    conv.step = st.CONSENT
    conv.asked_at[st.CONSENT] = time.monotonic()
    who = cs.partner_name or "dem Heizungsbetrieb"
    await out.buttons(
        contact,
        case_id,
        f"Ich würde {who} beauftragen. Darf ich dafür deinen Namen, deine Telefonnummer, Adresse und Etage "
        "sowie die Fotos weitergeben?",
        [Option(f"consent_yes:{case_id}", "Ja, gerne"), Option(f"consent_no:{case_id}", "Nein")],
    )


async def on_consent(contact, case_id: str, yes: bool) -> None:
    conv = st.conversation(be.attr(contact, "id"))
    cs = st.case_state(case_id)
    if not yes:
        be.record_event(case_id, "tenant", "consent.declined", "Mieter:in hat die Weitergabe abgelehnt")
        conv.step = st.WAITING_APPROVAL
        await out.text(
            contact, case_id, "Alles klar, ich gebe nichts weiter. Die Hausverwaltung meldet sich bei dir."
        )
        return
    if not cs.partner_id:
        try:
            ranking = be.rank_partners(case_id)
            if ranking:
                cs.partner_id, cs.partner_name = be.attr(ranking[0], "partner_id"), be.attr(ranking[0], "name")
        except Exception:
            log.exception("rank_partners failed")
    if not cs.partner_id:
        await out.text(contact, case_id, "Danke! Ich suche gerade einen passenden Betrieb und melde mich gleich.")
        return
    be.add_tenant_input(case_id, "tap: consent")
    be.record_consent(
        be.attr(contact, "id"), cs.partner_id, case_id, cs.consent_fields, cs.consent_purpose, "whatsapp"
    )
    try:
        be.dispatch_job(case_id, cs.partner_id)
    except Exception as exc:
        code = be.rule_violation_code(exc)
        if code == "approval_required":
            conv.step = st.WAITING_APPROVAL
            await out.text(
                contact,
                case_id,
                "Danke! Die Hausverwaltung muss den Auftrag kurz freigeben, dann geht er sofort an "
                f"{partner_label(case_id)}.",
            )
            return
        log.exception("dispatch_job failed")
        await out.text(contact, case_id, "Danke! Ich kümmere mich darum und melde mich gleich bei dir.")
        return
    conv.step = st.DISPATCHED
    await out.text(
        contact,
        case_id,
        f"Danke! {partner_label(case_id)} hat den Auftrag. Sobald Terminvorschläge da sind, kannst du hier "
        "einen auswählen.",
    )


# ---------------------------------------------------------------- scheduling
def slot_label(slot: dict) -> str:
    return slot.get("label") or f"{slot.get('start', '')[:16]}"


async def send_slots(case_id: str, slots: list[dict]) -> None:
    cs = st.case_state(case_id)
    cs.slots = list(slots)
    rows = [Option(f"slot_{i + 1}:{case_id}", slot_label(s)) for i, s in enumerate(slots[:9])]
    rows.append(Option(f"slot_none:{case_id}", "Passt nicht"))
    for c in tenant_contacts(case_id, reporter_only=True):
        st.conversation(be.attr(c, "id")).step = st.SCHEDULING
        await out.list_(
            c,
            case_id,
            f"{partner_label(case_id)} kann zu diesen Zeiten vorbeikommen. Wann passt es dir?",
            "Termin wählen",
            rows,
            section_title=(cs.partner_name or "Termine")[:24],
        )


async def on_slot(contact, case_id: str, n: int) -> None:
    """n is 1-based as in the list row id slot_<n>."""
    cs = st.case_state(case_id)
    be.confirm_slot(case_id, n)  # 1-based (interfaces §3.3); services counts the tap
    label = slot_label(cs.slots[n - 1]) if 0 < n <= len(cs.slots) else f"Termin {n}"
    st.conversation(be.attr(contact, "id")).step = st.SCHEDULED
    await out.text(
        contact, case_id, f"Passt! {partner_label(case_id)} kommt {label}. Ich erinnere dich vorher. 👍"
    )
    me = be.attr(contact, "id")
    for other in tenant_contacts(case_id):
        if be.attr(other, "id") != me:
            await out.text(other, case_id, f"Update: Der Techniker kommt {label} für die Heizung im Haus.")


async def on_slot_none(contact, case_id: str) -> None:
    be.record_event(case_id, "tenant", "slot.rejected", "Keiner der Termine passt")
    await out.text(contact, case_id, f"Kein Problem, ich frage {partner_label(case_id)} nach anderen Terminen.")


# ---------------------------------------------------------------- close the loop
async def ask_fixed(case_id: str, notes: str | None = None) -> None:
    for c in tenant_contacts(case_id, reporter_only=True):
        st.conversation(be.attr(c, "id")).step = st.CONFIRM_FIXED
        await out.buttons(
            c,
            case_id,
            f"{partner_label(case_id)} hat die Reparatur abgeschlossen. Ist es bei dir wieder warm?",
            [Option(f"fixed_yes:{case_id}", "Ja, alles warm"), Option(f"fixed_no:{case_id}", "Nein, noch kalt")],
        )


async def on_fixed(contact, case_id: str, fixed: bool) -> None:
    be.tenant_confirms_fixed(case_id, fixed)
    if fixed:
        await out.text(
            contact,
            case_id,
            "Super, dann schließe ich den Fall. 🎉 Die Rechnung geht direkt an die Hausverwaltung, für dich "
            "entstehen keine Kosten.",
        )
        me = be.attr(contact, "id")
        for other in tenant_contacts(case_id):
            if be.attr(other, "id") != me:
                await out.text(other, case_id, "Die Heizung im Haus ist repariert. Sag Bescheid, falls es noch kalt ist.")
        for conv in st.conversations_for_case(case_id):
            st.reset_conversation(conv.contact_id)
    else:
        st.conversation(be.attr(contact, "id")).step = st.DISPATCHED
        await out.text(contact, case_id, f"Oh nein! Ich gebe das sofort an {partner_label(case_id)} weiter.")


# ---------------------------------------------------------------- voice reply (optional)
async def maybe_voice_reply(contact) -> None:
    """Once per conversation, answer the resident's first voice note with a short voice note.
    No-op without ELEVENLABS_API_KEY or if TTS fails."""
    conv = st.conversation(be.attr(contact, "id"))
    if conv.voice_replied:
        return
    from app import media

    name = first_name(contact)
    line = (f"Hi {name}, hier ist Debye. " if name else "Hi, hier ist Debye. ") + (
        "Ich hab deine Sprachnachricht bekommen und kümmer mich drum. "
        "Tipp einfach unten auf eine Antwort, dann geht's sofort weiter."
    )
    path = await media.speak(line)
    if not path:
        return
    conv.voice_replied = True
    await out.media(contact, conv.case_id, "audio", path)


# ---------------------------------------------------------------- error codes without the LLM
_CODE_RE = re.compile(r"\bF\s?\.?\s?(\d{2})\b", re.IGNORECASE)
# Photos we know: the demo boiler display (data/demo/boiler_display_F28.jpg) shows F.28.
_KNOWN_PHOTOS = {"boiler_display_F28.jpg": "F.28"}
_known_hashes: dict[str, str] | None = None


def _photo_hashes() -> dict[str, str]:
    global _known_hashes
    if _known_hashes is None:
        _known_hashes = {}
        demo_dir = Path(__file__).resolve().parents[3] / "data" / "demo"
        for name, code in _KNOWN_PHOTOS.items():
            try:
                _known_hashes[hashlib.sha256((demo_dir / name).read_bytes()).hexdigest()] = code
            except OSError:
                pass
    return _known_hashes


def detect_error_code(texts: list[str], image_paths: list[str]) -> tuple[str | None, str]:
    """(code, source): a code the resident typed/said ("text"), or the code on a photo we can
    recognise exactly ("photo"). No guessing."""
    for p in image_paths:
        try:
            code = _photo_hashes().get(hashlib.sha256(Path(p).read_bytes()).hexdigest())
        except OSError:
            code = None
        if code:
            return code, "photo"
    for t in reversed(texts):
        m = _CODE_RE.search(t or "")
        if m:
            return f"F.{m.group(1)}", "text"
    return None, "text"


def error_code_sentence(code: str, source: str = "photo") -> str:
    return error_codes.resident_sentence(code, source)


# ---------------------------------------------------------------- scripted fallback (Claude down / slow)
async def scripted_fallback(contact, conv: st.Conversation, image_paths: list[str] | None = None) -> None:
    cid = conv.case_id
    code, source = detect_error_code(conv.tenant_texts[-3:], image_paths or [])
    new_code = code if code and code != conv.error_code else None
    if conv.step == st.NEW or not cid:
        said = " ".join(conv.tenant_texts[-3:]).strip() or "Heizung ausgefallen"
        summary = error_codes.case_title(code)
        res = await ensure_case(contact, summary=summary, symptoms=said[:500], error_code=code)
        if res["duplicate"]:
            await send_duplicate_notice(contact, res["case_id"])
        else:
            prefix = "Danke, ich habe das aufgenommen."
            if new_code:
                prefix = f"Danke! {error_code_sentence(new_code, source)} Ich habe einen Fall angelegt."
                conv.error_code = new_code
            await ask_cold(contact, res["case_id"], prefix=prefix)
    elif conv.step == st.TRIAGE:
        if new_code:  # e.g. the photo arrived just after the voice note
            conv.error_code = new_code
            be.set_case_error_code(cid, new_code)
            if st.TRIAGE in conv.asked_at:  # cold question still open: acknowledge only, don't ask again
                await out.text(contact, cid, f"{error_code_sentence(new_code, source)} Ich habe das im Fall notiert.")
            else:
                await ask_cold(contact, cid, prefix=error_code_sentence(new_code, source))
        elif not _asked_recently(conv, st.TRIAGE):
            await ask_cold(contact, cid)
    elif conv.step == st.CONSENT:
        if not _asked_recently(conv, st.CONSENT):
            await request_consent(contact, cid)
    elif conv.step == st.SCHEDULING and st.case_state(cid).slots:
        await send_slots(cid, st.case_state(cid).slots)
    elif conv.step == st.CONFIRM_FIXED:
        await ask_fixed(cid)
    else:
        await out.text(contact, cid, "Danke! Ich bin dran und melde mich, sobald es Neuigkeiten gibt.")
