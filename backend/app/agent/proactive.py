"""Detect the moment: centrix reports a boiler error (asset.error_reported) and Debye writes the tenant
FIRST, with the code already known, then continues the normal flow:

  heating off   → the boiler fault is the whole heating: company ranking + consent (no triage question)
  hot water off → the hot-water diagnosis, which starts with the code known
  all working   → noted for the property management, nothing sent to a company
"""
from __future__ import annotations

import logging

from app.channels.base import Option

from . import _backend as be
from . import error_codes, flow
from . import outbound as out
from . import state as st

log = logging.getLogger("debye.proactive")

PROACTIVE = "proactive_check"  # conversation step: waiting for the answer to the proactive question


def _label(code: str) -> str:
    return error_codes.EN.get(code) or "boiler error"


async def on_asset_error(unit_id: str, code: str, asset_id: str | None = None) -> dict:
    """Returns {case_id, messaged, duplicate, contact_id}."""
    ctx = be.get_unit_context(unit_id)
    if not ctx:
        raise ValueError(f"unit {unit_id} not found")
    tenant = ctx.get("tenant")
    asset_id = asset_id or flow.heating_asset_id(ctx)
    summary = f"Boiler reported {code} ({_label(code)})"
    existing = be.find_open_case_for_asset(asset_id) if asset_id else None
    if existing is not None:  # already being handled: note it, don't write the tenant again
        cid = flow.case_id_of(existing)
        be.record_event(cid, "centrix", "asset.error_reported", summary,
                        {"unit_id": unit_id, "asset_id": asset_id, "code": code})
        return {"case_id": cid, "messaged": False, "duplicate": True}
    contact = be.get_contact(be.attr(tenant, "id")) if tenant else None
    if contact is None:
        be.record_event(None, "centrix", "asset.error_reported", summary + " (no tenant to message)",
                        {"unit_id": unit_id, "asset_id": asset_id, "code": code})
        return {"case_id": None, "messaged": False, "duplicate": False}
    conv = st.conversation(be.attr(contact, "id"))
    res = await flow.ensure_case(contact, summary=error_codes.case_title(code),
                                 symptoms=f"{summary}, reported by the boiler via centrix before the tenant wrote",
                                 error_code=code, priority="urgent")
    cid = res["case_id"]
    be.record_event(cid, "centrix", "asset.error_reported", summary,
                    {"unit_id": unit_id, "asset_id": asset_id, "code": code})
    if res.get("already_open"):  # the tenant is already talking to us about it
        conv.error_code = conv.error_code or code
        return {"case_id": cid, "messaged": False, "duplicate": False}
    conv.error_code = code
    conv.step = PROACTIVE
    await ask(contact, cid, code)
    return {"case_id": cid, "messaged": True, "duplicate": False, "contact_id": be.attr(contact, "id")}


async def ask(contact, case_id: str, code: str) -> None:
    conv = st.conversation(be.attr(contact, "id"))
    name = flow.first_name(contact)
    de = conv.lang == "de"
    if de:
        text = (f"Hallo{' ' + name if name else ''}, dein Kessel hat eine Störung gemeldet "
                f"({_label_de(code)}, {code}). Ist bei dir die Heizung oder das Warmwasser aus?")
        opts = ["Heizung aus", "Warmwasser aus", "Alles läuft"]
    else:
        text = (f"Hi{' ' + name if name else ''}, your boiler reported a fault ({_label(code)}, {code}). "
                "Is your heating or hot water off?")
        opts = ["Heating is off", "Hot water is off", "All working"]
    await out.buttons(contact, case_id, text,
                      [Option(f"aerr_heat:{case_id}", opts[0]), Option(f"aerr_water:{case_id}", opts[1]),
                       Option(f"aerr_fine:{case_id}", opts[2])])


def _label_de(code: str) -> str:
    return {"F.22": "Wasserdruck zu niedrig", "F.28": "Zündung fehlgeschlagen",
            "F.29": "Flamme im Betrieb erloschen"}.get(code, "Kesselstörung")


async def on_answer(contact, case_id: str, kind: str) -> None:
    conv = st.conversation(be.attr(contact, "id"))
    conv.case_id = conv.case_id or case_id
    de = conv.lang == "de"
    if kind == "aerr_heat":
        be.add_tenant_input(case_id, "tap: heating off")
        await flow.on_cold(contact, case_id, True)  # the boiler itself: every radiator, no triage question
    elif kind == "aerr_water":
        be.add_tenant_input(case_id, "tap: hot water off")
        from . import diagnosis

        conv.step = st.DIAGNOSIS
        await diagnosis.begin(contact, conv, "No hot water" + (f" (boiler reported {conv.error_code})"
                                                               if conv.error_code else ""))
    else:
        be.add_tenant_input(case_id, "tap: all working")
        be.record_event(case_id, "tenant", "asset.error_no_impact",
                        "Tenant says heating and hot water work despite the boiler error", {})
        conv.step = st.WAITING_APPROVAL
        await out.text(contact, case_id,
                       "Gut zu hören. Ich habe es für deine Hausverwaltung notiert; schreib mir, falls etwas ausfällt."
                       if de else "Good to hear. I've noted it for your property management; message me if "
                       "anything stops working.")
