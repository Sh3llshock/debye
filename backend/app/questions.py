"""Feature 4: a partner asks the tenant a question (needs_info) and just-in-time access details.

needs_info: POST /api/partner/{pid}/jobs/{case_id}/question stores case.data.open_question and
case.data.questions[], records job.needs_info and sends the question to the tenant (agent/flow.py).
The tenant's next free-text reply on that case is the answer (router.py → flow.answer_open_question):
stored on the question, recorded as job.info_provided, visible on the partner's job card.

Access details (Unit.access: key_safe_code, intercom_name, parking_note) are released to the partner
only with the tenant's consent for "access_details" AND on the day of the booked slot (demo clock).
The first release records access.released.
"""
from __future__ import annotations

from datetime import datetime

from sqlmodel import select

from .config import now, now_iso
from .db import get_session
from .events import record_event
from .models import Case, Contact, Partner, Unit

MAX_QUESTION_CHARS = 500
ACCESS_FIELD = "access_details"
ACCESS_KEYS = ("key_safe_code", "intercom_name", "parking_note")


class QuestionError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _partner_name(s, partner_id: str) -> str:
    p = s.get(Partner, partner_id)
    return ((p.manifest or {}).get("name") if p else None) or partner_id


def asker_name(s, case: Case, partner_id: str) -> str | None:
    """First name of who asks: the assigned technician, else the partner's staff contact."""
    tech = (case.data or {}).get("technician") or {}
    name = tech.get("name")
    if not name:
        staff = s.exec(select(Contact).where(Contact.partner_id == partner_id)).first()
        name = staff.name if staff else None
    return name.split()[0] if name and name.split() else None


def ask(case_id: str, partner_id: str, text: str) -> dict:
    """Store the question and record job.needs_info. Returns the question dict (+ partner_name)."""
    text = " ".join((text or "").split())
    if not text:
        raise QuestionError(422, "the question is empty")
    if len(text) > MAX_QUESTION_CHARS:
        raise QuestionError(422, f"keep the question under {MAX_QUESTION_CHARS} characters")
    with get_session() as s:
        c = s.get(Case, case_id)
        if not c or c.partner_id != partner_id:
            raise QuestionError(404, f"job {case_id} not found for {partner_id}")
        if c.status in ("closed",):
            raise QuestionError(409, "the job is closed")
        data = dict(c.data or {})
        if data.get("open_question"):
            raise QuestionError(409, "wait for the tenant's answer to your last question")
        qs = list(data.get("questions") or [])
        q = {"id": f"q{len(qs) + 1}", "text": text, "asked_by": partner_id,
             "asker_name": asker_name(s, c, partner_id), "asked_at": now_iso(),
             "answer": None, "answered_at": None}
        qs.append(q)
        c.data = {**data, "questions": qs, "open_question": q}
        c.updated_at = now_iso()
        s.add(c)
        s.commit()
        pname = _partner_name(s, partner_id)
    record_event(case_id, "partner", "job.needs_info", f"{pname} asks the tenant: {text}",
                 {"question_id": q["id"], "text": text, "partner_id": partner_id})
    return {**q, "partner_name": pname}


def open_question_for(contact_id: str, prefer_case_id: str | None = None) -> tuple[str, dict] | None:
    """(case_id, open question) for a tenant, preferring their current case."""
    with get_session() as s:
        if prefer_case_id:
            c = s.get(Case, prefer_case_id)
            if c and (c.data or {}).get("open_question"):
                return c.id, c.data["open_question"]
        for c in s.exec(select(Case).where(Case.reporter_contact_id == contact_id)
                        .order_by(Case.updated_at.desc())).all():
            if (c.data or {}).get("open_question") and c.status != "closed":
                return c.id, c.data["open_question"]
    return None


def answer(case_id: str, text: str, contact_id: str | None = None) -> dict | None:
    """Store the tenant's reply on the open question and record job.info_provided."""
    text = (text or "").strip()
    with get_session() as s:
        c = s.get(Case, case_id)
        data = dict((c.data if c else None) or {})
        q = data.get("open_question")
        if not c or not q or not text:
            return None
        ans = {**q, "answer": text[:1000], "answered_at": now_iso()}
        qs = [ans if x.get("id") == q["id"] else x for x in data.get("questions") or []]
        c.data = {**data, "questions": qs, "open_question": None}
        c.updated_at = now_iso()
        s.add(c)
        s.commit()
        pname = _partner_name(s, q.get("asked_by") or c.partner_id or "")
    record_event(case_id, "tenant", "job.info_provided", f"Tenant answered {pname}: {text[:200]}",
                 {"question_id": q["id"], "question": q["text"], "answer": text[:1000],
                  "contact_id": contact_id})
    return {**ans, "partner_name": pname}


# ---------------------------------------------------------------- access details
def _slot_day(slot_start: str | None):
    if not slot_start:
        return None
    try:
        return datetime.fromisoformat(slot_start.replace("Z", "+00:00"))
    except ValueError:
        return None


def access_view(s, c: Case, partner_id: str, consented: set[str]) -> dict | None:
    """Partner-facing access block; None when the unit has no access details on file.
    Records access.released the first time the details are shown."""
    unit = s.get(Unit, c.unit_id) if c.unit_id else None
    access = {k: v for k, v in ((unit.access if unit else None) or {}).items() if k in ACCESS_KEYS and v}
    if not access:
        return None
    if ACCESS_FIELD not in consented:
        return {"consented": False, "released": False}
    start = _slot_day(c.slot_start)
    if start is None:
        return {"consented": True, "released": False, "available_on": None}
    today = now().astimezone(start.tzinfo).date() if start.tzinfo else now().replace(tzinfo=None).date()
    visit_day = start.date()
    if today != visit_day or c.status in ("closed",):
        return {"consented": True, "released": False, "available_on": visit_day.isoformat()}
    data = dict(c.data or {})
    if not data.get("access_released_at"):
        c.data = {**data, "access_released_at": now_iso(), "access_released_to": partner_id}
        s.add(c)
        s.commit()
        record_event(c.id, "debye", "access.released",
                     f"Access details released to {_partner_name(s, partner_id)} for the visit today",
                     {"partner_id": partner_id, "fields": sorted(access)})
    return {"consented": True, "released": True, "available_on": visit_day.isoformat(), **access}
