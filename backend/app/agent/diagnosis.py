"""Diagnosis conversation for "no hot water" (docs/diagnosis.md, data/diagnosis/no_hot_water.json).

The model chooses the next question and concludes, using the KB in <diagnosis> and three tools
(ask_question, record_answer, conclude_diagnosis). Code enforces the rules:
  - the safety question (gas smell) comes first and is asked by code; yes → emergency, nothing else;
  - centrix shortcuts before any question: a neighbour's open case on the same central boiler →
    boiler_fault; a building notice today → planned_maintenance;
  - at most 5 questions (ask_question refuses more; the fallback concludes with the best cause);
  - conclusion paths: self_help (tip + follow-up check, no dispatch), caretaker (event + case, no
    partner), utility (staff event), technician (case with trade + diagnosis → consent → approval).
If the model is down, `next_step` (signal matching) picks the question or the conclusion.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from functools import lru_cache
from pathlib import Path

from app.channels.base import Option

from . import _backend as be
from . import outbound as out
from . import state as st

log = logging.getLogger("debye.diagnosis")

KB_PATH = Path(__file__).resolve().parents[3] / "data" / "diagnosis" / "no_hot_water.json"
MAX_QUESTIONS = 5
SAFETY_QID = "q_safety"
CARETAKER_CONTACT = "c_501"
HOT_WATER_RE = re.compile(
    r"(hot water|warm water|shower|lukewarm|no hot|cold water|tap|boiler|warmwasser|warmes wasser|dusche|"
    r"lauwarm|kein warm)", re.IGNORECASE)


@lru_cache(maxsize=1)
def kb() -> dict:
    return json.loads(KB_PATH.read_text(encoding="utf-8"))


def questions() -> dict[str, dict]:
    return {q["id"]: q for q in kb()["questions"]}


def causes() -> dict[str, dict]:
    return {c["id"]: c for c in kb()["causes"]}


def applies(text: str | None) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(p.lower() in t for p in kb().get("applies_to", [])) or bool(HOT_WATER_RE.search(t))


def active(conv: st.Conversation) -> bool:
    d = conv.diagnosis
    return bool(d) and not d.get("concluded")


# ------------------------------------------------------------------ state helpers
def start(conv: st.Conversation, complaint: str | None) -> dict:
    conv.diagnosis = {"answers": {}, "asked": [], "safety_done": False, "concluded": None,
                      "complaint": complaint, "started": time.time(), "facts": []}
    return conv.diagnosis


def record(conv: st.Conversation, qid: str, key: str) -> dict:
    d = conv.diagnosis
    q = questions().get(qid)
    if qid != SAFETY_QID and (q is None or key not in q["answers"]):
        raise ValueError(f"unknown answer {qid}={key}")
    d["answers"][qid] = key
    return d


def _signal_ok(sig: str, answers: dict, facts: list[str], error_code: str | None) -> bool | None:
    """True/False if the signal is decided, None if still unknown."""
    if "=" not in sig:
        return True if sig in facts else None
    qid, want = sig.split("=", 1)
    have = answers.get(qid)
    if have is None:
        return None
    if want.startswith("code:"):
        return have == "code" and (error_code or "").upper() == want[5:].upper()
    return have == want


def score(d: dict, error_code: str | None = None) -> list[dict]:
    """Causes ranked best first: score = (matched − 2·contradicted) / considered signals.
    Fact signals (neighbour_reported, building_notice_today, free-text hints) only count when present:
    the centrix shortcuts already handled them."""
    out = []
    facts = d.get("facts", [])
    for cid, c in causes().items():
        sigs = [s for s in c.get("signals", []) if "=" in s or s in facts]
        if not sigs:
            continue
        ok = bad = unknown = 0
        for s in sigs:
            r = _signal_ok(s, d["answers"], facts, error_code)
            if r is True:
                ok += 1
            elif r is False:
                bad += 1
            else:
                unknown += 1
        if bad == 0 or ok > bad:
            n = len(sigs)
            out.append({"id": cid, "score": (ok - 2 * bad) / n, "potential": (ok + unknown - 2 * bad) / n,
                        "ok": ok, "bad": bad, "unknown": unknown})
    return sorted(out, key=lambda x: (-x["score"], -x["ok"], x["unknown"]))


def _next_question(d: dict, cause_id: str) -> str | None:
    cause = causes()[cause_id]
    order = list(cause.get("ask_order") or []) + [s.split("=")[0] for s in cause["signals"] if "=" in s]
    for qid in dict.fromkeys(order):
        if qid in questions() and qid not in d["answers"] and qid not in d["asked"]:
            return qid
    return None


def next_step(conv: st.Conversation) -> tuple[str, str, float]:
    """Deterministic policy (fallback + guard): ("ask", qid, 0) or ("conclude", cause_id, confidence)."""
    d = conv.diagnosis
    if not d["asked"] and "q_scope" not in d["answers"]:
        return "ask", "q_scope", 0.0  # strategy: usually q_scope first
    ranked = score(d, conv.error_code)
    out_of_questions = len(d["asked"]) >= MAX_QUESTIONS
    if ranked:
        best = ranked[0]
        confidence = round(min(0.95, max(0.4, best["score"])), 2)
        if out_of_questions:
            return "conclude", best["id"], confidence
        if best["unknown"] == 0 and best["score"] > 0:
            # another cause that could still match MORE signals? ask its open question first
            for rival in ranked[1:]:
                if rival["unknown"] and rival["ok"] + rival["unknown"] > best["ok"]                         and rival["potential"] >= best["score"]:
                    qid = _next_question(d, rival["id"])
                    if qid:
                        return "ask", qid, 0.0
            return "conclude", best["id"], confidence
        for cand in ranked:
            qid = _next_question(d, cand["id"])
            if qid:
                return "ask", qid, 0.0
    for qid in ("q_scope", "q_radiators", "q_recent_use", "q_waited", "q_timing", "q_display"):
        if qid not in d["answers"] and qid not in d["asked"]:
            return "ask", qid, 0.0
    return "conclude", (ranked[0]["id"] if ranked else "boiler_fault"), 0.4


def context_block(conv: st.Conversation) -> dict:
    """What the model sees in <diagnosis>."""
    d = conv.diagnosis
    return {
        "symptom": kb()["symptom"],
        "first_message": d.get("complaint"),
        "strategy": kb()["strategy"],
        "questions": [{"id": q["id"], "text": q["text"], "answers": q["answers"]} for q in kb()["questions"]],
        "causes": [{"id": c["id"], "label": c["label"], "signals": c["signals"], "outcome": c["outcome"],
                    "trade": c.get("trade"), **({"applies_if": c["applies_if"]} if c.get("applies_if") else {})}
                   for c in kb()["causes"]],
        "answers_so_far": d["answers"],
        "questions_asked": len(d["asked"]),
        "max_questions": MAX_QUESTIONS,
        "facts": d.get("facts", []),
        "display_error_code": conv.error_code,
        "suggested_next": dict(zip(("action", "id", "confidence"), next_step(conv))),
    }


# ------------------------------------------------------------------ asking
def _options(qid: str) -> list[Option]:
    q = questions()[qid]
    short = {"only_shower": "Only the shower", "everywhere": "Everywhere", "yes": "Yes", "no": "No",
             "code": "Shows a code", "normal": "Looks normal", "dark": "It's dark", "none": "No gas stove",
             "was_wrong": "That was it!", "correct": "Knob is fine", "low": "Below 1 bar", "ok": "1 bar or more",
             "slow": "Warms up slowly", "stays_cold": "Stays cold"}
    return [Option(f"diag:{qid}:{k}", short.get(k, k.replace("_", " ").capitalize())[:20]) for k in q["answers"]]


async def ask(contact, conv: st.Conversation, qid: str, lead: str | None = None) -> None:
    d = conv.diagnosis
    if qid == SAFETY_QID:
        text = kb()["safety_first"]["question"]
        opts = [Option(f"diag:{SAFETY_QID}:yes", "Yes, I smell gas"), Option(f"diag:{SAFETY_QID}:no", "No gas smell")]
    else:
        if len(d["asked"]) >= MAX_QUESTIONS:
            raise ValueError("max questions reached; conclude now")
        text, opts = questions()[qid]["text"], _options(qid)
        d["asked"].append(qid)
    conv.step = st.DIAGNOSIS
    conv.asked_at[st.DIAGNOSIS] = time.monotonic()
    await out.buttons(contact, conv.case_id, f"{lead} {text}" if lead else text, opts)


ELECTRIC_HEATER_TYPES = ("electric_instant_heater", "instant_water_heater", "instantaneous_heater",
                         "durchlauferhitzer", "electric_water_heater")


def facts_from_centrix(contact, conv: st.Conversation) -> None:
    """What centrix already knows: the unit's hot-water source answers q_heater_type, so it isn't asked."""
    from . import flow

    if "q_heater_type" not in questions():
        return
    ctx = flow.unit_context_for(contact)
    assets = ctx.get("assets") or []
    types = {str(be.attr(a, "type") or "").lower() for a in assets}
    if any(t in ELECTRIC_HEATER_TYPES or "instant" in t for t in types):
        conv.diagnosis["answers"]["q_heater_type"] = "yes"
        conv.diagnosis["facts"].append("centrix: electric instantaneous heater in the unit")
    elif (ctx.get("property") or {}).get("heating_central") and "gas_boiler" in types:
        conv.diagnosis["answers"]["q_heater_type"] = "no"
        conv.diagnosis["facts"].append("centrix: hot water from the central gas boiler")


async def begin(contact, conv: st.Conversation, complaint: str | None) -> None:
    """Start: empathy line + safety question (code, always first)."""
    start(conv, complaint)
    facts_from_centrix(contact, conv)
    name = (be.attr(contact, "name") or "").split(" ")[0]
    lead = f"Oh no{', ' + name if name else ''}, a cold shower is the worst 😕 Let me figure out what's going on."
    await ask(contact, conv, SAFETY_QID, lead=lead)


# ------------------------------------------------------------------ answers (taps or mapped free text)
async def on_answer(contact, qid: str, key: str) -> None:
    from . import loop

    conv = st.conversation(be.attr(contact, "id"))
    if not conv.diagnosis:
        start(conv, None)
    d = conv.diagnosis
    if qid == SAFETY_QID:
        d["safety_done"] = True
        if key == "yes":
            await conclude(contact, conv, "gas_smell", 1.0, "Resident reports a gas smell (safety question).")
            return
        if await apply_centrix_shortcuts(contact, conv):
            return
        complaint = d.get("complaint") or ""
        await loop.run_tenant_turn(
            contact,
            f"[No gas smell. The resident's first message was: \"{complaint}\". Record every answer that message "
            "already gives (e.g. only the shower → q_scope=only_shower), then ask the next question.]")
        return
    record(conv, qid, key)
    be.add_tenant_input(conv.case_id, f"answer: {qid}={key}") if conv.case_id else None
    q = questions()[qid]
    await loop.run_tenant_turn(contact, f"[Answer to '{q['text']}': {q['answers'][key]}]")


async def apply_centrix_shortcuts(contact, conv: st.Conversation) -> bool:
    """Neighbour's open case on the same central boiler → boiler_fault; building notice → planned_maintenance."""
    from . import flow

    ctx = flow.unit_context_for(contact)
    notices = ctx.get("notices") or (ctx.get("property") or {}).get("notices") or []
    if any(be.attr(n, "active", True) for n in notices):
        conv.diagnosis["facts"].append("building_notice_today")
        await conclude(contact, conv, "planned_maintenance", 0.9, "Building notice for today in centrix.")
        return True
    asset_id = flow.heating_asset_id(ctx)
    existing = None
    if asset_id:
        try:
            existing = be.find_open_case_for_asset(asset_id)
        except Exception:
            log.exception("find_open_case_for_asset failed")
    if existing is not None and be.attr(existing, "reporter_contact_id") != be.attr(contact, "id"):
        conv.diagnosis["facts"].append("neighbour_reported")
        await conclude(contact, conv, "boiler_fault", 0.9,
                       "A neighbour already reported the central boiler (open case in centrix).")
        return True
    return False


# ------------------------------------------------------------------ conclusion
def _label(cause_id: str) -> str:
    if cause_id == "gas_smell":
        return "Gas smell (emergency)"
    return causes().get(cause_id, {}).get("label", cause_id)


def _qa(qid: str, answers: dict) -> dict:
    q = questions().get(qid, {})
    key = answers.get(qid)
    return {"id": qid, "question": q.get("text", qid), "answer": q.get("answers", {}).get(key, key)}


def diagnosis_record(conv: st.Conversation, cause_id: str, confidence: float, reasoning: str) -> dict:
    d = conv.diagnosis or {}
    return {"cause_id": cause_id, "label": _label(cause_id), "confidence": confidence, "reasoning": reasoning,
            "questions_asked": [_qa(q, d.get("answers", {})) for q in d.get("asked", [])],
            "answers": d.get("answers", {}), "facts": d.get("facts", [])}


async def conclude(contact, conv: st.Conversation, cause_id: str, confidence: float, reasoning: str) -> dict:
    from . import flow

    d = conv.diagnosis or start(conv, None)
    if d.get("concluded"):
        return {"ok": True, "note": "already concluded"}
    if cause_id != "gas_smell" and cause_id not in causes():
        raise ValueError(f"unknown cause {cause_id}")
    d["concluded"] = cause_id
    rec = diagnosis_record(conv, cause_id, confidence, reasoning)
    complaint = d.get("complaint") or "No hot water"

    if cause_id == "gas_smell":
        sf = kb()["safety_first"]["if_yes"]
        res = await flow.ensure_case(contact, summary="Gas smell reported", symptoms=complaint, priority="emergency",
                                     type_="emergency.gas", diagnosis=rec)
        cid = res["case_id"]
        _store(cid, None, rec, opened=not res.get("duplicate") and not res.get("already_open"))
        be.record_event(cid, "debye", "staff.alert", "URGENT: tenant reports a gas smell. Gas emergency line advised.",
                        {"notify_staff": sf.get("notify_staff", "urgent")})
        conv.step = st.CLOSED
        await out.text(contact, cid, sf["tenant_message"])
        return {"ok": True, "outcome": "emergency", "case_id": cid}

    c = causes()[cause_id]
    outcome = c["outcome"]
    if outcome == "self_help":
        conv.step = st.SELF_HELP
        if be.has("close_self_help") and not conv.case_id:
            res = await flow.ensure_case(contact, summary=_title(c, conv), symptoms=complaint, priority="normal",
                                         type_="repair.hot_water", diagnosis=rec)
            if not res.get("duplicate"):
                _store(res["case_id"], None, rec, opened=not res.get("already_open"))
            conv.step = st.SELF_HELP
        await out.text(contact, conv.case_id, c["tenant_message"])
        minutes = 2 if _demo_mode() else (c.get("follow_up_minutes") or 60)
        schedule_follow_up(contact, cause_id, minutes)
        return {"ok": True, "outcome": "self_help", "follow_up_minutes": minutes,
                "note": "Tip sent; no case dispatched. Do not send another message."}

    if outcome == "technician":
        type_ = "repair.heating" if c.get("trade") == "heating" else f"repair.{c.get('trade') or 'general'}"
        res = await flow.ensure_case(contact, summary=_title(c, conv), symptoms=complaint,
                                     error_code=conv.error_code, type_=type_, trade=c.get("trade"), diagnosis=rec)
        cid = res["case_id"]
        if not res.get("duplicate"):
            _store(cid, c.get("trade"), rec, opened=not res.get("already_open"))
        if res.get("duplicate"):
            await flow.send_duplicate_notice(contact, cid)
            return {"ok": True, "outcome": "technician", "case_id": cid, "duplicate": True}
        await out.text(contact, cid, c["tenant_message"])
        cs = st.case_state(cid)
        try:
            ranking = be.rank_partners(cid)  # backend-core ranks by the case's trade
            if ranking:
                cs.partner_id, cs.partner_name = be.attr(ranking[0], "partner_id"), be.attr(ranking[0], "name")
        except Exception:
            log.exception("rank_partners failed")
        await flow.request_consent(contact, cid)
        return {"ok": True, "outcome": "technician", "case_id": cid,
                "note": "Consent question sent. Do not send another message."}

    # caretaker / utility: a case for the record, no partner
    res = await flow.ensure_case(contact, summary=_title(c, conv), symptoms=complaint, error_code=conv.error_code,
                                 type_="repair.hot_water", trade=c.get("trade"), diagnosis=rec)
    cid = res["case_id"]
    if not res.get("duplicate"):
        _store(cid, c.get("trade"), rec, opened=not res.get("already_open"))
    if outcome == "caretaker":
        if be.has("notify_caretaker"):
            try:
                be.notify_caretaker(cid, c["label"])
            except Exception:
                log.exception("notify_caretaker failed")
        else:
            be.record_event(cid, "debye", "caretaker.notified", f"Caretaker asked to check: {c['label']}",
                            {"contact_id": CARETAKER_CONTACT, "cause_id": cause_id})
    else:
        be.record_event(cid, "debye", "staff.utility_contact", f"Staff to contact the gas supplier: {c['label']}",
                        {"cause_id": cause_id})
    conv.step = st.DISPATCHED
    await out.text(contact, cid, c["tenant_message"])
    return {"ok": True, "outcome": outcome, "case_id": cid, "note": "Message sent. Do not send another message."}


def _title(c: dict, conv: st.Conversation) -> str:
    from . import error_codes

    if conv.error_code:
        return error_codes.case_title(conv.error_code)
    return f"No hot water – {c['label'][0].lower()}{c['label'][1:]}"


def _store(case_id: str, trade: str | None, rec: dict, opened: bool = False) -> None:
    """Persist the diagnosis. Newer services record the 'Debye diagnosed: …' event themselves
    (open_case(diagnosis=…) / set_case_diagnosis), so we don't add our own then."""
    if be.has("set_case_diagnosis"):
        if not (opened and be.open_case_takes("diagnosis")):
            try:
                be.set_case_diagnosis(case_id, rec, trade)
            except Exception:
                log.exception("set_case_diagnosis failed")
        return
    be.set_case_data(case_id, trade=trade, diagnosis=rec)
    be.record_event(case_id, "debye", "diagnosis.concluded",
                    f"Diagnosis: {rec['label']} ({int(rec['confidence'] * 100)}%). {rec['reasoning']}", rec)


def _demo_mode() -> bool:
    from app.channels.base import demo_mode

    return demo_mode()


# ------------------------------------------------------------------ follow-up after self-help
_followups: dict[str, asyncio.Task] = {}


def schedule_follow_up(contact, cause_id: str, minutes: float) -> None:
    cid = be.attr(contact, "id")
    old = _followups.pop(cid, None)
    if old and not old.done():
        old.cancel()
    seconds = float(os.getenv("DIAGNOSIS_FOLLOWUP_SECONDS", minutes * 60))
    try:
        _followups[cid] = asyncio.get_running_loop().create_task(_follow_up(contact, cause_id, seconds))
    except RuntimeError:
        log.warning("no running loop; follow-up for %s not scheduled", cid)


async def _follow_up(contact, cause_id: str, seconds: float) -> None:
    await asyncio.sleep(seconds)
    await send_follow_up(contact, cause_id)


async def send_follow_up(contact, cause_id: str) -> None:
    conv = st.conversation(be.attr(contact, "id"))
    name = (be.attr(contact, "name") or "").split(" ")[0]
    conv.step = st.SELF_HELP
    await out.buttons(contact, conv.case_id, f"Hi{' ' + name if name else ''}, just checking in: is the hot water back?",
                      [Option(f"diagfu_yes:{cause_id}", "Yes, all good"), Option(f"diagfu_no:{cause_id}", "Still cold")])


async def on_follow_up(contact, cause_id: str, fixed: bool) -> None:
    conv = st.conversation(be.attr(contact, "id"))
    if fixed:
        conv.step = st.CLOSED
        if conv.case_id and be.has("close_self_help"):
            try:
                be.close_self_help(conv.case_id, f"Tenant confirmed the hot water is back ({_label(cause_id)}).")
            except Exception:
                log.exception("close_self_help failed")
        await out.text(contact, conv.case_id, "Great to hear! 🎉 Enjoy the warm shower.")
        st.reset_conversation(be.attr(contact, "id"))
        return
    # still cold after the self-help tip → send a heating technician
    conv.diagnosis = conv.diagnosis or start(conv, None)
    conv.diagnosis["concluded"] = None
    conv.diagnosis["facts"].append("self_help_failed")
    await out.text(contact, conv.case_id, "Thanks for letting me know, then I'll get a technician to look at it.")
    await conclude(contact, conv, "tank_thermostat_or_scale", 0.6,
                   f"Still cold after the self-help tip for '{_label(cause_id)}'.")
