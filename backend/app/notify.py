# STUB – replaced by agent-whatsapp
"""Tenant notifications (interfaces §3.4). This stub only logs and records a message.out event."""
from __future__ import annotations

import logging

log = logging.getLogger("debye.notify")


async def notify_tenant(case_id: str, event: str, data: dict) -> None:
    # event ∈ job_accepted | slots_proposed | job_completed | approval_granted | partner_declined
    log.info("[notify stub] case=%s event=%s data=%s", case_id, event, data)
