"""Deterministic tenant flow steps.

Used by the router for button taps (interfaces §3.6), by notify_tenant, by
agent tools, and as the scripted fallback when Claude is slow or down. Nothing
here calls the LLM, so the critical taps are instant and unbreakable.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from pathlib import Path
from app.channels.base import Option

from . import _backend as be
from . import error_codes
from . import outbound as out
from . import state as st

log = logging.getLogger("debye.flow")

DEFAULT_PARTNER_NAME = "the heating company"


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
    trade: str | None = None,
    diagnosis: dict | None = None,
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
        trade=trade,
        diagnosis=diagnosis,
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
        f"Thanks{', ' + name if name else ''}. The heating for the whole building is already reported and a "
        "technician is on it. I'll keep you posted.",
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
        (prefix + " " if prefix else "") + "Are all your radiators cold, or just one?",
        [Option(f"cold_all:{case_id}", "All cold"), Option(f"cold_some:{case_id}", "Just one room")],
    )


async def on_cold(contact, case_id: str, all_cold: bool) -> None:
    cs = st.case_state(case_id)
    cs.triage_answer = "all" if all_cold else "some"
    be.add_tenant_input(case_id, "tap: all cold" if all_cold else "tap: just one room")
    be.record_event(
        case_id,
        "tenant",
        "triage.answer",
        "All radiators cold" if all_cold else "Only one room cold",
        {"all_radiators_cold": all_cold},
    )
    if not all_cold:  # one room: the radiator itself, not the boiler (KB: self-help → caretaker)
        await one_room_tip(contact, case_id)
        return
    try:
        ranking = be.rank_partners(case_id)
    except Exception:
        log.exception("rank_partners failed")
        ranking = []
    if ranking:
        top = ranking[0]
        cs.partner_id, cs.partner_name = be.attr(top, "partner_id"), be.attr(top, "name")
    await request_consent(contact, case_id)


# How each consent field is named in the question (en, de).
CONSENT_FIELD_TEXT = {
    "name": ("name", "deinen Namen"),
    "phone": ("phone number", "deine Telefonnummer"),
    "email": ("email address", "deine E-Mail-Adresse"),
    "address": ("address", "deine Adresse"),
    "unit_floor": ("floor", "dein Stockwerk"),
    "photos": ("the photos", "die Fotos"),
}
DEFAULT_CONSENT_FIELDS = ["name", "phone", "address", "photos"]  # company not chosen yet (staff pick)


def consent_scope(case_id: str, conv) -> tuple[list[str], str]:
    """(fields, purpose) the tenant is asked to agree to, which is also what the consent record stores:
    the chosen partner's manifest fields that need consent (photos only if the tenant sent any), and a
    purpose taken from the case itself."""
    from app.rules import norm_field

    cs = st.case_state(case_id)
    manifest = None
    if cs.partner_id:
        try:
            manifest = be._call("get_partner_manifest", cs.partner_id)
        except Exception:
            log.exception("get_partner_manifest failed")
    raw = list(manifest.consent_fields) if manifest is not None else DEFAULT_CONSENT_FIELDS
    fields: list[str] = []
    for f in map(norm_field, raw):
        if (f != "photos" or conv.photos) and f not in fields:
            fields.append(f)
    order = list(CONSENT_FIELD_TEXT)
    fields.sort(key=lambda f: order.index(f) if f in order else len(order))
    case = None
    try:
        case = be._call("get_case", case_id)
    except Exception:
        log.exception("get_case failed")
    trade = (be.attr(case, "data") or {}).get("trade") if case is not None else None
    what = (be.attr(case, "title") or be.attr(case, "type")) if case is not None else None
    purpose = "On-site repair visit" + (f" ({trade})" if trade else "") + (f": {what}" if what else "")
    return fields, purpose


def consent_question(who: str, fields: list[str], lang: str) -> str:
    """The consent question naming exactly the fields that will be recorded."""
    de = lang == "de"
    names = [CONSENT_FIELD_TEXT.get(f, (f.replace("_", " "),) * 2)[1 if de else 0] for f in fields]
    if not de and names and not names[0].startswith("the "):
        names[0] = "your " + names[0]
    if not names:
        names = ["deine Kontaktdaten" if de else "your contact details"]
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + (" und " if de else " and ") + names[-1]
    if de:
        return f"Ich würde {who} schicken. Ist es okay, wenn ich {joined} weitergebe?"
    return f"I'd like to send {who} over. Is it okay if I share {joined} with them?"


async def one_room_tip(contact, case_id: str) -> None:
    conv = st.conversation(be.attr(contact, "id"))
    conv.step = st.SELF_HELP
    de = conv.lang == "de"
    await out.buttons(
        contact, case_id,
        "Wenn nur ein Raum kalt ist, liegt es meist am Heizkörper selbst, nicht an der Heizung. Dreh das "
        "Thermostat an dem Heizkörper ganz auf (Stufe 5) und warte 15 Minuten. Bleibt er oben kalt oder "
        "gluckert er, ist Luft drin; dann muss er entlüftet werden. Ist er jetzt warm?"
        if de else
        "When only one room is cold, it's usually that radiator, not the heating. Turn its thermostat valve "
        "fully open (to 5) and give it 15 minutes. If it stays cold at the top or gurgles, there's air in it "
        "and it needs bleeding. Is it warm now?",
        [Option(f"oneroom_ok:{case_id}", "Ja, warm" if de else "Yes, warm"),
         Option(f"oneroom_no:{case_id}", "Noch kalt" if de else "Still cold")],
    )


async def on_one_room(contact, case_id: str, warm: bool) -> None:
    """After the radiator tip: warm → close as self-help; still cold → the caretaker (bleeding, valve),
    no installer."""
    conv = st.conversation(be.attr(contact, "id"))
    de = conv.lang == "de"
    be.add_tenant_input(case_id, "tap: radiator warm" if warm else "tap: radiator still cold")
    if warm:
        conv.step = st.CLOSED
        try:
            be.close_self_help(case_id, "One room cold: opening the thermostat valve fixed it")
        except Exception:
            log.exception("close_self_help failed")
        await out.text(contact, case_id, "Super, dann ist alles gut. Melde dich, falls er wieder kalt wird."
                       if de else "Great, then it's sorted. Message me if it goes cold again.")
        return
    conv.step = st.WAITING_APPROVAL
    try:
        be.notify_caretaker(case_id, "One radiator stays cold: bleed it / check the thermostat valve")
        told = True
    except Exception:
        log.exception("notify_caretaker failed")
        be.record_event(case_id, "system", "staff.attention", "One radiator cold; caretaker could not be notified", {})
        told = False
    await out.text(
        contact, case_id,
        ("Dann schaut sich unser Hausmeister den Heizkörper an (entlüften, Ventil prüfen). Ich habe ihm "
         "Bescheid gegeben." if told else
         "Dann schaut sich die Hausverwaltung den Heizkörper an; ich habe es weitergegeben.")
        if de else
        ("Then our caretaker will look at the radiator (bleeding it, checking the valve). I've let them know." if told else
         "Then your property management will have the radiator looked at; I've passed it on."))


async def request_consent(contact, case_id: str) -> None:
    cs = st.case_state(case_id)
    conv = st.conversation(be.attr(contact, "id"))
    conv.step = st.CONSENT
    conv.asked_at[st.CONSENT] = time.monotonic()
    who = ("einen Techniker" if conv.lang == "de" else "a technician") if cs.trade_unknown \
        else cs.partner_name or ("eine Heizungsfirma" if conv.lang == "de" else "a heating company")
    cs.consent_fields, cs.consent_purpose = consent_scope(case_id, conv)
    await out.buttons(
        contact,
        case_id,
        consent_question(who, cs.consent_fields, conv.lang),
        [Option(f"consent_yes:{case_id}", "Ja, gerne" if conv.lang == "de" else "Yes, go ahead"),
         Option(f"consent_no:{case_id}", "Nein" if conv.lang == "de" else "No")],
    )


async def on_consent(contact, case_id: str, yes: bool) -> None:
    conv = st.conversation(be.attr(contact, "id"))
    cs = st.case_state(case_id)
    if not yes:
        be.record_event(case_id, "tenant", "consent.declined", "Tenant declined sharing their details")
        conv.step = st.WAITING_APPROVAL
        await out.text(
            contact, case_id, "Understood, I won't share anything. Someone from the property management will get in touch."
        )
        return
    if cs.trade_unknown and not cs.partner_id:
        # which company depends on the cause: the property manager picks it when approving
        be.add_tenant_input(case_id, "tap: consent")
        be.record_event(case_id, "tenant", "consent.given_pending_partner",
                        "Tenant agreed to share their details with the technician staff pick", {})
        conv.step = st.WAITING_APPROVAL
        await out.text(contact, case_id, "Danke. Deine Hausverwaltung wählt die passende Firma aus und bestätigt "
                       "den Termin; ich melde mich dann." if conv.lang == "de" else "Thanks. Your property manager "
                       "picks the right company and confirms the visit; I'll update you then.")
        return
    if not cs.partner_id:
        try:
            ranking = be.rank_partners(case_id)
            if ranking:
                cs.partner_id, cs.partner_name = be.attr(ranking[0], "partner_id"), be.attr(ranking[0], "name")
        except Exception:
            log.exception("rank_partners failed")
    if not cs.partner_id:
        be.record_event(case_id, "system", "staff.attention", "No matching company found: staff pick one", {})
        await out.text(contact, case_id, "Thanks. I've passed this to your property management; they'll pick the "
                       "company and I'll update you when they do.")
        return
    be.add_tenant_input(case_id, "tap: consent")
    if not cs.consent_fields:  # state lost since the question (e.g. restart): rebuild it the same way
        cs.consent_fields, cs.consent_purpose = consent_scope(case_id, conv)
    be.record_consent(
        be.attr(contact, "id"), cs.partner_id, case_id, cs.consent_fields, cs.consent_purpose, conv.channel
    )
    try:
        be.dispatch_job(case_id, cs.partner_id)
    except Exception as exc:
        code = be.rule_violation_code(exc)
        if code == "approval_required":
            conv.step = st.WAITING_APPROVAL
            await tell_approval_pending(case_id, [contact])
            return
        log.exception("dispatch_job failed")
        be.record_event(case_id, "system", "staff.attention", "Sending the job failed: staff follow up", {})
        await out.text(contact, case_id, "Thanks. I've flagged this for your property management; they'll pick it up and get in touch.")
        return
    conv.step = st.DISPATCHED
    await out.text(
        contact,
        case_id,
        f"Thanks. {partner_label(case_id)} has the job. As soon as they suggest times, you can pick one here.",
    )


APPROVAL_PENDING_TEXT = "Thanks. Your property manager is confirming the repair, I'll update you shortly."


async def tell_approval_pending(case_id: str, contacts: list | None = None) -> None:
    """Once per case: consent is recorded, the property manager still has to approve."""
    cs = st.case_state(case_id)
    if cs.approval_notice_sent:
        return
    cs.approval_notice_sent = True
    for c in contacts if contacts is not None else tenant_contacts(case_id, reporter_only=True):
        st.conversation(be.attr(c, "id")).step = st.WAITING_APPROVAL
        await out.text(c, case_id, APPROVAL_PENDING_TEXT)


# ---------------------------------------------------------------- scheduling
def slot_label(slot: dict) -> str:
    return slot.get("label") or f"{slot.get('start', '')[:16]}"


_REL_RE = re.compile(r"^(today|tomorrow|heute|morgen)\s+(\d{1,2}(?::\d\d)?)\s*[–-]\s*(\d{1,2}(?::\d\d)?)$", re.I)
_ABS_RE = re.compile(r"^(.+?),?\s+(\d{1,2}(?::\d\d)?)\s*[–-]\s*(\d{1,2}(?::\d\d)?)$")
_REL_EN = {"today": "today", "tomorrow": "tomorrow", "heute": "today", "morgen": "tomorrow"}


def natural_when(slot_or_label) -> str:
    """'Tomorrow 8–10' → 'tomorrow between 8 and 10'; 'Sat 21 Nov, 8–10' → 'on Sat 21 Nov between 8 and 10'.
    Use as: f'… will come {natural_when(slot)}'."""
    label = slot_or_label if isinstance(slot_or_label, str) else slot_label(slot_or_label or {})
    label = (label or "").strip()
    m = _REL_RE.match(label)
    if m:
        return f"{_REL_EN[m.group(1).lower()]} between {m.group(2)} and {m.group(3)}"
    m = _ABS_RE.match(label)
    if m:
        return f"on {m.group(1).strip()} between {m.group(2)} and {m.group(3)}"
    return f"on {label}" if label else "at the agreed time"


async def send_slots(case_id: str, slots: list[dict], technician_name: str | None = None) -> None:
    cs = st.case_state(case_id)
    cs.slots = list(slots)
    if technician_name:
        cs.technician_name = technician_name
    rows = [Option(f"slot_{i + 1}:{case_id}", slot_label(s)) for i, s in enumerate(slots[:9])]
    rows.append(Option(f"slot_none:{case_id}", "None of these work"))
    who = f"{partner_label(case_id)} can send {cs.technician_name}" if cs.technician_name else \
        f"{partner_label(case_id)} can come"
    for c in tenant_contacts(case_id, reporter_only=True):
        st.conversation(be.attr(c, "id")).step = st.SCHEDULING
        await out.list_(
            c,
            case_id,
            f"{who} at one of these times. Which one works for you?",
            "Pick a time",
            rows,
            section_title=(cs.partner_name or "Times")[:24],
        )


async def on_slot(contact, case_id: str, n: int) -> None:
    """n is 1-based as in the list row id slot_<n>."""
    cs = st.case_state(case_id)
    be.confirm_slot(case_id, n)  # 1-based (interfaces §3.3); services counts the tap
    label = slot_label(cs.slots[n - 1]) if 0 < n <= len(cs.slots) else f"option {n}"
    cs.chosen_slot = cs.slots[n - 1] if 0 < n <= len(cs.slots) else None
    st.conversation(be.attr(contact, "id")).step = st.SCHEDULED
    if cs.technician_name:  # dispatcher flow: the technician still confirms (notify "technician_confirmed")
        await out.text(
            contact, case_id, f"Thanks. I've asked {cs.technician_name} to confirm and will let you know shortly."
        )
        return
    reminded = schedule_reminder(case_id, cs.chosen_slot, [be.attr(contact, "id")])
    await out.text(
        contact, case_id,
        f"{partner_label(case_id)} will come {natural_when(label)}."
        + (" I'll remind you the evening before." if reminded else "")
    )
    await _tell_neighbours(contact, case_id,
                           f"Update: a technician is coming {natural_when(label)} for the building's heating.")


async def _tell_neighbours(contact, case_id: str, text: str) -> None:
    me = be.attr(contact, "id") if contact is not None else None
    for other in tenant_contacts(case_id):
        if be.attr(other, "id") != me:
            await out.text(other, case_id, text)


async def on_technician_confirmed(case_id: str, technician_name: str | None, slot: dict | None) -> None:
    """notify 'technician_confirmed': the technician accepted the slot the tenant picked."""
    cs = st.case_state(case_id)
    tech = technician_name or cs.technician_name or "The technician"
    cs.technician_name = tech
    when = natural_when(slot or cs.chosen_slot or {})
    reporters = tenant_contacts(case_id, reporter_only=True)
    reminded = schedule_reminder(case_id, slot or cs.chosen_slot, [be.attr(c, "id") for c in reporters],
                                 who=f"{tech} from {partner_label(case_id)}")
    for c in reporters:
        name = first_name(c)
        st.conversation(be.attr(c, "id")).step = st.SCHEDULED
        await out.text(
            c,
            case_id,
            f"{name + ', ' if name else ''}{tech} from {partner_label(case_id)} will come to your apartment "
            f"{when}." + (" I'll remind you the evening before." if reminded else ""),
        )
    await _tell_neighbours(reporters[0] if reporters else None, case_id,
                           f"Update: {tech} from {partner_label(case_id)} is coming {when} for the "
                           "building's heating.")


async def on_slot_none(contact, case_id: str) -> None:
    be.record_event(case_id, "tenant", "slot.rejected", "None of the proposed times work for the tenant")
    await out.text(contact, case_id, f"Understood. I'll ask {partner_label(case_id)} for other times.")


# ---------------------------------------------------------------- close the loop
async def ask_fixed(case_id: str, notes: str | None = None) -> None:
    for c in tenant_contacts(case_id, reporter_only=True):
        st.conversation(be.attr(c, "id")).step = st.CONFIRM_FIXED
        await out.buttons(
            c,
            case_id,
            f"{partner_label(case_id)} has finished the repair. Is it warm again at your place?",
            [Option(f"fixed_yes:{case_id}", "Yes, all warm"), Option(f"fixed_no:{case_id}", "No, still cold")],
        )


async def on_fixed(contact, case_id: str, fixed: bool) -> None:
    be.tenant_confirms_fixed(case_id, fixed)
    if fixed:
        await out.text(
            contact,
            case_id,
            "Good. The invoice goes straight to the property management, so there's nothing for you to pay.",
        )
        me = be.attr(contact, "id")
        for other in tenant_contacts(case_id):
            if be.attr(other, "id") != me:
                await out.text(other, case_id, "The building's heating is working again. Let me know if it's still cold at your place.")
        for conv in st.conversations_for_case(case_id):
            st.reset_conversation(conv.contact_id)
    else:
        st.conversation(be.attr(contact, "id")).step = st.DISPATCHED
        await out.text(contact, case_id, f"Thanks for telling me. I'll let {partner_label(case_id)} know right away.")


HEATING_WORDS = ("heat", "radiator", "boiler", "cold", "warm", "hot water", "heiz", "kalt", "kessel", "therme",
                 "warmwasser")


async def link_if_building_case_open(contact, conv: st.Conversation) -> bool:
    """Safety net after a model turn: a resident who reports a heating problem while the building's
    central-heating case is open gets linked to it (quietly), even if the model forgot open_case."""
    if conv.case_id:
        return False
    said = " ".join(conv.tenant_texts[-3:]).lower()
    if not any(w in said for w in HEATING_WORDS):
        return False
    asset_id = heating_asset_id(unit_context_for(contact))
    if not asset_id:
        return False
    try:
        existing = be.find_open_case_for_asset(asset_id)
    except Exception:
        log.exception("find_open_case_for_asset failed")
        return False
    if existing is None:
        return False
    cid = case_id_of(existing)
    be.link_contact_to_case(cid, be.attr(contact, "id"), "affected")
    conv.case_id, conv.step = cid, st.DISPATCHED
    _flush_inputs(conv)
    log.info("linked %s to open building case %s (safety net)", be.attr(contact, "id"), cid)
    return True


# ---------------------------------------------------------------- voice reply (optional)
async def maybe_voice_reply(contact) -> None:
    """Once per conversation, answer the resident's first voice note with a short voice note.
    No-op without ELEVENLABS_API_KEY or if TTS fails."""
    conv = st.conversation(be.attr(contact, "id"))
    if conv.voice_replied:
        return
    from app import media

    name = first_name(contact)
    line = (f"Hi {name}, it's Debye. " if name else "Hi, it's Debye. ") + (
        "Got your voice message, I'm on it. "
        "Just answer my question below and we'll get things moving."
    )
    path = await media.speak(line)
    if not path:
        return
    conv.voice_replied = True
    await out.media(contact, conv.case_id, "audio", path)


async def diagnosis_fallback(contact, conv: st.Conversation) -> None:
    """Model down during a diagnosis: next question or conclusion by signal matching."""
    from . import diagnosis

    from . import choice

    d = conv.diagnosis
    last = diagnosis.open_question(d)
    if last and conv.pending_options and conv.tenant_texts:
        opt = choice.fast_match(conv.tenant_texts[-1], conv.pending_options)  # model down: map the plain answer
        if opt is not None and opt.id.startswith("diag:"):
            diagnosis.record(conv, last, opt.id.split(":")[2])
    if diagnosis.open_question(d) and _asked_recently(conv, st.DIAGNOSIS, 60):
        return  # question still open; wait for the answer
    action, ident, conf = diagnosis.next_step(conv)
    if action == "ask":
        await diagnosis.ask(contact, conv, ident)
    else:
        await diagnosis.conclude(contact, conv, ident, conf, "Scripted: best match of the answers to the signals.",
                                 force=True)


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
    from . import diagnosis

    if diagnosis.active(conv):
        await diagnosis_fallback(contact, conv)
        return
    cid = conv.case_id
    code, source = detect_error_code(conv.tenant_texts[-3:], image_paths or [])
    new_code = code if code and code != conv.error_code else None
    if conv.step == st.NEW or not cid:
        said = " ".join(conv.tenant_texts[-3:]).strip() or "Heating not working"
        summary = error_codes.case_title(code)
        res = await ensure_case(contact, summary=summary, symptoms=said[:500], error_code=code)
        if res["duplicate"]:
            await send_duplicate_notice(contact, res["case_id"])
        else:
            prefix = ""
            if new_code:
                prefix = error_code_sentence(new_code, source)
                conv.error_code = new_code
            await ask_cold(contact, res["case_id"], prefix=prefix)
    elif conv.step == st.TRIAGE:
        if new_code:  # e.g. the photo arrived just after the voice note
            conv.error_code = new_code
            be.set_case_error_code(cid, new_code)
            if st.TRIAGE in conv.asked_at:  # cold question still open: acknowledge only, don't ask again
                await out.text(contact, cid, f"{error_code_sentence(new_code, source)} Thanks for the photo, that helps the technician.")
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
        await out.text(contact, cid, "Thanks. I'm on it and will let you know as soon as there's news.")


# ---------------------------------------------------------------- visit reminders
# "I'll remind you the evening before" is only said when a reminder is really scheduled here: 18:00 the
# day before the visit, on the (demo-aware) clock app.config.now(). A small loop checks every 30 s, and
# /demo/skip-to-tomorrow checks at once. In memory, like the self-help follow-up.
REMINDER_HOUR = 18
_reminders: dict[str, dict] = {}  # case_id -> {at, start, end, contact_ids, who, sent}
_reminder_task = None


def clear_reminders() -> None:
    _reminders.clear()


def _parse_dt(v):
    from datetime import datetime

    from app.config import TZ

    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=TZ)


def schedule_reminder(case_id: str, slot: dict | None, contact_ids: list[str], who: str | None = None) -> bool:
    """True if a reminder for the evening before this slot is scheduled (so the text may promise it)."""
    from datetime import timedelta

    from app.config import now

    start = _parse_dt((slot or {}).get("start"))
    if start is None or not contact_ids:
        return False
    at = (start - timedelta(days=1)).replace(hour=REMINDER_HOUR, minute=0, second=0, microsecond=0)
    if at <= now():  # the evening before has already passed (visit today or tomorrow morning)
        return False
    _reminders[case_id] = {"at": at, "start": start, "end": _parse_dt((slot or {}).get("end")),
                           "contact_ids": list(dict.fromkeys(contact_ids)), "who": who, "sent": False}
    be.record_event(case_id, "system", "reminder.scheduled", f"Visit reminder scheduled for {at:%a %d %b %H:%M}",
                    {"at": at.isoformat(), "visit": start.isoformat()})
    _ensure_reminder_loop()
    return True


def _ensure_reminder_loop() -> None:
    global _reminder_task
    import asyncio

    if _reminder_task is not None and not _reminder_task.done():
        return
    try:
        _reminder_task = asyncio.get_running_loop().create_task(_reminder_loop())
    except RuntimeError:  # no loop (seed scripts): /demo/skip-to-tomorrow or the next loop start sends it
        _reminder_task = None


async def _reminder_loop() -> None:
    import asyncio

    while any(not r["sent"] for r in _reminders.values()):
        await asyncio.sleep(float(os.getenv("REMINDER_CHECK_SECONDS", "30")))
        try:
            await send_due_reminders()
        except Exception:
            log.exception("reminders failed")


def _hour(d) -> str:
    return f"{d.hour}" if d.minute == 0 else f"{d.hour}:{d.minute:02d}"


async def send_due_reminders() -> int:
    """Sends every reminder whose time has come (demo clock aware). Returns how many were sent."""
    from app.config import now

    sent = 0
    t = now()
    for case_id, r in list(_reminders.items()):
        if r["sent"] or r["at"] > t:
            continue
        r["sent"] = True
        if r["start"] <= t:  # the visit itself is already over: no point reminding
            continue
        span = f"between {_hour(r['start'])} and {_hour(r['end'])}" if r.get("end") else f"at {_hour(r['start'])}"
        day = "tomorrow" if (r["start"].date() - t.date()).days == 1 else f"on {r['start']:%a %d %b}"
        who = r.get("who") or partner_label(case_id)
        for cid in r["contact_ids"]:
            contact = be.get_contact(cid)
            if contact is None:
                continue
            name = first_name(contact)
            await out.text(contact, case_id, f"{'Hi ' + name + ', a' if name else 'A'} quick reminder: {who} "
                           f"is coming {day} {span}. Reply here if that no longer works.")
            sent += 1
        be.record_event(case_id, "system", "reminder.sent", "Visit reminder sent to the tenant", {})
    return sent
