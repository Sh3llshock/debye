"""In-process conversation state.

The demo resets anyway, so this lives in memory. Claude history is kept per
contact and append-only; a new history starts when the contact's case closes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Steps of the tenant flow; used to pick scripted fallbacks.
NEW = "new"  # nothing reported yet
TRIAGE = "triage"  # case open, waiting for the cold_all/cold_some tap
CONSENT = "consent"  # consent buttons sent
DISPATCHED = "dispatched"  # job sent to partner
SCHEDULING = "scheduling"  # slots list sent
SCHEDULED = "scheduled"
CONFIRM_FIXED = "confirm_fixed"  # "Ist es wieder warm?" sent
CLOSED = "closed"
WAITING_APPROVAL = "waiting_approval"
DIAGNOSIS = "diagnosis"  # "no hot water" diagnosis questions running
SELF_HELP = "self_help"  # tip given, follow-up check pending


@dataclass
class Conversation:
    contact_id: str
    case_id: str | None = None
    step: str = NEW
    history: list = field(default_factory=list)  # LLM messages (dicts), format of history_provider
    history_provider: str = ""
    tenant_texts: list[str] = field(default_factory=list)
    voice_replied: bool = False  # Debye's one-time voice note (ElevenLabs) was sent
    error_code: str | None = None  # display code already told to the resident
    diagnosis: dict | None = None  # see agent/diagnosis.py
    pending_options: list = field(default_factory=list)  # Options of the last open question (buttons/list)
    pending_question: str | None = None
    asked_at: dict = field(default_factory=dict)  # step -> time.monotonic() of the last question
    pending_inputs: list[str] = field(default_factory=list)  # zero-forms labels before the case exists
    lang: str = "en"  # resident's language for code-written texts (diagnosis.update_lang)
    photos: int = 0  # photos the resident sent in this conversation (consent mentions them only if any)


@dataclass
class CaseState:
    case_id: str
    reporter_contact_id: str | None = None
    partner_id: str | None = None
    partner_name: str | None = None
    consent_fields: list[str] = field(default_factory=lambda: ["name", "phone", "address", "unit_floor", "photos"])
    consent_purpose: str = "Heizungsreparatur vor Ort"
    slots: list[dict] = field(default_factory=list)  # [{start, end, label}]
    approval_notice_sent: bool = False
    technician_name: str | None = None  # set by notify slots_proposed / technician_confirmed
    chosen_slot: dict | None = None
    triage_answer: str | None = None


_convs: dict[str, Conversation] = {}
_cases: dict[str, CaseState] = {}


def conversation(contact_id: str) -> Conversation:
    c = _convs.get(contact_id)
    if c is None:
        c = _convs[contact_id] = Conversation(contact_id=contact_id)
    return c


def case_state(case_id: str) -> CaseState:
    s = _cases.get(case_id)
    if s is None:
        s = _cases[case_id] = CaseState(case_id=case_id)
    return s


def conversations_for_case(case_id: str) -> list[Conversation]:
    return [c for c in _convs.values() if c.case_id == case_id]


def reset_conversation(contact_id: str) -> None:
    _convs.pop(contact_id, None)


def reset_all() -> None:
    """Call from /demo/reset."""
    _convs.clear()
    _cases.clear()
