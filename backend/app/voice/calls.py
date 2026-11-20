"""Phone/web calls with Debye (ElevenLabs Conversational AI) landing in the same case as WhatsApp.

ElevenLabs runs the voice conversation and calls our server tools (identify_caller, report_issue).
When the call ends we put it on the case timeline ("Call with Luka (1:12): ...") and Debye continues
on WhatsApp with a short summary plus the next button (consent / triage), so nothing is asked twice.

The end of a call is detected three ways, whichever comes first (deduped by conversation id):
  1. ElevenLabs' post-call webhook (POST /api/voice/post_call), if configured in the workspace;
  2. the /call test page telling us the session ended;
  3. a background watcher started on the first tool call that polls the conversation status.
So a real phone call works even without a post-call webhook.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

import httpx

from app.agent import _backend as be
from app.agent import error_codes, flow
from app.agent import outbound as out
from app.agent import state as st

log = logging.getLogger("debye.voice")

ELEVEN_API = "https://api.elevenlabs.io/v1"
POLL_SECONDS = float(os.getenv("VOICE_POLL_SECONDS", "5"))
POLL_MAX_SECONDS = float(os.getenv("VOICE_POLL_MAX_SECONDS", "1200"))


@dataclass
class Call:
    conversation_id: str
    contact_id: str | None = None
    case_id: str | None = None
    duplicate: bool = False
    all_cold: bool | None = None
    error_code: str | None = None
    summary_de: str | None = None
    finished: bool = False
    tools_used: list[str] = field(default_factory=list)
    diagnosis: bool = False  # "no hot water": diagnosis questions asked on the phone
    phone_questions: list[str] = field(default_factory=list)


_calls: dict[str, Call] = {}
_watchers: dict[str, asyncio.Task] = {}


def reset_all() -> None:
    for t in _watchers.values():
        t.cancel()
    _watchers.clear()
    _calls.clear()


def get_call(conversation_id: str | None) -> Call | None:
    return _calls.get(conversation_id or "")


def _call_for(conversation_id: str | None) -> Call | None:
    cid = _clean(conversation_id)
    if not cid:
        return None
    c = _calls.get(cid)
    if c is None:
        c = _calls[cid] = Call(conversation_id=cid)
    return c


# ---------------------------------------------------------------- helpers
def _clean(v) -> str | None:
    """Unset ElevenLabs dynamic variables arrive empty, as 'None'/'unknown', or as '{{name}}'."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in ("none", "null", "unknown", "undefined") or s.startswith("{{"):
        return None
    return s


def resolve_contact(contact_id: str | None = None, caller_id: str | None = None):
    """Web test page passes contact_id; a phone call passes the caller's number (system__caller_id)."""
    contact_id, caller_id = _clean(contact_id), _clean(caller_id)
    if contact_id:
        c = be.get_contact(contact_id)
        if c is not None:
            return c
    if caller_id:
        try:
            return be.get_contact_by_phone(caller_id)
        except Exception:
            log.exception("get_contact_by_phone failed")
    return None


def fmt_duration(secs) -> str:
    try:
        s = int(round(float(secs)))
    except (TypeError, ValueError):
        return "0:00"
    return f"{s // 60}:{s % 60:02d}"


def _norm_code(code: str | None) -> str | None:
    code = _clean(code)
    if not code:
        return None
    c = code.upper().replace(" ", "")
    if c.startswith("F") and not c.startswith("F."):
        c = "F." + c[1:].lstrip(".")
    return c


def _yes_no(v) -> bool | None:
    if isinstance(v, bool):
        return v
    s = (_clean(v) or "").lower()
    if s in ("yes", "ja", "true", "all", "alle", "überall"):
        return True
    if s in ("no", "nein", "false", "some", "one", "einer"):
        return False
    return None


# ---------------------------------------------------------------- caller context up front
def caller_variables(contact) -> dict:
    """Dynamic variables for the start of a call (web page via the signed-URL response, phone via the
    conversation-initiation webhook), so the agent knows the caller without a tool call at the start."""
    ctx = flow.unit_context_for(contact)
    prop, unit = ctx.get("property") or {}, ctx.get("unit") or {}
    heating = next((a for a in ctx.get("assets") or [] if a.get("type") in ("gas_boiler", "heat_pump")), None)
    conv = st.conversation(be.attr(contact, "id"))
    open_cases = ctx.get("open_cases") or []
    mine = [c for c in open_cases if c.get("case_id") == conv.case_id]
    building = [c for c in open_cases if (c.get("type") or "").startswith("repair.heating")]
    if mine:
        c = mine[0]
        open_summary = f"The caller's own open case: {c.get('title')} (status {c.get('status')})."
    elif building:
        c = building[0]
        open_summary = (f"A heating case for the building is already open: {c.get('title')} "
                        f"(status {c.get('status')}). It is being handled.")
    else:
        open_summary = "none"
    boiler = " ".join(str(heating.get(k)) for k in ("make", "model") if heating and heating.get(k)) or "unknown"
    return {
        "contact_id": be.attr(contact, "id"),
        "tenant_name": flow.first_name(contact) or "there",
        "unit_label": str(unit.get("label") or unit.get("id") or "unknown"),
        "address": _address(prop),
        "boiler": boiler,
        "open_case_summary": open_summary,
    }


def _address(prop: dict) -> str:
    addr, city = prop.get("address") or prop.get("street") or "", prop.get("city") or ""
    if city and city not in addr:
        addr = f"{addr}, {city}" if addr else city
    return addr or "unknown"


UNKNOWN_CALLER_VARIABLES = {"contact_id": "unknown", "tenant_name": "there", "unit_label": "unknown",
                            "address": "unknown", "boiler": "unknown", "open_case_summary": "unknown"}


# ---------------------------------------------------------------- server tools
async def identify_caller(conversation_id: str | None, contact_id: str | None, caller_id: str | None) -> dict:
    contact = resolve_contact(contact_id, caller_id)
    call = _call_for(conversation_id)
    if call:
        call.tools_used.append("identify_caller")
        watch(call.conversation_id)
    if contact is None:
        return {
            "known": False,
            "instructions": "Unknown number. Ask politely for name and address, note the issue, and say the "
            "property manager will call back. Do not open a case.",
        }
    if call:
        call.contact_id = be.attr(contact, "id")
    ctx = flow.unit_context_for(contact)
    prop, unit = ctx.get("property") or {}, ctx.get("unit") or {}
    heating = next((a for a in ctx.get("assets") or [] if a.get("type") in ("gas_boiler", "heat_pump")), None)
    conv = st.conversation(be.attr(contact, "id"))
    open_cases = [
        {"case_id": c["case_id"], "title": c.get("title"), "status": c.get("status"),
         "error": c.get("error_label"), "error_code": c.get("error_code"),
         "is_this_callers_case": c["case_id"] == conv.case_id}
        for c in ctx.get("open_cases") or []
    ]
    return {
        "known": True,
        "contact_id": be.attr(contact, "id"),
        "first_name": flow.first_name(contact),
        "address": ", ".join(x for x in [prop.get("address") or prop.get("street"), prop.get("city")] if x),
        "floor": unit.get("floor"),
        "unit": unit.get("label") or unit.get("id"),
        "heating": {k: heating.get(k) for k in ("make", "model", "type", "installed", "last_service")}
        if heating else None,
        "open_cases": open_cases,
        "whatsapp_case_step": conv.step if conv.case_id else None,
        "instructions": "Greet the caller by first name. Never ask for address, floor or boiler model: you have "
        "them. If one of open_cases is a heating case, it is already being handled: say so instead of opening a "
        "new one.",
    }


async def report_issue(
    conversation_id: str | None,
    contact_id: str | None,
    caller_id: str | None,
    summary: str,
    symptoms: str | None = None,
    error_code: str | None = None,
    all_radiators_cold=None,
    priority: str | None = None,
    issue_type: str | None = None,
    answers=None,
) -> dict:
    contact = resolve_contact(contact_id, caller_id)
    call = _call_for(conversation_id)
    if contact is None and call and call.contact_id:
        contact = be.get_contact(call.contact_id)
    if contact is None:
        return {"ok": False, "message": "Caller unknown; say the property manager will call back."}
    if _is_hot_water(issue_type, summary, symptoms):
        if (priority or "").lower() == "emergency" and not parse_answers(answers):
            answers = "q_safety=yes"  # an emergency during a hot-water call is the gas question
        return await _start_diagnosis(contact, call, summary, symptoms, error_code, answers)
    code = _norm_code(error_code)
    summary = (summary or "").strip() or error_codes.case_title(code)
    res = await flow.ensure_case(
        contact,
        summary=summary[:200],
        symptoms=((symptoms or summary) + " (am Telefon gemeldet)")[:500],
        error_code=code,
        priority="emergency" if (priority or "").lower() == "emergency" else "urgent",
    )
    case_id = res["case_id"]
    conv = st.conversation(be.attr(contact, "id"))
    if code and not res.get("duplicate"):
        if res.get("already_open"):
            be.set_case_error_code(case_id, code)
        conv.error_code = code  # explained on the phone: WhatsApp won't explain it again
    be.add_tenant_input(case_id, "phone call")
    all_cold = _yes_no(all_radiators_cold)
    if call:
        call.tools_used.append("report_issue")
        call.contact_id = be.attr(contact, "id")
        call.case_id, call.duplicate = case_id, bool(res.get("duplicate"))
        call.all_cold, call.error_code, call.summary_de = all_cold, code, summary
        watch(call.conversation_id)
    reply = {"ok": True, "case_id": case_id, "duplicate": bool(res.get("duplicate"))}
    if res.get("duplicate"):
        reply["say"] = ("The heating for the building has already been reported and a technician is on it. "
                        "I'll keep you posted on WhatsApp.")
        return reply
    say = ("I've opened a case. After the call I'll send you a short summary on WhatsApp and ask there "
           "whether I may share your details with the heating company.")
    if code:  # meaning first, code in brackets (persona rule); the agent reads "say" out verbatim
        reply["explain_error_code"] = error_codes.resident_sentence(code, "text")
        say = f"{reply['explain_error_code']} {say}"
    reply["say"] = say
    if all_cold is None:
        reply["still_ask"] = "Ask once: are all radiators cold or only one? Then call report_issue again with the answer."
    return reply


# ---------------------------------------------------------------- "no hot water": diagnosis on the phone
VOICE_MAX_QUESTIONS = int(os.getenv("VOICE_MAX_QUESTIONS", "3"))  # KB questions on the phone (safety not counted)
_HEATING_WORDS = ("heating", "radiator", "heizung", "heizkörper")


def _is_hot_water(issue_type: str | None, summary: str | None, symptoms: str | None) -> bool:
    from app.agent import diagnosis

    t = (_clean(issue_type) or "").lower().replace("-", "_").replace(" ", "_")
    if t in ("hot_water", "no_hot_water", "shower"):
        return True
    if t in ("heating", "other", "emergency"):
        return False
    text = f"{summary or ''} {symptoms or ''}"
    if any(w in text.lower() for w in _HEATING_WORDS):
        return False
    return diagnosis.applies(text)


def _question_payload(qid: str) -> dict:
    from app.agent import diagnosis

    if qid == diagnosis.SAFETY_QID:
        return {"question_id": qid, "text": diagnosis.kb()["safety_first"]["question"],
                "answers": {"yes": "the caller smells gas", "no": "no gas smell"}}
    q = diagnosis.questions()[qid]
    return {"question_id": qid, "text": q["text"], "answers": q["answers"]}


def _next_phone_step(contact, call: Call | None, conv: st.Conversation) -> dict:
    """The next question to ask on the phone, or 'wrap up, WhatsApp continues'."""
    from app.agent import diagnosis

    d = conv.diagnosis
    wrap = {"ok": True, "diagnosis": True, "done_on_phone": True,
            "say": "Thanks, that already helps a lot. Right after the call I'll send you the next step on "
                   "WhatsApp, so you don't have to repeat anything.",
            "then": "Say goodbye using their name and call end_call."}
    if not d.get("safety_done"):
        return {"ok": True, "diagnosis": True, "ask": _question_payload(diagnosis.SAFETY_QID)}
    if call is not None and len(call.phone_questions) >= VOICE_MAX_QUESTIONS:
        return wrap
    action, ident, _ = diagnosis.next_step(conv)
    if action != "ask" or ident == "q_display":  # a display photo is easier on WhatsApp
        return wrap
    if call is not None:
        call.phone_questions.append(ident)
    if ident not in d["asked"]:
        d["asked"].append(ident)
    return {"ok": True, "diagnosis": True, "ask": _question_payload(ident)}


PHONE_QUESTIONS = ("q_scope", "q_recent_use", "q_waited")  # asked on the phone (agent prompt lists them)


def parse_answers(answers) -> list[tuple[str, str]]:
    """'q_safety=no; q_scope=only_shower' (or a dict) -> [(qid, key), ...]."""
    if isinstance(answers, dict):
        items = list(answers.items())
    else:
        items = [part.split("=", 1) for part in str(answers or "").replace(",", ";").split(";") if "=" in part]
    return [(q.strip(), str(k).strip().lower().replace(" ", "_")) for q, k in items if q.strip() and str(k).strip()]


async def _start_diagnosis(contact, call: Call | None, summary: str, symptoms: str | None,
                           error_code: str | None, answers=None) -> dict:
    from app.agent import diagnosis

    conv = st.conversation(be.attr(contact, "id"))
    if call:
        call.tools_used.append("report_issue")
        call.contact_id = be.attr(contact, "id")
        call.diagnosis = True
        call.summary_de = (summary or "").strip() or "No hot water"
        watch(call.conversation_id)
    complaint = " ".join(x for x in [(summary or "").strip(), (symptoms or "").strip()] if x) or "No hot water"
    if not conv.diagnosis or conv.diagnosis.get("concluded"):
        diagnosis.start(conv, complaint + " (on the phone)")
        diagnosis.facts_from_centrix(contact, conv)
    code = _norm_code(error_code)
    if code:
        conv.error_code = code
        conv.diagnosis["answers"]["q_display"] = "code"
    conv.step = st.DIAGNOSIS
    pairs = parse_answers(answers)
    if pairs:  # one tool call with everything the caller answered (webhook tools mid-call are fragile)
        cid = call.conversation_id if call else None
        cont_id = be.attr(contact, "id")
        reply = None
        for qid, key in sorted(pairs, key=lambda x: x[0] != diagnosis.SAFETY_QID):
            reply = await answer_question(cid, cont_id, None, qid, key, advance=False)
            if reply.get("emergency"):
                return reply
            if qid != diagnosis.SAFETY_QID and call is not None and qid not in call.phone_questions:
                call.phone_questions.append(qid)
        if call is not None:
            call.phone_questions = [q for q in call.phone_questions if q in conv.diagnosis["answers"]]
        return {"ok": True, "diagnosis": True, "done_on_phone": True,
                "say": "Thanks, that already helps a lot. Right after the call I'll send you the next step on "
                       "WhatsApp, so you don't have to repeat anything.",
                "then": "Say goodbye using their name and call end_call."}
    reply = _next_phone_step(contact, call, conv)
    reply["how"] = ("Ask 'ask.text' in your own short words, then call answer_question with question_id and the "
                    "answer key that fits. If the caller already told you the answer, don't ask, just record it.")
    return reply


async def answer_question(conversation_id: str | None, contact_id: str | None, caller_id: str | None,
                          question_id: str, answer: str, advance: bool = True) -> dict:
    from app.agent import diagnosis

    contact = resolve_contact(contact_id, caller_id)
    call = _call_for(conversation_id)
    if contact is None and call and call.contact_id:
        contact = be.get_contact(call.contact_id)
    if contact is None:
        return {"ok": False, "message": "Caller unknown; say the property manager will call back."}
    conv = st.conversation(be.attr(contact, "id"))
    if not conv.diagnosis:
        return {"ok": False, "message": "No diagnosis running: call report_issue first."}
    qid, key = (question_id or "").strip(), (answer or "").strip().lower().replace(" ", "_")
    if qid == diagnosis.SAFETY_QID:
        if key in ("yes", "true", "ja"):
            if call:
                call.diagnosis = True
            res = await diagnosis.conclude(contact, conv, "gas_smell", 1.0, "Caller reports a gas smell (phone).")
            if call:
                call.case_id = res.get("case_id")
            sf = diagnosis.kb()["safety_first"]["if_yes"]
            return {"ok": True, "emergency": True, "say": sf["tenant_message"],
                    "then": "Say it calmly, then end_call so they can leave the apartment."}
        conv.diagnosis["safety_done"] = True
    else:
        try:
            diagnosis.record(conv, qid, key)
        except ValueError:
            allowed = list((diagnosis.questions().get(qid) or {}).get("answers", {}).keys())
            return {"ok": False, "message": f"Use one of these answer keys for {qid}: {allowed}"}
        if qid not in conv.diagnosis["asked"]:
            conv.diagnosis["asked"].append(qid)
    if not advance:
        return {"ok": True}
    return _next_phone_step(contact, call, conv)


async def _continue_diagnosis_on_whatsapp(contact, call: Call, hello: str) -> None:
    """After a hot-water call: recap the phone answers, then the next question or the conclusion."""
    from app.agent import diagnosis

    conv = st.conversation(be.attr(contact, "id"))
    d = conv.diagnosis
    if not d or d.get("concluded"):
        if d and d.get("concluded") == "gas_smell":
            return  # emergency instructions already sent during the call
        await out.text(contact, conv.case_id, f"{hello} If there's anything else, just message me here.")
        return
    said = [diagnosis.questions()[q]["answers"][k] for q, k in d["answers"].items()
            if q in diagnosis.questions() and k in diagnosis.questions()[q]["answers"] and q != "q_heater_type"]
    recap = "no hot water" + (f": {', '.join(said)}" if said else "")
    await out.text(contact, conv.case_id, f"{hello} Quick recap: {recap}.")
    if not d.get("safety_done"):
        await diagnosis.ask(contact, conv, diagnosis.SAFETY_QID)
        return
    if await diagnosis.apply_centrix_shortcuts(contact, conv):
        return
    action, ident, conf = diagnosis.next_step(conv)
    if action == "ask":
        await diagnosis.ask(contact, conv, ident)
    else:
        await diagnosis.conclude(contact, conv, ident, conf, "From the answers given on the phone call.")


# ---------------------------------------------------------------- end of call
def _first(contact) -> str:
    return flow.first_name(contact) or "resident"


async def finish_call(conversation: dict) -> dict:
    """conversation: the ElevenLabs conversation (post-call webhook `data`, or GET /convai/conversations/{id}).
    Records the call on the case and continues on WhatsApp. Idempotent per conversation id."""
    conv_id = conversation.get("conversation_id")
    call = _call_for(conv_id) or Call(conversation_id="")
    if call.finished:
        return {"ok": True, "already_done": True, "case_id": call.case_id}
    dyn = (conversation.get("conversation_initiation_client_data") or {}).get("dynamic_variables") or {}
    meta = conversation.get("metadata") or {}
    phone = (meta.get("phone_call") or {}).get("external_number")
    contact = (be.get_contact(call.contact_id) if call.contact_id else None) or resolve_contact(
        dyn.get("contact_id"), dyn.get("system__caller_id") or phone)
    if contact is None:
        log.info("call %s ended from an unknown caller; nothing recorded", conv_id)
        call.finished = True
        return {"ok": True, "case_id": None, "unknown_caller": True}
    call.finished = True
    if conv_id:
        t = _watchers.pop(conv_id, None)
        if t and t is not asyncio.current_task():
            t.cancel()
    contact_id = be.attr(contact, "id")
    conv = st.conversation(contact_id)
    case_id = call.case_id or conv.case_id
    duration = fmt_duration(meta.get("call_duration_secs"))
    summary_en = ((conversation.get("analysis") or {}).get("transcript_summary") or "").strip()
    if not summary_en:
        summary_en = call.summary_de or "Call without a report"
    transcript = [
        {"role": t.get("role"), "message": t.get("message"), "t": t.get("time_in_call_secs")}
        for t in conversation.get("transcript") or [] if t.get("message")
    ]
    line = f"Call with {_first(contact)} ({duration}): {timeline_text(call, summary_en, conv)}"
    if call.diagnosis:  # the case (if any) is opened by the diagnosis conclusion on WhatsApp
        await be.log_message(contact_id, conv.case_id, "voice", "in",
                             f"📞 Call ({duration}): {call.summary_de or _first_sentence(summary_en)}",
                             contact_name=be.attr(contact, "name"))
        name = flow.first_name(contact)
        await _continue_diagnosis_on_whatsapp(contact, call, f"Thanks for your call{', ' + name if name else ''}! 📞")
        case_id = call.case_id or st.conversation(contact_id).case_id
        if case_id:
            be.record_event(case_id, "tenant", "call.completed", line,
                            {"conversation_id": conv_id, "duration": duration, "summary": summary_en,
                             "transcript": transcript, "channel": "voice"})
        return {"ok": True, "case_id": case_id, "line": line}
    if case_id:
        be.record_event(case_id, "tenant", "call.completed", line,
                        {"conversation_id": conv_id, "duration": duration, "summary": summary_en,
                         "transcript": transcript, "channel": "voice"})
        if call.all_cold is not None and not call.duplicate:
            be.record_event(case_id, "tenant", "triage.answer",
                            ("All radiators cold" if call.all_cold else "Only one room cold") + " (on the phone)",
                            {"all_radiators_cold": call.all_cold, "channel": "voice"})
    await be.log_message(contact_id, case_id, "voice", "in",
                         f"📞 Call ({duration}): {call.summary_de or _first_sentence(summary_en)}",
                         contact_name=be.attr(contact, "name"))
    await continue_on_whatsapp(contact, case_id, call, duration)
    return {"ok": True, "case_id": case_id, "line": line}


def _first_sentence(text: str, limit: int = 160) -> str:
    t = (text or "").strip()
    cut = t.find(". ")
    t = t[: cut + 1] if 0 < cut < limit else t
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def timeline_text(call: Call, summary_en: str, conv: st.Conversation | None = None) -> str:
    """Short English line for the staff timeline, built from what the tools recorded."""
    if call.diagnosis:
        if conv is not None and (conv.diagnosis or {}).get("concluded") == "gas_smell":
            return "GAS SMELL reported. Emergency advice given on the phone, staff alerted."
        n = len(call.phone_questions)
        return (f"no hot water, safety check + {n} diagnosis question{'s' if n != 1 else ''} answered on the "
                "phone. Diagnosis continues on WhatsApp.")
    if not call.case_id:
        return _first_sentence(summary_en)
    if call.duplicate:
        return "same heating fault reported, linked to the open case"
    parts = ["heating cold"]
    if call.all_cold is not None:
        parts.append("all radiators cold" if call.all_cold else "only one room cold")
    if call.error_code:
        parts.append(f"{error_codes.EN.get(call.error_code, 'boiler error')} ({call.error_code})")
    nxt = "consent asked on WhatsApp" if call.all_cold is not None else "triage continues on WhatsApp"
    return ", ".join(parts) + f". Case opened, {nxt}."


async def continue_on_whatsapp(contact, case_id: str | None, call: Call, duration: str) -> None:
    """Short recap + the next button, so the case simply continues in the chat."""
    name = flow.first_name(contact)
    hello = f"Thanks for your call{', ' + name if name else ''}! 📞"
    if not case_id:
        await out.text(contact, None, f"{hello} If there's anything else, just message me here.")
        return
    if call.duplicate:
        await out.text(contact, case_id, f"{hello} Quick recap: the heating for the building has already been reported "
                                         "and a technician is on it. I'll keep you posted here.")
        return
    recap = (call.summary_de or "Your heating has stopped working").rstrip(". ") + "."
    if call.error_code:
        recap += " " + error_codes.resident_sentence(call.error_code, "text")
    await out.text(contact, case_id, f"{hello} Quick recap: {recap} I've opened a case.")
    conv = st.conversation(be.attr(contact, "id"))
    if conv.step not in (st.NEW, st.TRIAGE):
        return  # the chat is already further along (consent given etc.): nothing to ask
    if call.all_cold is None:
        await flow.ask_cold(contact, case_id)
        return
    cs = st.case_state(case_id)
    cs.triage_answer = "all" if call.all_cold else "some"
    try:
        ranking = be.rank_partners(case_id)
    except Exception:
        log.exception("rank_partners failed")
        ranking = []
    if ranking:
        cs.partner_id, cs.partner_name = be.attr(ranking[0], "partner_id"), be.attr(ranking[0], "name")
    await flow.request_consent(contact, case_id)


# ---------------------------------------------------------------- ElevenLabs API
def _key() -> str | None:
    return os.getenv("ELEVENLABS_API_KEY")


async def fetch_conversation(conversation_id: str) -> dict | None:
    key = _key()
    if not key:
        return None
    async with httpx.AsyncClient(timeout=15) as http:
        r = await http.get(f"{ELEVEN_API}/convai/conversations/{conversation_id}", headers={"xi-api-key": key})
    if r.status_code != 200:
        log.warning("get conversation %s: HTTP %s", conversation_id, r.status_code)
        return None
    return r.json()


async def signed_url(agent_id: str) -> str:
    key = _key()
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY missing")
    async with httpx.AsyncClient(timeout=15) as http:
        r = await http.get(f"{ELEVEN_API}/convai/conversation/get-signed-url",
                           params={"agent_id": agent_id}, headers={"xi-api-key": key})
    r.raise_for_status()
    return r.json()["signed_url"]


async def finish_when_done(conversation_id: str, max_seconds: float | None = None) -> dict | None:
    """Poll ElevenLabs until the conversation is processed, then finish_call."""
    waited, limit = 0.0, max_seconds if max_seconds is not None else POLL_MAX_SECONDS
    while waited <= limit:
        call = get_call(conversation_id)
        if call and call.finished:
            return None
        data = await fetch_conversation(conversation_id)
        if data and data.get("status") in ("done", "failed"):
            return await finish_call(data)
        await asyncio.sleep(POLL_SECONDS)
        waited += POLL_SECONDS
    log.warning("call %s: gave up waiting for the end of the conversation", conversation_id)
    return None


def watch(conversation_id: str) -> None:
    """Start (once) the background watcher for a conversation; no-op without an API key or event loop."""
    if not conversation_id or conversation_id in _watchers or not _key():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def run():
        try:
            await finish_when_done(conversation_id)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("call watcher %s failed", conversation_id)
        finally:
            _watchers.pop(conversation_id, None)

    _watchers[conversation_id] = loop.create_task(run())
