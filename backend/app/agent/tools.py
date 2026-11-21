"""Tool schemas (strict) and their implementations for the tenant persona."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.channels.base import Option

from . import flow
from . import outbound as out
from . import state as st

log = logging.getLogger("debye.tools")


def be_id(contact) -> str | None:
    from . import _backend as be

    return be.attr(contact, "id")


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
        "options). Pick the one that best splits the remaining causes. Max 3 per diagnosis (re-asking the open "
        "question doesn't count).",
        "input_schema": _obj({"question_id": {"type": "string"},
                              "translation": {"type": ["string", "null"],
                                              "description": "null if the resident writes English. Otherwise the "
                                              "question text translated into their language (same meaning)."},
                              "lead_in": {"type": ["string", "null"],
                                          "description": "optional few words of lead-in like 'Ok.' or 'Got it, "
                                          "thanks.' (no filler empathy, no question; the system adds the question; "
                                          "null = a default lead-in)"}}),
    },
    {
        "name": "record_answer",
        "description": "Diagnosis mode only: record what the resident told you in free text as an answer key of a "
        "question (also for questions you didn't ask, e.g. 'my roommate just showered' → q_hot_water_use=before). "
        "Use answer_key 'unknown' when the tenant doesn't know or can't check; the question is then skipped.",
        "input_schema": _obj({"question_id": {"type": "string"}, "answer_key": {"type": "string"}}),
    },
    {
        "name": "clarify",
        "description": "Diagnosis mode only: the tenant's answer is truly ambiguous ('everything', 'idk', 'kinda'). "
        "Ask ONE short clarifying question instead of guessing, e.g. 'Do you mean all the taps, or that everything "
        "was running at the same time?'. Doesn't count as a diagnostic question; at most 2 per diagnosis.",
        "input_schema": _obj({"text": {"type": "string"}}),
    },
    {
        "name": "conclude_diagnosis",
        "description": "Diagnosis mode only: finish with the most likely cause from <diagnosis>.causes. The system "
        "tells the resident the cause and does the right next step (tip + follow-up, caretaker, or case + consent "
        "for a technician). Do not send another message after it.",
        "input_schema": _obj({"cause_id": {"type": "string"},
                              "confidence": {"type": "number", "description": "0..1"},
                              "reasoning": {"type": "string", "description": "one or two sentences for the staff, "
                                            "using only answers_so_far and centrix facts"},
                              "translation": {"type": ["string", "null"],
                                              "description": "null if the resident writes English. Otherwise the "
                                              "cause's tenant_message translated into their language."}}),
    },
]

SCHEMAS += [
    {
        "name": "ask_free",
        "description": "model_first diagnosis only (<diagnosis>.mode = model_first): ask the resident ONE short question "
        "in your own words (their language), the one that best separates the likely causes in <diagnosis>.reference. "
        "options: 0-3 short tap answers (max 20 characters each), or [] for a free answer. Max 3 questions per "
        "diagnosis; never ask what the resident already said; never the same question twice.",
        "input_schema": _obj({"question": {"type": "string"},
                              "options": {"type": "array", "items": {"type": "string"}}}),
    },
    {
        "name": "switch_area",
        "description": "model_first diagnosis only: the problem belongs to another area (see <diagnosis>.other_areas), "
        "e.g. the resident says the water comes from the ceiling. Switches the reference to that area; then ask or "
        "conclude in the same turn.",
        "input_schema": _obj({"area": {"type": "string"}}),
    },
]

for s in SCHEMAS:
    s["strict"] = True


async def _reply(ctx: TurnContext, text: str) -> dict:
    from . import diagnosis

    if not (text or "").strip():
        raise ValueError("empty message: send nothing instead")
    if {"ask_question", "clarify"} & set(ctx.calls[:-1]) and diagnosis.active(ctx.conv):
        raise ValueError("A diagnosis question was just sent: stop now, don't add another message.")

    d = ctx.conv.diagnosis
    if diagnosis.active(ctx.conv) and diagnosis.model_first(d):
        if "?" in text:
            raise ValueError("model_first: ask questions only with ask_free (it checks for repeats and the limit)")
        if "?" not in (d.get("last_text") or "") or {"ask_free", "conclude_diagnosis"} & set(ctx.calls[:-1]):
            raise ValueError("model_first: no plain-text messages during the diagnosis. Ask with ask_free, or "
                             "finish with conclude_diagnosis (it sends the cause's message and the next step).")
    if diagnosis.active(ctx.conv) and diagnosis.open_question(d) and "?" in text:
        raise ValueError(f"Question {diagnosis.open_question(d)} is still open: don't ask anything in plain text. Record what the "
                         "resident said, or send a short acknowledgement without a question, or nothing.")
    await out.text(ctx.contact, ctx.conv.case_id, text)
    ctx.sent += 1
    return {"ok": True, "delivered": True}


def _no_free_questions_in_diagnosis(ctx: TurnContext) -> None:
    from . import diagnosis

    if diagnosis.active(ctx.conv):
        raise ValueError("A diagnosis is running: ask only with ask_question (or reply without a question). "
                         + ("A question was already sent this turn; stop now." if ctx.sent else ""))


async def _ask_buttons(ctx: TurnContext, text: str, options: list[dict]) -> dict:
    import time

    _no_free_questions_in_diagnosis(ctx)

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
    _no_free_questions_in_diagnosis(ctx)
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
            "explain_error_code": resident_sentence(error_code, "photo") + " Thanks for the photo, that helps the technician."}


async def _record_triage(ctx: TurnContext, case_id: str, all_radiators_cold: bool) -> dict:
    case_id = ctx.conv.case_id or case_id
    await flow.on_cold(ctx.contact, case_id, all_radiators_cold)
    ctx.sent += 1
    sent = "Consent question" if all_radiators_cold else "Radiator tip (thermostat valve, bleeding) with buttons"
    return {"ok": True, "note": f"{sent} was sent to the resident. Do not send another message."}


async def _ask_question(ctx: TurnContext, question_id: str, lead_in: str | None = None,
                        translation: str | None = None) -> dict:
    from . import diagnosis

    if not diagnosis.active(ctx.conv):
        raise ValueError("no diagnosis running")
    d = ctx.conv.diagnosis
    if diagnosis.model_first(d):
        raise ValueError("model_first diagnosis: ask in your own words with ask_free")
    if question_id not in diagnosis.questions():
        raise ValueError(f"unknown question {question_id}")
    if question_id in d["answers"]:
        raise ValueError(f"{question_id} is already answered ({d['answers'][question_id]}); ask something else")
    if question_id == diagnosis.open_question(d):  # re-asking the open question (after "hello?", "lol", a side question)
        if {"ask_question", "clarify"} & set(ctx.calls[:-1]):
            raise ValueError("A question was already sent this turn. Stop now.")
        await diagnosis.ask(ctx.contact, ctx.conv, question_id, lead=(lead_in or "").split("?")[0].strip() or None,
                            text=translation)
        ctx.sent += 1
        return {"ok": True, "delivered": True, "note": "Open question repeated. Wait for the answer."}
    if len(d["asked"]) >= diagnosis.MAX_QUESTIONS:
        raise ValueError("3 questions asked: call conclude_diagnosis now with the most likely cause")
    action, ident, _conf = diagnosis.next_step(ctx.conv)
    if action == "conclude" and d["answers"]:
        raise ValueError(f"The answers already point to {ident}: call conclude_diagnosis now instead of asking")
    if question_id in diagnosis.NEVER_ASK:
        raise ValueError(f"Never ask {question_id}; record it only if the resident mentions it")
    forced = diagnosis.forced_question(ctx.conv)
    if forced and question_id != forced:
        raise ValueError(f"Ask {forced} now (it decides between the causes that fit)")
    cands = diagnosis.question_candidates(ctx.conv)
    if cands and question_id not in cands[:2] and not (action == "ask" and ident == question_id):
        raise ValueError(f"{question_id} doesn't help much now; ask {cands[0]} (it splits the causes that fit "
                         f"the answers so far)")
    if ctx.conv.step == st.DIAGNOSIS and diagnosis.open_question(d) and ctx.sent \
            and diagnosis.open_question(d) != question_id:
        raise ValueError("A question was already sent this turn. Stop now and send nothing else.")
    if lead_in and "?" in lead_in:  # the KB question follows; never ask twice
        head = lead_in.split("?")[0]
        lead_in = head.rsplit(".", 1)[0].strip() + "." if "." in head else None
    await diagnosis.ask(ctx.contact, ctx.conv, question_id, lead=lead_in, text=translation)
    ctx.sent += 1
    return {"ok": True, "delivered": True, "note": "Question sent with its options. Wait for the answer."}


async def _record_answer(ctx: TurnContext, question_id: str, answer_key: str) -> dict:
    from . import diagnosis

    if not diagnosis.active(ctx.conv):
        raise ValueError("no diagnosis running")
    d = ctx.conv.diagnosis
    if diagnosis.open_question(d) != question_id and \
            not diagnosis.explicit_enough(question_id, answer_key, d.get("last_text") or d.get("complaint")):
        raise ValueError(f"The resident didn't say that explicitly ('{(d.get('last_text') or '')[:60]}'); "
                         f"don't record {question_id} from it")
    diagnosis.record(ctx.conv, question_id, answer_key)
    action, ident, conf = diagnosis.next_step(ctx.conv)
    return {"ok": True, "answers_so_far": ctx.conv.diagnosis["answers"],
            "suggested_next": {"action": action, "id": ident, "confidence": conf}}


async def _conclude(ctx: TurnContext, cause_id: str, confidence: float, reasoning: str,
                    translation: str | None = None) -> dict:
    from . import diagnosis

    if not diagnosis.active(ctx.conv):
        raise ValueError("no diagnosis running")
    if not diagnosis.question_slot_free(ctx.conv.diagnosis):
        raise ValueError("A question was sent this turn: wait for the answer before concluding.")
    if diagnosis.model_first(ctx.conv.diagnosis):
        if cause_id not in diagnosis.causes():
            raise ValueError(f"unknown cause {cause_id}; pick one of <diagnosis>.reference.causes (or switch_area)")
        if not diagnosis.evidence_ok(ctx.conv, reasoning):
            raise ValueError('Quote the resident: the reasoning must contain at least one "..." quote of what they '
                             "wrote (or a centrix fact). Never state anything they didn't say.")
        res = await diagnosis.conclude(ctx.contact, ctx.conv, cause_id, max(0.0, min(1.0, confidence)), reasoning,
                                       translation=translation, force=True)
        ctx.sent += 1
        return res
    res = await diagnosis.conclude(ctx.contact, ctx.conv, cause_id, max(0.0, min(1.0, confidence)), reasoning,
                                   translation=translation)
    ctx.sent += 1
    return res


async def _clarify(ctx: TurnContext, text: str) -> dict:
    from . import diagnosis

    d = ctx.conv.diagnosis
    if not diagnosis.active(ctx.conv):
        raise ValueError("no diagnosis running")
    if diagnosis.model_first(d):
        raise ValueError("model_first diagnosis: a clarifying question is a question too, use ask_free")
    if d.get("clarifications", 0) >= 2:
        raise ValueError("2 clarifications used: record what you can (or 'unknown') and move on")
    if ctx.sent:
        raise ValueError("A message was already sent this turn: stop now.")
    if not (text or "").strip() or "?" not in text:
        raise ValueError("a clarifying question must be one short question")
    if d.get("asked") and not diagnosis.open_question(d) and not d.get("conflicts"):
        last = d["asked"][-1]
        raise ValueError(f"The answer is clear ({last}={d['answers'].get(last, 'unknown')}); don't clarify, "
                         "continue with the next question or conclude")
    if diagnosis.area_of(d) != diagnosis.HOT_WATER and not d.get("conflicts"):
        oq = diagnosis.open_question(d) or "-"
        if re.fullmatch(r"\W*(y(es|ep|eah|up|a|ess+)|yes+|sure|exactly|correct|right|ja|genau|richtig|no|nope|nah|"
                        r"nein)\W*", (d.get("last_text") or "").strip(), re.I):
            raise ValueError("The resident answered with a clear yes/no: record_answer for the open question with "
                             "the matching key and continue. Never ask 'just to confirm'.")
        if d.get("clarify_turn") is not None and d.get("turn", 0) - d["clarify_turn"] <= 1:
            raise ValueError("You just asked a clarifying question and the resident answered it ('yes' confirms it). "
                             "Never confirm twice: record what it means with record_answer (or 'unknown') and continue "
                             "with the next question, or conclude.")
        if oq in d.get("clarified", []):
            raise ValueError(f"{oq} was already clarified once: record_answer({oq}, 'unknown') and move on.")
        d.setdefault("clarified", []).append(oq)
        d["clarify_turn"] = d.get("turn", 0)
    d["clarifications"] = d.get("clarifications", 0) + 1
    if d.get("conflicts"):  # the conflict question goes out with both answers as buttons
        await diagnosis.ask_conflict(ctx.contact, ctx.conv)
        d["clarifications"] -= 1  # (ask_conflict counted it)
        ctx.sent += 1
        return {"ok": True, "delivered": True, "note": "Asked which answer is right. Wait for it."}
    await out.text(ctx.contact, ctx.conv.case_id, text.strip())
    ctx.sent += 1
    return {"ok": True, "delivered": True, "note": "Wait for the tenant's answer."}


async def _ask_free(ctx: TurnContext, question: str, options: list[str]) -> dict:
    from . import diagnosis

    d = ctx.conv.diagnosis
    if not diagnosis.active(ctx.conv) or not diagnosis.model_first(d):
        raise ValueError("ask_free is only for a model_first diagnosis; use ask_question")
    question = (question or "").strip()
    if "?" not in question or len(question) > 300:
        raise ValueError("one short question, ending with '?'")
    if ctx.sent or not diagnosis.question_slot_free(d):
        raise ValueError("A message was already sent this turn: stop now.")
    asked = d.setdefault("free_q", [])
    if len(asked) >= diagnosis.MAX_QUESTIONS:
        raise ValueError("3 questions asked: call conclude_diagnosis now with the most likely cause")
    for prev in asked:
        if diagnosis.too_similar(question, prev):
            raise ValueError(f"You already asked that ('{prev}'). Never repeat a question: ask something different "
                             "that moves the diagnosis on, or conclude with the most likely cause.")
    opts = [o.strip()[:20] for o in (options or []) if o and o.strip()][:3]
    asked.append(question)
    d["free_open"] = question
    d["q_turn"] = d.get("turn")
    ctx.conv.step = st.DIAGNOSIS
    if opts:
        de = ctx.conv.lang == "de"
        rows = [Option(f"fa{i}", o) for i, o in enumerate(opts)] + \
            [Option("fa9", "Etwas anderes" if de else "Something else")]
        if len(rows) > 3:
            await out.list_(ctx.contact, ctx.conv.case_id, question, "Auswählen" if de else "Choose", rows)
        else:
            await out.buttons(ctx.contact, ctx.conv.case_id, question, rows)
    else:
        await out.text(ctx.contact, ctx.conv.case_id, question)
    ctx.sent += 1
    return {"ok": True, "delivered": True, "note": "Question sent. Wait for the answer."}


async def _switch_area(ctx: TurnContext, area: str) -> dict:
    from . import diagnosis

    d = ctx.conv.diagnosis
    if not diagnosis.active(ctx.conv) or not diagnosis.model_first(d):
        raise ValueError("switch_area is only for a model_first diagnosis")
    if area not in diagnosis.areas() or area == diagnosis.HOT_WATER:
        raise ValueError(f"unknown area {area}; pick one of <diagnosis>.other_areas")
    if area == diagnosis.area_of(d):
        return {"ok": True, "note": "already in that area"}
    if d.get("switches", 0) >= 2:
        raise ValueError("area switched twice already: conclude with the best outcome")
    keep = {k: d.get(k) for k in ("free_q", "free_open", "turn", "q_turn", "facts")}
    complaint = "\n".join(t for t in [d.get("complaint"), d.get("last_text")] if t)
    diagnosis.start(ctx.conv, complaint, area)
    ctx.conv.diagnosis.update({k: v for k, v in keep.items() if v is not None})
    ctx.conv.diagnosis["switches"] = d.get("switches", 0) + 1
    if ctx.conv.triage is not None:
        ctx.conv.triage["area"] = area
    return {"ok": True, "diagnosis": diagnosis.model_first_context(ctx.conv)}


IMPLS: dict[str, Callable[..., Awaitable[dict]]] = {
    "clarify": _clarify,
    "ask_question": _ask_question,
    "record_answer": _record_answer,
    "conclude_diagnosis": _conclude,
    "ask_free": _ask_free,
    "switch_area": _switch_area,
    "reply": _reply,
    "ask_buttons": _ask_buttons,
    "ask_list": _ask_list,
    "open_case": _open_case,
    "note_error_code": _note_error_code,
    "record_triage_answer": _record_triage,
}


SENDING_TOOLS = {"reply", "ask_buttons", "ask_list", "ask_question", "clarify", "conclude_diagnosis", "ask_free",
                 "record_triage_answer", "open_case"}


class NewerMessages(Exception):
    """The tenant sent more messages while the model was thinking: re-plan with all of them."""


async def execute(block, ctx: TurnContext) -> dict:
    """Runs one tool_use block and returns the tool_result content block."""
    name = block.name
    ctx.calls.append(name)
    if name in SENDING_TOOLS and ctx.sent == 0:
        from app import router as msg_router

        if msg_router.has_pending(be_id(ctx.contact)):
            raise NewerMessages()
    try:
        impl = IMPLS[name]
        result = await impl(ctx, **dict(block.input))
        return {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result, ensure_ascii=False)}
    except ValueError as exc:  # expected refusals (guards); the model gets the reason and adapts
        log.info("tool %s refused: %s", name, exc)
        return {"type": "tool_result", "tool_use_id": block.id, "content": f"Error: {exc}", "is_error": True}
    except Exception as exc:
        log.exception("tool %s failed", name)
        return {"type": "tool_result", "tool_use_id": block.id, "content": f"Error: {exc}", "is_error": True}
