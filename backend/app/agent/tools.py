"""Tool schemas (strict) and their implementations for the tenant persona."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.channels.base import Option

from . import flow
from . import outbound as out
from . import state as st

log = logging.getLogger("debye.tools")


@dataclass
class TurnContext:
    contact: Any
    conv: st.Conversation
    effort: str = "low"
    sent: int = 0  # messages delivered this turn (to decide on scripted fallback)
    calls: list[str] = field(default_factory=list)


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": required if required is not None else list(props),
        "additionalProperties": False,
    }


_option = _obj({"id": {"type": "string"}, "title": {"type": "string", "description": "max 20 characters"}})
_row = _obj({"id": {"type": "string"}, "title": {"type": "string", "description": "max 24 characters"}})

SCHEMAS: list[dict] = [
    {
        "name": "reply",
        "description": "Send a WhatsApp text message to the resident.",
        "input_schema": _obj({"text": {"type": "string"}}),
    },
    {
        "name": "ask_buttons",
        "description": "Send a message with up to 3 reply buttons. Use for predictable answers.",
        "input_schema": _obj(
            {"text": {"type": "string"}, "options": {"type": "array", "items": _option}}
        ),
    },
    {
        "name": "ask_list",
        "description": "Send a message with a list picker (up to 10 rows).",
        "input_schema": _obj(
            {
                "text": {"type": "string"},
                "button_label": {"type": "string", "description": "max 20 characters"},
                "rows": {"type": "array", "items": _row},
            }
        ),
    },
    {
        "name": "open_case",
        "description": "Open a repair case for the resident's unit (the heating asset is looked up from centrix). "
        "If a case for the same central heating is already open, links the resident to it and returns "
        "duplicate=true.",
        "input_schema": _obj(
            {
                "summary": {"type": "string", "description": "short English title; explain any code, "
                            "e.g. 'No heating – ignition failed (F.28)'"},
                "symptoms": {"type": "string", "description": "what the resident reported, in their words"},
                "error_code": {"type": ["string", "null"], "description": "display code like F.28, or null"},
                "priority": {"type": "string", "enum": ["emergency", "urgent", "normal"]},
            }
        ),
    },
    {
        "name": "note_error_code",
        "description": "Store a boiler display error code on the already open case (e.g. read from a photo "
        "sent after the case was opened). Call this before telling the resident you noted it.",
        "input_schema": _obj({"case_id": {"type": "string"}, "error_code": {"type": "string",
                                                                              "description": "e.g. F.28"}}),
    },
    {
        "name": "record_triage_answer",
        "description": "Use when the resident answers 'are all radiators cold?' by typing instead of tapping. "
        "Finds the installer and asks the resident for consent automatically.",
        "input_schema": _obj({"case_id": {"type": "string"}, "all_radiators_cold": {"type": "boolean"}}),
    },
]

SCHEMAS += [
    {
        "name": "ask_question",
        "description": "Diagnosis mode only: ask one question from <diagnosis>.questions by id (sent with its answer "
        "options). Pick the one that best splits the remaining causes. Max 5 per diagnosis.",
        "input_schema": _obj({"question_id": {"type": "string"},
                              "lead_in": {"type": ["string", "null"],
                                          "description": "optional short empathetic or acknowledging sentence "
                                          "(no question in it; the question text is added by the system)"}}),
    },
    {
        "name": "record_answer",
        "description": "Diagnosis mode only: record what the resident told you in free text as an answer key of a "
        "question (also for questions you didn't ask, e.g. 'my roommate just showered' → q_recent_use=yes).",
        "input_schema": _obj({"question_id": {"type": "string"}, "answer_key": {"type": "string"}}),
    },
    {
        "name": "conclude_diagnosis",
        "description": "Diagnosis mode only: finish with the most likely cause from <diagnosis>.causes. The system "
        "tells the resident the cause and does the right next step (tip + follow-up, caretaker, or case + consent "
        "for a technician). Do not send another message after it.",
        "input_schema": _obj({"cause_id": {"type": "string"},
                              "confidence": {"type": "number", "description": "0..1"},
                              "reasoning": {"type": "string", "description": "one or two sentences for the staff"}}),
    },
]

for s in SCHEMAS:
    s["strict"] = True


async def _reply(ctx: TurnContext, text: str) -> dict:
    await out.text(ctx.contact, ctx.conv.case_id, text)
    ctx.sent += 1
    return {"ok": True, "delivered": True}


async def _ask_buttons(ctx: TurnContext, text: str, options: list[dict]) -> dict:
    import time

    if not options:
        raise ValueError("options must not be empty")
    is_cold = any(o["id"].startswith(("cold_all:", "cold_some:")) for o in options)
    if is_cold and ctx.conv.step == st.TRIAGE and st.TRIAGE in ctx.conv.asked_at:
        raise ValueError("The 'all radiators cold?' question is still open (buttons already sent). Do not ask it "
                         "again; use reply to acknowledge in one sentence without repeating the question.")
    await out.buttons(ctx.contact, ctx.conv.case_id, text, [Option(o["id"], o["title"]) for o in options])
    ctx.sent += 1
    if is_cold:
        ctx.conv.step = st.TRIAGE
        ctx.conv.asked_at[st.TRIAGE] = time.monotonic()
    return {"ok": True, "delivered": True}


async def _ask_list(ctx: TurnContext, text: str, button_label: str, rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("rows must not be empty")
    await out.list_(ctx.contact, ctx.conv.case_id, text, button_label, [Option(r["id"], r["title"]) for r in rows])
    ctx.sent += 1
    return {"ok": True, "delivered": True}


async def _open_case(ctx: TurnContext, summary: str, symptoms: str, error_code: str | None, priority: str) -> dict:
    from . import diagnosis

    if diagnosis.active(ctx.conv):
        raise ValueError("A diagnosis is running: use ask_question / record_answer / conclude_diagnosis instead.")
    res = await flow.ensure_case(
        ctx.contact, summary=summary, symptoms=symptoms, error_code=error_code, priority=priority
    )
    if res.get("duplicate"):
        return {"case_id": res["case_id"], "duplicate": True,
                "next": "Tell the resident it is already reported and being handled. Ask nothing else."}
    if res.get("already_open"):
        return {"case_id": res["case_id"], "duplicate": False, "note": "case was already open for this resident"}
    out = {"case_id": res["case_id"], "duplicate": False,
           "next": f"Ask with ask_buttons: ids cold_all:{res['case_id']} / cold_some:{res['case_id']}."}
    if error_code:
        from .error_codes import resident_sentence

        out["explain_error_code"] = resident_sentence(error_code, "text")
        out["explain_error_code_if_from_photo"] = resident_sentence(error_code, "photo")
    return out


async def _note_error_code(ctx: TurnContext, case_id: str, error_code: str) -> dict:
    from . import _backend as be

    case_id = ctx.conv.case_id or case_id
    if not case_id:
        raise ValueError("no open case; call open_case with error_code instead")
    be.set_case_error_code(case_id, error_code)
    ctx.conv.error_code = error_code
    from .error_codes import resident_sentence

    return {"ok": True, "case_id": case_id, "error_code": error_code,
            "explain_error_code": resident_sentence(error_code, "photo") + " Thanks for the photo, that really helps the technician 👍"}


async def _record_triage(ctx: TurnContext, case_id: str, all_radiators_cold: bool) -> dict:
    case_id = ctx.conv.case_id or case_id
    await flow.on_cold(ctx.contact, case_id, all_radiators_cold)
    ctx.sent += 1
    return {"ok": True, "note": "Consent question was sent to the resident. Do not send another message."}


async def _ask_question(ctx: TurnContext, question_id: str, lead_in: str | None) -> dict:
    from . import diagnosis

    if not diagnosis.active(ctx.conv):
        raise ValueError("no diagnosis running")
    d = ctx.conv.diagnosis
    if question_id not in diagnosis.questions():
        raise ValueError(f"unknown question {question_id}")
    if question_id in d["answers"]:
        raise ValueError(f"{question_id} is already answered ({d['answers'][question_id]}); ask something else")
    if len(d["asked"]) >= diagnosis.MAX_QUESTIONS:
        raise ValueError("5 questions asked: call conclude_diagnosis now with the most likely cause")
    if ctx.conv.step == st.DIAGNOSIS and d["asked"] and d["asked"][-1] not in d["answers"] and ctx.sent:
        raise ValueError("one question at a time")
    if lead_in and "?" in lead_in:  # the KB question follows; never ask twice
        head = lead_in.split("?")[0]
        lead_in = head.rsplit(".", 1)[0].strip() + "." if "." in head else None
    await diagnosis.ask(ctx.contact, ctx.conv, question_id, lead=lead_in)
    ctx.sent += 1
    return {"ok": True, "delivered": True, "note": "Question sent with its options. Wait for the answer."}


async def _record_answer(ctx: TurnContext, question_id: str, answer_key: str) -> dict:
    from . import diagnosis

    if not diagnosis.active(ctx.conv):
        raise ValueError("no diagnosis running")
    diagnosis.record(ctx.conv, question_id, answer_key)
    action, ident, conf = diagnosis.next_step(ctx.conv)
    return {"ok": True, "answers_so_far": ctx.conv.diagnosis["answers"],
            "suggested_next": {"action": action, "id": ident, "confidence": conf}}


async def _conclude(ctx: TurnContext, cause_id: str, confidence: float, reasoning: str) -> dict:
    from . import diagnosis

    if not diagnosis.active(ctx.conv):
        raise ValueError("no diagnosis running")
    res = await diagnosis.conclude(ctx.contact, ctx.conv, cause_id, max(0.0, min(1.0, confidence)), reasoning)
    ctx.sent += 1
    return res


IMPLS: dict[str, Callable[..., Awaitable[dict]]] = {
    "ask_question": _ask_question,
    "record_answer": _record_answer,
    "conclude_diagnosis": _conclude,
    "reply": _reply,
    "ask_buttons": _ask_buttons,
    "ask_list": _ask_list,
    "open_case": _open_case,
    "note_error_code": _note_error_code,
    "record_triage_answer": _record_triage,
}


async def execute(block, ctx: TurnContext) -> dict:
    """Runs one tool_use block and returns the tool_result content block."""
    name = block.name
    ctx.calls.append(name)
    try:
        impl = IMPLS[name]
        result = await impl(ctx, **dict(block.input))
        return {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result, ensure_ascii=False)}
    except Exception as exc:
        log.exception("tool %s failed", name)
        return {"type": "tool_result", "tool_use_id": block.id, "content": f"Error: {exc}", "is_error": True}
