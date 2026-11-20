"""notify_tenant (interfaces §3.4): backend-core calls this when staff or the partner act."""
from __future__ import annotations

import logging

from app.agent import _backend as be
from app.agent import flow
from app.agent import outbound as out
from app.agent import state as st

log = logging.getLogger("debye.notify")


async def notify_tenant(case_id: str, event: str, data: dict) -> None:
    """event ∈ job_accepted | slots_proposed | job_completed | approval_granted | partner_declined."""
    data = data or {}
    cs = st.case_state(case_id)
    if data.get("partner_name"):
        cs.partner_name = data["partner_name"]
    if data.get("partner_id"):
        cs.partner_id = data["partner_id"]
    try:
        if event == "slots_proposed":
            await flow.send_slots(case_id, data.get("slots") or [])
        elif event == "job_completed":
            await flow.ask_fixed(case_id, data.get("notes"))
        elif event == "job_accepted":
            for c in flow.tenant_contacts(case_id, reporter_only=True):
                await out.text(
                    c,
                    case_id,
                    f"Gute Nachricht: {flow.partner_label(case_id)} hat zugesagt 🙌 Terminvorschläge kommen gleich.",
                )
        elif event == "approval_granted":
            for c in flow.tenant_contacts(case_id, reporter_only=True):
                st.conversation(be.attr(c, "id")).step = st.DISPATCHED
                await out.text(
                    c,
                    case_id,
                    f"Die Hausverwaltung hat grünes Licht gegeben 👍 {flow.partner_label(case_id)} meldet sich gleich mit Terminen.",
                )
        elif event == "partner_declined":
            nxt = data.get("next_partner_name")
            if nxt:
                cs.partner_name = nxt
                cs.partner_id = data.get("next_partner_id", cs.partner_id)
            for c in flow.tenant_contacts(case_id, reporter_only=True):
                msg = (
                    f"Kleines Update: Der erste Betrieb hat keine Kapazität. Ich habe {nxt} angefragt."
                    if nxt
                    else "Kleines Update: Der Betrieb hat abgesagt. Ich suche gerade einen anderen."
                )
                await out.text(c, case_id, msg)
        else:
            log.warning("notify_tenant: unknown event %s", event)
    except Exception:
        log.exception("notify_tenant(%s, %s) failed", case_id, event)
