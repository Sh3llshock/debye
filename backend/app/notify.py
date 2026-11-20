"""notify_tenant (interfaces §3.4): backend-core calls this when staff or the partner act."""
from __future__ import annotations

import logging

from app.agent import _backend as be
from app.agent import flow
from app.agent import outbound as out
from app.agent import state as st

log = logging.getLogger("debye.notify")


async def notify_tenant(case_id: str, event: str, data: dict) -> None:
    """event ∈ job_accepted | slots_proposed (data.slots, data.technician_name) | technician_confirmed
    (data.technician_name, data.slot) | job_completed | approval_pending | approval_granted | approval_rejected (data.reason) | partner_declined."""
    data = data or {}
    cs = st.case_state(case_id)
    if data.get("partner_name"):
        cs.partner_name = data["partner_name"]
    if data.get("partner_id"):
        cs.partner_id = data["partner_id"]
    try:
        if event == "slots_proposed":
            await flow.send_slots(case_id, data.get("slots") or [], data.get("technician_name"))
        elif event == "technician_confirmed":
            await flow.on_technician_confirmed(case_id, data.get("technician_name"), data.get("slot"))
        elif event == "job_completed":
            await flow.ask_fixed(case_id, data.get("notes"))
        elif event == "job_accepted":
            for c in flow.tenant_contacts(case_id, reporter_only=True):
                await out.text(
                    c,
                    case_id,
                    f"{flow.partner_label(case_id)} has taken the job and will suggest times shortly.",
                )
        elif event == "approval_pending":
            await flow.tell_approval_pending(case_id)
        elif event == "approval_rejected":
            reason = (data.get("reason") or "").strip().rstrip(".")
            for c in flow.tenant_contacts(case_id, reporter_only=True):
                st.conversation(be.attr(c, "id")).step = st.WAITING_APPROVAL
                await out.text(
                    c,
                    case_id,
                    "Your property manager has decided not to send a technician for now"
                    + (f": {reason}." if reason else ".") + " They'll be in touch.",
                )
        elif event == "approval_granted":
            cs.approval_notice_sent = False
            for c in flow.tenant_contacts(case_id, reporter_only=True):
                st.conversation(be.attr(c, "id")).step = st.DISPATCHED
                await out.text(
                    c,
                    case_id,
                    f"Your property manager approved the repair. {flow.partner_label(case_id)} will suggest times shortly.",
                )
        elif event == "partner_declined":
            nxt = data.get("next_partner_name")
            if nxt:
                cs.partner_name = nxt
                cs.partner_id = data.get("next_partner_id", cs.partner_id)
            for c in flow.tenant_contacts(case_id, reporter_only=True):
                msg = (
                    f"Quick update: the first company is fully booked, so I've asked {nxt}."
                    if nxt
                    else "Quick update: the company can't take the job. I'm finding another one."
                )
                await out.text(c, case_id, msg)
        else:
            log.warning("notify_tenant: unknown event %s", event)
    except Exception:
        log.exception("notify_tenant(%s, %s) failed", case_id, event)
