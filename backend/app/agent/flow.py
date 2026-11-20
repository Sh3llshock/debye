"""Deterministic tenant flow steps.

Used by the router for button taps (interfaces §3.6), by notify_tenant, by
agent tools, and as the scripted fallback when Claude is slow or down. Nothing
here calls the LLM, so the critical taps are instant and unbreakable.
"""
from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

from app.channels.base import Option

from . import _backend as be
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


def attach_photos(conv: st.Conversation, case_id: str) -> None:
    for path in conv.photos:
        try:
            mime = mimetypes.guess_type(path)[0] or "image/jpeg"
            be.attach_document(case_id, "photo", Path(path).name, mime, path, None)
        except Exception:
            log.exception("attach photo failed")
    conv.photos.clear()


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
        attach_photos(conv, cid)
        return {"case_id": cid, "duplicate": True}
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
    attach_photos(conv, cid)
    return {"case_id": cid, "duplicate": False}


async def send_duplicate_notice(contact, case_id: str) -> None:
    name = first_name(contact)
    await out.text(
        contact,
        case_id,
        f"Danke{', ' + name if name else ''}! Die Heizung im Haus ist schon gemeldet und ein Techniker ist "
        "informiert. Ich halte dich auf dem Laufenden. 🔧",
    )


async def ask_cold(contact, case_id: str, prefix: str = "") -> None:
    st.conversation(be.attr(contact, "id")).step = st.TRIAGE
    await out.buttons(
        contact,
        case_id,
        (prefix + " " if prefix else "") + "Sind alle Heizkörper kalt oder nur einer?",
        [Option(f"cold_all:{case_id}", "Überall kalt"), Option(f"cold_some:{case_id}", "Nur ein Raum")],
    )


async def on_cold(contact, case_id: str, all_cold: bool) -> None:
    cs = st.case_state(case_id)
    cs.triage_answer = "all" if all_cold else "some"
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
    st.conversation(be.attr(contact, "id")).step = st.CONSENT
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
    be.confirm_slot(case_id, n)  # services.confirm_slot is 1-based
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


# ---------------------------------------------------------------- scripted fallback (Claude down / slow)
async def scripted_fallback(contact, conv: st.Conversation) -> None:
    cid = conv.case_id
    if conv.step == st.NEW or not cid:
        said = " ".join(conv.tenant_texts[-3:]).strip() or "Heizung ausgefallen"
        res = await ensure_case(contact, summary="Heizung kalt", symptoms=said[:500])
        if res["duplicate"]:
            await send_duplicate_notice(contact, res["case_id"])
        else:
            await ask_cold(contact, res["case_id"], prefix="Danke, ich habe das aufgenommen.")
    elif conv.step == st.TRIAGE:
        await ask_cold(contact, cid)
    elif conv.step == st.CONSENT:
        await request_consent(contact, cid)
    elif conv.step == st.SCHEDULING and st.case_state(cid).slots:
        await send_slots(cid, st.case_state(cid).slots)
    elif conv.step == st.CONFIRM_FIXED:
        await ask_fixed(cid)
    else:
        await out.text(contact, cid, "Danke! Ich bin dran und melde mich, sobald es Neuigkeiten gibt.")
