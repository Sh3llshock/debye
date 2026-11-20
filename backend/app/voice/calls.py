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
) -> dict:
    contact = resolve_contact(contact_id, caller_id)
    call = _call_for(conversation_id)
    if contact is None and call and call.contact_id:
        contact = be.get_contact(call.contact_id)
    if contact is None:
        return {"ok": False, "message": "Caller unknown; say the property manager will call back."}
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
        reply["say"] = ("Die Heizung im Haus ist schon gemeldet und ein Techniker ist informiert. "
                        "Ich halte dich auf WhatsApp auf dem Laufenden.")
        return reply
    say = ("Ich habe einen Fall angelegt. Nach dem Anruf schicke ich dir auf WhatsApp eine kurze "
           "Zusammenfassung und frage dort, ob ich deine Daten an den Heizungsbetrieb weitergeben darf.")
    if code:  # meaning first, code in brackets (persona rule); the agent reads "say" out verbatim
        reply["explain_error_code"] = error_codes.resident_sentence(code, "text")
        say = f"{reply['explain_error_code']} {say}"
    reply["say"] = say
    if all_cold is None:
        reply["still_ask"] = "Ask once: are all radiators cold or only one? Then call report_issue again with the answer."
    return reply


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
    line = f"Call with {_first(contact)} ({duration}): {timeline_text(call, summary_en)}"
    if case_id:
        be.record_event(case_id, "tenant", "call.completed", line,
                        {"conversation_id": conv_id, "duration": duration, "summary": summary_en,
                         "transcript": transcript, "channel": "voice"})
        if call.all_cold is not None and not call.duplicate:
            be.record_event(case_id, "tenant", "triage.answer",
                            ("Alle Heizkörper kalt" if call.all_cold else "Nur ein Raum kalt") + " (am Telefon)",
                            {"all_radiators_cold": call.all_cold, "channel": "voice"})
    await be.log_message(contact_id, case_id, "voice", "in",
                         f"📞 Anruf ({duration}): {call.summary_de or _first_sentence(summary_en)}",
                         contact_name=be.attr(contact, "name"))
    await continue_on_whatsapp(contact, case_id, call, duration)
    return {"ok": True, "case_id": case_id, "line": line}


def _first_sentence(text: str, limit: int = 160) -> str:
    t = (text or "").strip()
    cut = t.find(". ")
    t = t[: cut + 1] if 0 < cut < limit else t
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def timeline_text(call: Call, summary_en: str) -> str:
    """Short English line for the staff timeline, built from what the tools recorded."""
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
    hello = f"Danke für deinen Anruf{', ' + name if name else ''}! 📞"
    if not case_id:
        await out.text(contact, None, f"{hello} Wenn noch etwas ist, schreib mir einfach hier.")
        return
    if call.duplicate:
        await out.text(contact, case_id, f"{hello} Kurz zusammengefasst: Die Heizung im Haus ist schon gemeldet, "
                                         "ein Techniker ist informiert. Ich halte dich hier auf dem Laufenden.")
        return
    recap = (call.summary_de or "Deine Heizung ist ausgefallen").rstrip(". ") + "."
    if call.error_code:
        recap += " " + error_codes.resident_sentence(call.error_code, "text")
    await out.text(contact, case_id, f"{hello} Kurz zusammengefasst: {recap} Den Fall habe ich angelegt.")
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
