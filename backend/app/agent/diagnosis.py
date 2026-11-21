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
import contextvars
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

KB_DIR = Path(__file__).resolve().parents[3] / "data" / "diagnosis"
KB_PATH = KB_DIR / "no_hot_water.json"
HOT_WATER = "no_hot_water"  # the original KB; every other area (agent/triage.py) uses the same engine
# The KB in use for the conversation being handled: set from conv.diagnosis["area"] at every entry point
# (use_area), so one engine serves all areas while hot water behaves exactly as before.
_AREA: contextvars.ContextVar[str] = contextvars.ContextVar("debye_kb_area", default=HOT_WATER)
MAX_QUESTIONS = 3  # KB strategy (PR 90): at most 3 questions, then the likeliest technician outcome
SAFETY_QID = "q_safety"
CARETAKER_CONTACT = "c_501"
GAS_YES_RE = re.compile(
    r"(?<!no )(?<!not )(?<!don't )(?<!dont )(?<!kein )\b(smell(s|ing)? (of )?gas|gas smell|smells like gas|"
    r"hiss(es|ing)?|riecht nach gas|gasgeruch|zischt|zischen)\b", re.IGNORECASE)
GAS_NO_RE = re.compile(
    r"\b(no,? no gas( smell)?|no gas( smell)?( at all)?|no smell( of gas)?|don'?t smell (any )?(gas|anything)|"
    r"(do )?not smell(ing)? (any )?gas|kein gasgeruch|kein gas|riecht nicht( nach gas)?)\b", re.IGNORECASE)
HOT_WATER_RE = re.compile(
    r"(hot water|warm water|shower|lukewarm|no hot|cold water|tap|boiler|warmwasser|warmes wasser|dusche|"
    r"lauwarm|kein warm|sho?we?r|shwr|ho?t ?wa?te?r|duschen?|hw is|no hw)", re.IGNORECASE)


@lru_cache(maxsize=None)
def load_kb(area: str = HOT_WATER) -> dict:
    """One area's knowledge base: data/diagnosis/<area>.json (same format as no_hot_water.json)."""
    path = KB_DIR / f"{area}.json"
    if not path.is_file() or not re.fullmatch(r"[a-z_]+", area):
        raise KeyError(f"no diagnosis KB for area {area!r}")
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def areas() -> tuple[str, ...]:
    """Every area with a KB (a json file with questions and causes), hot water first."""
    out = []
    for f in sorted(KB_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("questions") and data.get("causes"):
            out.append(f.stem)
    return tuple(sorted(out, key=lambda a: (a != HOT_WATER, a)))


def area_of(x) -> str:
    """The area of a conversation or diagnosis dict (hot water if none is set)."""
    d = x.diagnosis if hasattr(x, "diagnosis") else x
    return (d.get("area") or HOT_WATER) if isinstance(d, dict) else HOT_WATER


def use_area(x) -> str:
    """Point kb()/questions()/causes() at the KB of this conversation (or diagnosis dict)."""
    area = area_of(x)
    if _AREA.get() != area:
        _AREA.set(area)
    return area


def is_hot_water() -> bool:
    return _AREA.get() == HOT_WATER


def kb() -> dict:
    return load_kb(_AREA.get())


def questions() -> dict[str, dict]:
    return {q["id"]: q for q in kb()["questions"]}


def causes() -> dict[str, dict]:
    return {c["id"]: c for c in kb()["causes"]}


def applies(text: str | None) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(p.lower() in t for p in load_kb(HOT_WATER).get("applies_to", [])) or bool(HOT_WATER_RE.search(t))


def active(conv: st.Conversation) -> bool:
    d = conv.diagnosis
    use_area(conv)
    return bool(d) and not d.get("concluded")


# ------------------------------------------------------------------ state helpers
def start(conv: st.Conversation, complaint: str | None, area: str = HOT_WATER) -> dict:
    conv.diagnosis = {"answers": {}, "asked": [], "safety_done": False, "concluded": None,
                      "complaint": complaint, "started": time.time(), "facts": [], "turn": 1}
    if area != HOT_WATER:
        conv.diagnosis["area"] = area
    use_area(conv)
    return conv.diagnosis


def record(conv: st.Conversation, qid: str, key: str, authoritative: bool = False) -> dict:
    """Stores an answer. A different answer to an already answered question is a conflict (kept apart
    until the resident confirms it: a tap, or the same answer again); never silently overwritten."""
    d = conv.diagnosis
    use_area(d)
    conflicts = d.setdefault("conflicts", {})
    explicit = d.setdefault("explicit", [])
    # explicit = a tap, or the answer to the question that was open (or just re-asked)
    now_explicit = authoritative or open_question(d) == qid or d.get("conflict_open") == qid
    valid = key in (questions().get(qid) or {}).get("answers", {})
    if valid and qid in d["answers"] and key != d["answers"][qid]:
        if qid in explicit and not now_explicit:
            # an explicit earlier answer vs. something inferred later: clarify once, else keep the earlier one
            if qid not in d.setdefault("conflict_asked", []):
                conflicts[qid] = key
                log.info("conflict on %s: %s (explicit) vs %s (inferred)", qid, d["answers"][qid], key)
            return d
        conflicts.pop(qid, None)  # the later explicit answer (or one replacing an inferred one) wins
    elif valid and qid in d["answers"]:
        conflicts.pop(qid, None)
    if valid and now_explicit and qid not in explicit:
        explicit.append(qid)
    if key in ("unknown", "dont_know", "cant_check") and qid in questions() \
            and key not in questions()[qid]["answers"]:
        d.setdefault("dont_know", [])
        if qid not in d["dont_know"]:
            d["dont_know"].append(qid)  # don't ask it again; the signal stays unknown
        return d
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
    use_area(d)
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
    order = {cid: i for i, cid in enumerate(kb().get("likelihood_order") or [])}
    return sorted(out, key=lambda x: (-x["score"], -x["ok"], x["unknown"], order.get(x["id"], 99)))


def _next_question(d: dict, cause_id: str) -> str | None:
    use_area(d)
    cause = causes()[cause_id]
    order = list(cause.get("ask_order") or []) + [s.split("=")[0] for s in cause["signals"] if "=" in s]
    for qid in dict.fromkeys(order):
        if qid in questions() and qid not in d["answers"] and qid not in d["asked"] \
                and qid not in d.get("dont_know", []) and qid not in NEVER_ASK:
            return qid
    return None


def _likelihood(cause_id: str) -> int:
    order = kb().get("likelihood_order") or []
    return order.index(cause_id) if cause_id in order else 99


def question_candidates(conv: st.Conversation) -> list[str]:
    """Open questions in the order they help most: first those of causes that already have supporting
    evidence (most matched signals), then along likelihood_order; contradicted causes are skipped."""
    d = conv.diagnosis
    use_area(d)
    ranked = score(d, conv.error_code)
    possible = sorted((r for r in ranked if r["bad"] == 0), key=lambda r: (-r["ok"], _likelihood(r["id"])))
    out: list[str] = []
    for r in possible + [r for r in ranked if r["bad"]]:
        qid = _next_question(d, r["id"])
        if qid and qid not in out:
            out.append(qid)
    return out


# words that show a fact about a question; used to catch explanations that state unasked facts
FACT_WORDS = {
    "q_radiators": ("radiator", "heizkörper", "heating is on", "heating works", "heating is warm"),
    "q_display": ("display", "error code", "shows a code"),
    "q_pressure": ("pressure", "bar"),
    "q_gas_stove": ("stove", "herd"),
    "q_shower_handle": ("knob", "handle", "38"),
    "q_weather_pipe": ("outside wall", "frozen", "frost"),
    "q_recent_work": ("plumber", "work done", "recent work"),
    "q_power": ("power", "lights", "fuse"),
}


def missing_core(d: dict, cause_id: str) -> list[str]:
    """Questions the cause's explanation relies on (KB 'requires') that have no answer yet."""
    use_area(d)
    cause = causes().get(cause_id) or {}
    return [q for q in cause.get("requires") or []
            if q in questions() and q not in d["answers"] and q not in d.get("dont_know", [])]


def fact_words() -> dict[str, tuple[str, ...]]:
    """Words that state a fact about each question (hot water: FACT_WORDS; other KBs: questions' fact_words)."""
    if is_hot_water():
        return FACT_WORDS
    return {q["id"]: tuple(q.get("fact_words") or ()) for q in kb()["questions"] if q.get("fact_words")}


def invented_facts(d: dict, reasoning: str | None) -> list[str]:
    use_area(d)
    text = (reasoning or "").lower()
    first = (d.get("complaint") or "").lower()
    out = []
    for qid, words in fact_words().items():
        if qid in d["answers"] or qid in d.get("dont_know", []):
            continue
        hit = next((w for w in words if re.search(r"\b" + re.escape(w), text) and w not in first), None)
        if hit:
            out.append(f"'{hit}' ({qid} not answered)")
    return out


def contradictions(d: dict, cause_id: str, error_code: str | None = None) -> list[str]:
    use_area(d)
    out = []
    for s in causes()[cause_id].get("signals", []):
        if "=" in s and _signal_ok(s, d["answers"], d.get("facts", []), error_code) is False:
            qid = s.split("=")[0]
            out.append(f"{qid}={d['answers'].get(qid)} (needs {s.split('=', 1)[1]})")
    return out


HOLIDAY_RE = re.compile(r"(holiday|vacation|been away|back from|came back|got back|urlaub|verreist|zurück)",
                        re.IGNORECASE)


NEVER_ASK = {q for q in ("q_gas_stove",)}  # recorded only when the tenant volunteers it


def fallback_cause() -> str:
    """The neutral technician cause when nothing is clear (hot water: boiler_fault)."""
    return kb().get("fallback_cause") or "boiler_fault"


def first_question_rule(conv: st.Conversation) -> str | None:
    """Other areas: a KB rule may force the first question from the complaint's words
    (e.g. 'smoke alarm' → ot_alarm)."""
    d = conv.diagnosis
    if d.get("asked"):
        return None
    text = d.get("complaint") or ""
    for rule in kb().get("first_question_rules") or []:
        qid = rule.get("question")
        if qid in questions() and qid not in d["answers"] and qid not in d.get("dont_know", [])                 and re.search(rule.get("pattern") or "$^", text, re.IGNORECASE):
            return qid
    return None


def code_settles(d: dict, error_code: str | None) -> str | None:
    """A display code decides it: F.22 + gauge below 1 bar → caretaker (via q_pressure), F.22 with normal
    pressure or any other code → boiler technician (gas supply only if the stove won't light either)."""
    code = (error_code or "").upper().replace(" ", "")
    if not code or area_of(d) != HOT_WATER:
        return None
    a = d["answers"]
    if a.get("q_gas_stove") == "no":
        return "gas_supply_interrupted"
    if code in ("F.22", "F22"):
        if a.get("q_pressure") == "low":
            return "low_system_pressure"
        if a.get("q_pressure") == "ok" or "q_pressure" in d.get("dont_know", []):
            return "boiler_fault"
        return None
    return "boiler_fault"


def forced_question(conv: st.Conversation) -> str | None:
    """Questions the gold conversations always ask first in a situation (the model may not pick another)."""
    d = conv.diagnosis
    if use_area(d) != HOT_WATER:
        return first_question_rule(conv)
    a = d["answers"]
    skip = set(a) | set(d.get("dont_know", [])) | set(d["asked"])

    def open_(q):
        return q not in skip and q in questions()

    if a.get("q_radiators") == "yes" or conv.error_code or a.get("q_display") in ("code", "dark"):
        if open_("q_display") and not conv.error_code:
            return "q_display"
        code = (conv.error_code or "").upper().replace(" ", "")
        if code in ("F.22", "F22") and open_("q_pressure"):
            return "q_pressure"
        if a.get("q_display") == "dark" and open_("q_power"):
            return "q_power"
    if (a.get("q_heater_type") == "yes" or HOLIDAY_RE.search(d.get("complaint") or "")) and open_("q_switch_check"):
        return "q_switch_check"
    if ("q_scope" in a or "q_scope" in d["asked"]) and a.get("q_scope") != "only_shower"             and open_("q_hot_water_use") and a.get("q_radiators") != "yes":
        return "q_hot_water_use"  # the cheap check right after the scope (someone just showered / dishwasher)
    if a.get("q_scope") == "everywhere" and a.get("q_hot_water_use") == "no" and open_("q_radiators"):
        return "q_radiators"  # whole flat cold, nobody used it: heating on or off splits boiler vs. hot-water side
    return None


def decisive_self_help(d: dict, error_code: str | None = None) -> str | None:
    """A decisive cause whose required answers are given and match (e.g. q_hot_water_use=before,
    q_gas_stove=no) and that nothing contradicts: conclude at once."""
    use_area(d)
    boiler_problem = error_code or d["answers"].get("q_display") in ("code", "dark") \
        or d["answers"].get("q_radiators") == "yes"
    if d.get("conflicts"):
        return None  # an answer contradicts an earlier one: clarify first
    failed = set(d.get("failed_tips", []))
    by_code = code_settles(d, error_code)
    if by_code:
        return by_code
    for cid in kb().get("likelihood_order", []):
        c = causes().get(cid) or {}
        req = c.get("requires") or []
        if not c.get("decisive") or not req or cid in failed:
            continue
        if c.get("outcome") == "self_help" and boiler_problem:
            continue  # the boiler itself reports a problem: no "try this" tip
        if cid == "gas_supply_interrupted" and d["answers"].get("q_gas_stove") != "no":
            continue
        if all(f"{q}={d['answers'].get(q)}" in c.get("signals", []) for q in req)                 and not contradictions(d, cid, error_code):
            return cid
    return None


def next_step(conv: st.Conversation) -> tuple[str, str, float]:
    """Deterministic policy (fallback + guard): ("ask", qid, 0) or ("conclude", cause_id, confidence)."""
    d = conv.diagnosis
    use_area(d)
    ranked = score(d, conv.error_code)
    out_of_questions = len(d["asked"]) >= MAX_QUESTIONS
    decisive = decisive_self_help(d, conv.error_code)
    if decisive:  # cheap "try this" first; if it doesn't help, the follow-up sends a technician
        return "conclude", decisive, 0.8
    forced = forced_question(conv) if not out_of_questions else None
    if forced:
        return "ask", forced, 0.0
    if ranked:
        best = ranked[0]
        confidence = round(min(0.95, max(0.4, best["score"])), 2)
        if out_of_questions:
            if best["unknown"] and causes()[best["id"]]["outcome"] != "technician":
                tech = next((r for r in ranked if causes()[r["id"]]["outcome"] == "technician"), None)
                if tech:  # KB: still unclear after 3 questions → likeliest technician outcome, staff approve
                    return "conclude", tech["id"], round(min(0.7, max(0.4, tech["score"])), 2)
            return "conclude", best["id"], confidence
        if best["unknown"] == 0 and best["score"] > 0:
            # another cause that could still match MORE signals? ask its open question first
            for rival in ranked[1:]:
                if rival["ok"] and rival["unknown"] and rival["ok"] + rival["unknown"] > best["ok"]                         and rival["potential"] >= best["score"]:  # only rivals with some evidence
                    qid = _next_question(d, rival["id"])
                    if qid:
                        return "ask", qid, 0.0
            return "conclude", best["id"], confidence
        first = kb().get("first_question") or "q_scope"
        if not d["asked"] and first not in d["answers"] and (is_hot_water() or first not in d.get("dont_know", [])):
            return "ask", first, 0.0  # strategy: usually q_scope first (unless already clear)
        cands = question_candidates(conv)
        if cands:
            return "ask", cands[0], 0.0
    order = ("q_scope", "q_hot_water_use", "q_switch_check", "q_wait_result", "q_radiators", "q_display")         if is_hot_water() else tuple(q["id"] for q in kb()["questions"])
    for qid in order:
        if qid not in d["answers"] and qid not in d["asked"] and qid not in d.get("dont_know", [])                 and (is_hot_water() or len(d["asked"]) < MAX_QUESTIONS):
            return "ask", qid, 0.0
    return "conclude", (ranked[0]["id"] if ranked else fallback_cause()), 0.4


def context_block(conv: st.Conversation) -> dict:
    """What the model sees in <diagnosis>."""
    d = conv.diagnosis
    use_area(d)
    suggested = dict(zip(("action", "id", "confidence"), next_step(conv)))
    plan = d.get("plan")
    if plan and not is_hot_water() and len(d["asked"]) < MAX_QUESTIONS and suggested["action"] == "ask":
        nxt = next((q for q in plan["questions"] if q not in d["answers"] and q not in d["asked"]
                    and q not in d.get("dont_know", [])), None)
        if nxt:
            suggested = {"action": "ask", "id": nxt, "confidence": 0.0, "from": "plan"}
    return {
        **({"plan": plan} if plan and not is_hot_water() else {}),
        "symptom": kb()["symptom"],
        "first_message": d.get("complaint"),
        "strategy": kb()["strategy"],
        "likelihood_order": kb().get("likelihood_order", []),
        "questions": [{"id": q["id"], "text": q["text"], "answers": q["answers"]} for q in kb()["questions"]],
        "causes": [{"id": c["id"], "label": c["label"], "signals": c["signals"], "outcome": c["outcome"],
                    "trade": c.get("trade"), **({"applies_if": c["applies_if"]} if c.get("applies_if") else {})}
                   for c in kb()["causes"]],
        "answers_so_far": d["answers"],
        "tenant_doesnt_know": d.get("dont_know", []),
        "open_question": open_question(d),
        "clarifications_left": max(0, 2 - d.get("clarifications", 0)),
        "conflicts": {q: {"earlier": d["answers"].get(q), "now": k} for q, k in (d.get("conflicts") or {}).items()},
        "language": conv.lang,
        "questions_asked": len(d["asked"]),
        "max_questions": MAX_QUESTIONS,
        "facts": d.get("facts", []),
        "display_error_code": conv.error_code,
        "suggested_next": suggested,
    }


# ------------------------------------------------------------------ asking
_SHORT_DE = {"only_shower": "Nur die Dusche", "everywhere": "Überall", "yes": "Ja", "no": "Nein",
             "code": "Zeigt einen Code", "normal": "Sieht normal aus", "dark": "Es ist dunkel", "none": "Kein Gasherd",
             "low": "Unter 1 bar", "ok": "1 bar oder mehr", "before": "Ja, kurz vorher", "same_time": "Ja, gleichzeitig",
             "found_off": "Etwas war aus", "all_on": "Alles an", "cant_check": "Kann ich nicht sehen",
             "not_tried": "Noch nicht probiert", "warms_slowly": "Wird langsam warm", "stays_cold": "Bleibt kalt",
             "set_wrong": "Stoppt bei 38 °C"}


def code_sentence(conv: st.Conversation) -> str:
    from . import error_codes

    if conv.lang == "de":
        de = {"F.22": "der Wasserdruck der Heizung ist zu niedrig, deshalb schaltet sie sich zur Sicherheit ab",
              "F.28": "die Zündung des Kessels ist fehlgeschlagen, deshalb startet die Heizung nicht",
              "F.29": "die Flamme ist im Betrieb ausgegangen, deshalb fällt die Heizung immer wieder aus"}
        what = de.get(conv.error_code, "es liegt eine Störung am Kessel vor")
        return f"Danke, das heißt: {what} (Fehlercode {conv.error_code})."
    return error_codes.resident_sentence(conv.error_code, "text")


def _options(qid: str, lang: str = "en") -> list[Option]:
    q = questions()[qid]
    if q.get("buttons"):  # other areas: the KB names its buttons
        titles = (q.get("buttons_de") if lang == "de" else None) or q["buttons"]
        return [Option(f"diag:{qid}:{k}", (titles.get(k) or k.replace("_", " ").capitalize())[:20])
                for k in q["answers"]]
    if lang == "de":
        de = {**_SHORT_DE, **({"normal": "Ganz auf heiß"} if qid == "q_shower_handle" else {}),
              **({"yes": "Nur ein Rinnsal", "no": "Normaler Durchfluss"} if qid == "q_weather_pipe" else {})}
        return [Option(f"diag:{qid}:{k}", de.get(k, k)[:20]) for k in q["answers"]]
    short = {"only_shower": "Only the shower", "everywhere": "Everywhere", "yes": "Yes", "no": "No",
             "code": "Shows a code", "normal": "Looks normal", "dark": "It's dark", "none": "No gas stove",
             "low": "Below 1 bar", "ok": "1 bar or more",
             "before": "Yes, just before", "same_time": "Yes, same time",
             "found_off": "Something was off", "all_on": "All on", "cant_check": "Can't check",
             "not_tried": "Haven't tried", "warms_slowly": "Warms up slowly", "stays_cold": "Stays cold",
             "set_wrong": "Stops at 38°C"}
    if qid == "q_shower_handle":
        short = {**short, "normal": "Fully on hot"}
    if qid == "q_weather_pipe":
        short = {**short, "yes": "Only a trickle", "no": "Normal flow"}
    return [Option(f"diag:{qid}:{k}", short.get(k, k.replace("_", " ").capitalize())[:20]) for k in q["answers"]]


LEAD_INS = ("Let's fix it.", "Ok.", "Got it.")
LEAD_INS_DE = ("Schauen wir mal.", "Okay.", "Verstanden.")
_DE_WORDS = re.compile(r"\b(ich|nicht|kein|keine|ist|und|bei|mir|das|die|der|ja|nein|danke|bitte|wasser|heizung|"
                       r"dusche|kalt|geht|immer|noch|schon|auch|nur|habe|hat|wieder|deutsch|weiß|heiß|alles|überall|"
                       r"hähne|waschbecken|heizkörper|niemand|weiss|gar|sind|es|wird|okay danke)\b",
                       re.IGNORECASE)
_EN_WORDS = re.compile(r"\b(the|is|and|my|it|not|no|nope|yes|yeah|yep|water|shower|cold|hot|have|has|only|too|just|"
                       r"thanks|everything|everywhere|all|taps?|sinks?|kitchen|radiators?|nobody|none|was|were|i|"
                       r"idk|still|works?|what|why|how|send|someone|please|lol|sure|also|both)\b",
                       re.IGNORECASE)


def update_lang(conv: st.Conversation, text: str | None) -> str:
    """The resident's language from the message itself, short ones too ('no', 'all taps' → English).
    Unclear (an emoji, 'ok', a code) keeps the current one; English by default. The stored contact
    language is never used for this."""
    if text:
        de, en = len(_DE_WORDS.findall(text)), len(_EN_WORDS.findall(text))
        if en and en >= de:
            conv.lang = "en"
        elif de and de > en:
            conv.lang = "de"
    return conv.lang


def _looks_german(s: str | None) -> bool:
    return bool(s) and len(_DE_WORDS.findall(s)) > len(_EN_WORDS.findall(s))


def _looks_english(s: str | None) -> bool:
    return bool(s) and len(_EN_WORDS.findall(s)) > len(_DE_WORDS.findall(s))


def say(conv: st.Conversation, en: str, de: str) -> str:
    return de if getattr(conv, "lang", "en") == "de" else en


def open_question(d: dict) -> str | None:
    """The diagnosis question that is still waiting for an answer (None if none)."""
    if not d or not d.get("asked"):
        return None
    last = d["asked"][-1]
    return None if last in d["answers"] or last in d.get("dont_know", []) else last


async def ask_conflict(contact, conv: st.Conversation) -> None:
    """'Earlier you said X, now it sounds like Y. Which is right?' with both answers as buttons."""
    d = conv.diagnosis
    use_area(d)
    qid, new = next(iter(d["conflicts"].items()))
    q, old = questions()[qid], d["answers"][qid]
    if qid in d.setdefault("conflict_asked", []) or not question_slot_free(d):
        return
    d["conflict_asked"].append(qid)
    d["conflict_open"] = qid
    d["q_turn"] = d.get("turn")
    d["clarifications"] = d.get("clarifications", 0) + 1
    if conv.lang == "de":
        body = "Nur zur Sicherheit, was stimmt?"
    else:
        body = f"Just to check: earlier it sounded like {q['answers'][old]}, now like {q['answers'][new]}. Which is right?"
    opts = [o for o in _options(qid, conv.lang) if o.id.split(":")[2] in (old, new)]
    await out.buttons(contact, conv.case_id, body, opts)


def question_slot_free(d: dict) -> bool:
    """At most one question per turn (a turn = one batch of tenant messages)."""
    return d.get("q_turn") is None or d.get("q_turn") != d.get("turn")


def resolve_conflict_reply(conv: st.Conversation, text: str | None) -> None:
    """Any reply to 'just to check' resolves it: a clear pick wins, anything else keeps the earlier
    (explicit) answer and the diagnosis moves on. Never asked again."""
    d = conv.diagnosis
    use_area(d)
    qid = d.pop("conflict_open", None)
    if not qid:
        return
    new = (d.get("conflicts") or {}).pop(qid, None)
    if not new or not text:
        return
    from . import choice

    opt = choice.fast_match(text, [o for o in _options(qid, conv.lang) if o.id.split(":")[2] in (new, d["answers"][qid])])
    if opt is not None:
        d["answers"][qid] = opt.id.split(":")[2]


async def ask(contact, conv: st.Conversation, qid: str, lead: str | None = None, text: str | None = None) -> None:
    d = conv.diagnosis
    use_area(d)
    if not question_slot_free(d):
        log.info("diagnosis: a question was already sent this turn; %s not sent", qid)
        return
    if open_question(d) == qid and qid in d.setdefault("reasked", []):
        # asked twice already: treat as unknown and move on instead of repeating it again
        d.setdefault("dont_know", []).append(qid)
        action, ident, conf = next_step(conv)
        if action == "ask" and ident != qid:
            return await ask(contact, conv, ident)
        return await conclude(contact, conv, ident if action == "conclude" else
                              likeliest_technician(d, conv.error_code)[0], conf or 0.5,
                              "Moved on after the question was asked twice.", force=True)
    reask = open_question(d) == qid  # repeating the open question ("hello?") doesn't count as a new one
    if not reask and len(d["asked"]) >= MAX_QUESTIONS:
        raise ValueError("max questions reached; conclude now")
    q = questions()[qid]
    de = conv.lang == "de"
    if not de or not _looks_german(text):
        text = None  # English resident: never the model's translation; German: only a real German one
    if reask:  # never the same words twice: the short re-ask wording
        text = q.get("reask_de" if de else "reask") or text
    text = (text or "").strip() or (q.get("text_de") if de else None) or q["text"]
    opts = _options(qid, conv.lang)
    if lead and ((de and _looks_english(lead)) or (not de and _looks_german(lead))):
        lead = None  # a lead-in in the other language: use the default one
    if not reask:
        d["asked"].append(qid)
    else:
        d.setdefault("reasked", []).append(qid)
    d["q_turn"] = d.get("turn")
    if lead is None:  # a few words of lead-in, never filler
        leads = LEAD_INS_DE if conv.lang == "de" else LEAD_INS
        lead = ("Danke." if de else "Thanks.") if reask else \
            leads[0] if len(d["asked"]) == 1 else leads[1 + len(d["asked"]) % 2]
    lead = (lead or "").strip()
    q_words = set(questions()[qid]["text"].lower().split())
    if lead and len(set(lead.lower().split()) & q_words) >= 6:
        lead = LEAD_INS[1]  # the model pasted the question into the lead-in
    if conv.error_code and not d.get("code_explained") and qid in ("q_pressure", "q_gas_stove") and not reask:
        from . import error_codes

        d["code_explained"] = True
        lead = code_sentence(conv) if conv.lang == "de" else "Thanks, " + \
            error_codes.resident_sentence(conv.error_code, "text")[0].lower() + \
            error_codes.resident_sentence(conv.error_code, "text")[1:]
    conv.step = st.DIAGNOSIS
    conv.asked_at[st.DIAGNOSIS] = time.monotonic()
    body = f"{lead} {text}" if lead else text
    if len(opts) > 3:
        await out.list_(contact, conv.case_id, body, "Choose", opts)
    else:
        await out.buttons(contact, conv.case_id, body, opts)


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


async def begin(contact, conv: st.Conversation, complaint: str | None, images: list[str] | None = None) -> bool:
    """Start (KB PR 90): no proactive gas question. centrix context first, then the model takes
    everything the first message says and asks the one best question (max 3)."""
    from . import loop

    start(conv, complaint)
    conv.diagnosis["safety_done"] = True  # gas only matters if the tenant mentions it (router checks every text)
    facts_from_centrix(contact, conv)
    from . import flow

    code, _src = flow.detect_error_code([complaint or ""], images or [])
    if code:  # "the display shows F.28" in the first message (or a photo of it) answers q_display
        conv.error_code = conv.error_code or code
        conv.diagnosis["answers"]["q_display"] = "code"
    await extract_answers(conv, complaint)
    if await apply_centrix_shortcuts(contact, conv):
        return False
    return await loop.run_tenant_turn(
        contact,
        f"[New hot-water report: \"{complaint}\". Record every answer this message already gives, then ask the one "
        "question that best splits the likeliest causes, or conclude if it's already clear.]")


def safety_from_text(text: str | None) -> str | None:
    """'yes' if the resident clearly reports a gas smell, 'no' if they clearly rule it out, else None."""
    if not text:
        return None
    if GAS_NO_RE.search(text):
        return "no"
    if GAS_YES_RE.search(text):
        return "yes"
    return None


FIXED_RE = re.compile(r"\b((it'?s|is|water'?s?|shower'?s?|shower is) (hot|warm)( again| now)|(hot|warm) now|"
                      r"that was it|that did it|that worked|it worked|that fixed it|"
                      r"it works (again|now)|works (again|now)|working (again|now)|(it'?s|is|water'?s?) (warm|hot) "
                      r"again|(warm|hot) water is back|it'?s back|fixed( now)?|solved|all good now|"
                      r"geht wieder|funktioniert wieder|wieder warm|wieder heiß|"
                      r"(it'?s |it )?(draining|drains|dry|closes|shuts|rings) (again|now)|stopped (dripping|leaking)|"
                      r"power'?s? (is )?back|(light|lights|socket|bell) works?( again| now)|läuft wieder( ab)?|"
                      r"tropft nicht mehr|ist wieder trocken|klingelt wieder)\b", re.IGNORECASE)
STILL_COLD_RE = re.compile(r"\b(still (leaking|dripping|blocked|clogged|broken|stuck|dead|dark|there|wet|beeping|not draining)|"
                           r"still no (power|light)|tropft (immer )?noch|immer noch (verstopft|kaputt|undicht)|"
                           r"still (ice[- ]?|freezing |)cold|still freezing|still (not|isn'?t) (working|warm|hot)|didn'?t (work|help)|doesn'?t work|not working|"
                           r"no change|immer noch kalt|geht nicht|hat nicht geholfen)\b", re.IGNORECASE)
FRUSTRATED_RE = re.compile(r"\b(useless|just send (someone|somebody|a technician|a plumber)|send (a|the) technician|"
                           r"stop asking|so many questions|schick( einfach)? (jemand|einen techniker)|nutzlos)\b",
                           re.IGNORECASE)


ACK_RE = re.compile(r"(ok(ay)?|k|thanks?( you)?|thx|danke|will do|will try( it)?( later| now)?|i'?ll try( it)?( later| now)?|"
                    r"sure|alright|cool|got it|perfect|great|👍|🙏|ok,? (thanks|will try( later)?|i'?ll try( later)?))[.! ]*",
                    re.IGNORECASE)
_BUT_RE = re.compile(r"\b(but|aber|cold|kalt|lukewarm|only|nur)\b", re.IGNORECASE)


def fixed_from_text(text: str | None) -> bool | None:
    """True: 'it works again'; False: 'still cold'; None: neither or mixed ('works, but only in the kitchen')."""
    if not text:
        return None
    if STILL_COLD_RE.search(text):
        return False
    if FIXED_RE.search(text) and not _BUT_RE.search(text):
        return True
    if re.fullmatch(r"\s*(yes,?\s*)?(it )?(works|worked|that worked|that was it)[.! ]*", text, re.IGNORECASE):
        return True
    return None


async def resolved_by_tenant(contact, conv: st.Conversation, text: str) -> None:
    """'It works again' during a diagnosis: close nicely, no technician."""
    d = conv.diagnosis
    use_area(d)
    if d:
        d["concluded"] = "resolved_by_tenant"
    if conv.case_id and be.has("close_self_help"):
        try:
            be.close_self_help(conv.case_id, f"Tenant reports it works again: \"{text[:100]}\"")
        except Exception:
            log.exception("close_self_help failed")
    k = load_kb(use_area(d))
    await out.text(contact, conv.case_id, say(conv, k.get("resolved_message") or "Good to hear. Message me any time if it goes cold again.", k.get("resolved_message_de") or "Schön. Melde dich jederzeit, wenn es wieder kalt wird."))
    queued = getattr(conv, "triage", None) if area_of(d) != HOT_WATER else None
    st.reset_conversation(be.attr(contact, "id"))
    if queued:
        from . import triage

        await triage.after_conclusion(contact, st.conversation(be.attr(contact, "id")), queued)


def likeliest_technician(d: dict, error_code: str | None = None) -> tuple[str, bool]:
    """(cause, supported): the likeliest technician cause whose required answers are all given; else
    boiler_fault as a neutral 'heating technician' case (supported=False: don't explain a cause)."""
    use_area(d)
    for r in score(d, error_code):
        c = causes()[r["id"]]
        if c["outcome"] == "technician" and r["bad"] == 0 and not missing_core(d, r["id"]) and r["ok"]:
            return r["id"], True
    if area_of(d) != HOT_WATER:
        return fallback_cause(), False
    return "boiler_fault", d["answers"].get("q_radiators") == "yes" or bool(error_code)


NEUTRAL_TECH = "A technician needs to look at it."
NEUTRAL_TECH_DE = "Das sollte sich ein Techniker ansehen."
NEUTRAL_TECHS = (NEUTRAL_TECH, NEUTRAL_TECH_DE)


def neutral_message(conv: st.Conversation) -> str:
    """'A heating technician needs to look at it.' (or the area's own neutral line)."""
    if is_hot_water():
        return say(conv, NEUTRAL_TECH, NEUTRAL_TECH_DE)
    return say(conv, kb().get("neutral_message") or NEUTRAL_TECH, kb().get("neutral_message_de") or NEUTRAL_TECH_DE)


def neutral_messages() -> tuple[str, ...]:
    return NEUTRAL_TECHS + tuple(m for m in (kb().get("neutral_message"), kb().get("neutral_message_de")) if m)


async def escalate_now(contact, conv: st.Conversation, text: str) -> None:
    """Frustrated tenant: no more questions, send the likeliest technician (staff approve)."""
    d = conv.diagnosis
    use_area(d)
    tech, supported = likeliest_technician(d, conv.error_code)
    # one short acknowledgement, then the consent question (two messages); no cause explained
    await conclude(contact, conv, tech, 0.5, f"Tenant asked for a technician instead of more questions: "
                   f"\"{text[:100]}\". Best guess from the answers so far.", force=True,
                   message=say(conv, "Understood, I'll get a technician to look at it.",
                               "Verstanden, ich schicke einen Techniker vorbei."),
                   trade_unknown=not supported)


# ------------------------------------------------------------------ evidence extraction (free text → answers)
async def _classify_answers(text: str, open_qs: list[dict]) -> dict:
    """One strict structured-output call: for each open question, the answer key the text clearly
    states, or "unknown". Empty dict without an OpenAI key or on any error."""
    if not os.getenv("OPENAI_API_KEY") or (os.getenv("LLM_PROVIDER") or "openai").lower() != "openai":
        return {}
    from openai import AsyncOpenAI

    from app.media import openai_base_url

    props = {q["id"]: {"type": "string", "enum": [*q["answers"].keys(), "unknown"],
                       "description": q["text"] + " | " + "; ".join(f"{k} = {v}" for k, v in q["answers"].items())}
             for q in open_qs}
    schema = {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}
    extra = {}
    effort = os.getenv("OPENAI_REASONING_EFFORT")
    effort = "none" if effort is None else effort
    if effort:
        extra["reasoning_effort"] = effort
    try:
        client = AsyncOpenAI(base_url=openai_base_url(), timeout=8, max_retries=0)
        r = await client.chat.completions.create(
            model=os.getenv("OPENAI_CHAT_MODEL") or "gpt-6-luna",
            messages=[
                {"role": "system", "content": _area_extraction_prompt()} if not is_hot_water() else
                {"role": "system", "content": "A tenant describes a hot-water problem. For each question, give the "
                 "answer key ONLY if the tenant's message clearly states it (paraphrases count: 'the display is dark' "
                 "→ q_display=dark; 'my stove won't light' → q_gas_stove=no; 'stays cold no matter how long I wait' "
                 "→ q_wait_result=stays_cold; 'my flatmate just showered' → q_hot_water_use=before; 'the dishwasher was "
                 "running' → q_hot_water_use=same_time; 'the plumber was here yesterday' → q_recent_work=yes; "
                 "'the kitchen is fine' → q_scope=only_shower; 'the heating is off too' / 'the flat is freezing' → "
                 "q_radiators=yes; 'the radiators are warm' → q_radiators=no; 'can't check' / 'idk' → unknown; "
                 "'I switched the heater back on' → "
                 "q_switch_check=found_off). Ambiguous words ('everything', 'kinda', 'idk', 'both?') are 'unknown'. 'my shower is cold' or 'no hot "
                 "water in the shower' says NOTHING about the sinks: q_scope only when the text explicitly says only "
                 "the shower / the sink is hot (only_shower) or the sinks/all taps are cold too (everywhere). "
                 "If the tenant corrects an earlier statement, use the corrected one. Never guess."},
                {"role": "user", "content": text},
            ],
            response_format={"type": "json_schema", "json_schema": {"name": "answers", "strict": True,
                                                                     "schema": schema}},
            **extra,
        )
        msg = r.choices[0].message
        if getattr(msg, "refusal", None) or not msg.content:
            return {}
        return {k: v for k, v in json.loads(msg.content).items() if v != "unknown"}
    except Exception:
        log.exception("answer extraction failed")
        return {}


def _area_extraction_prompt() -> str:
    k = kb()
    return (f"A tenant reports a problem ({k.get('title') or k['symptom']}). For each question, give the answer key "
            "ONLY if the tenant's message clearly states it (paraphrases count). " + (k.get("extraction_hints") or "")
            + " Ambiguous words ('kinda', 'idk', 'both?', 'everything') are 'unknown'. If the tenant corrects an "
            "earlier statement, use the corrected one. Never guess.")


_ONLY_SHOWER_RE = re.compile(
    r"\b((only|just) (in )?(the |my |our )?shower|shower only|sinks? (is|are|'s)? ?(still )?(hot|warm|fine|ok|okay)|"
    r"kitchen( tap)? (is|'s)? ?(still )?(hot|warm|fine|ok|okay)|(other|rest of the) taps (are )?(fine|hot|ok)|"
    r"(the )?rest is fine|nur (in )?(die |der )?dusche|waschbecken (ist |sind )?(noch )?(warm|heiß|ok)|"
    r"küche (ist )?(warm|heiß|ok))", re.IGNORECASE)
_EVERYWHERE_RE = re.compile(
    r"\b(everywhere|every tap|all (the |of the )?taps|all of them|sinks? too|kitchen too|(the )?sinks? (are|is) "
    r"(also |too )?cold|also (the )?(sinks?|kitchen)|(and|plus) (the )?(sinks?|kitchen)|whole (flat|apartment)|"
    r"kitchen (and|or|&) (in )?(the )?(bath(room)?|shower)|(bath(room)?|shower) (and|or|&) (in )?(the )?(kitchen|sinks?)|"
    r"(kitchen|sink) tap and (the )?shower|both (the )?(kitchen|shower|sink)|"
    r"(kitchen|sinks?)\b[^.!?]{0,25}\bcold|cold (at|in) (the )?(sinks?|kitchen)|"
    r"(shower|kitchen) and (the )?(sinks?|kitchen|shower)|überall|alle hähne|auch (die |das |in der )?(waschbecken|küche))",
    re.IGNORECASE)


def explicit_enough(qid: str, key: str, text: str | None) -> bool:
    """q_scope only from explicit words: 'my shower is cold' says nothing about the sinks."""
    if qid != "q_scope":
        return True
    t = text or ""
    return bool(_ONLY_SHOWER_RE.search(t)) if key == "only_shower" else bool(_EVERYWHERE_RE.search(t))


SELF_CONTRA_RE = re.compile(r"^\W*(no|nope|nah|nein)\b.{0,80}\b(although|though|but|actually|then again|aber|obwohl|"
                            r"allerdings)\b", re.IGNORECASE | re.DOTALL)


async def extract_answers(conv: st.Conversation, text: str | None) -> dict:
    """Records what a free-text message already answers (only questions not answered yet)."""
    d = conv.diagnosis
    if not text or not d:
        return {}
    use_area(d)
    d["last_text"] = text
    asked_open = open_question(d)
    open_qs = [q for q in kb()["questions"] if (q["id"] not in d["answers"] or q["id"] in ("q_hot_water_use", "q_scope"))
               and (not q.get("ask_only") or q["id"] == asked_open)]  # ask_only: never inferred before it's asked
    if not open_qs:
        return {}
    found = await _classify_answers(text, open_qs)
    found = {q: k for q, k in found.items() if explicit_enough(q, k, text)}
    valid = {qid: key for qid, key in found.items()
             if qid in questions() and key in questions()[qid]["answers"] and qid not in d["answers"]}
    for qid, key in found.items():  # a definite answer that contradicts an earlier one: clarify, don't overwrite
        if qid in d["answers"] and key in (questions().get(qid) or {}).get("answers", {}) and key != d["answers"][qid]:
            record(conv, qid, key)
    open_q = open_question(d)
    if not is_hot_water() and open_q in valid and valid[open_q] != "no" \
            and "no" in (questions().get(open_q) or {}).get("answers", {}) and SELF_CONTRA_RE.search(text):
        # "No, only the sink. Although when I flush, it comes up in the shower": both in one message, clarify
        d["answers"][open_q] = "no"
        d.setdefault("conflicts", {})[open_q] = valid.pop(open_q)
    d["answers"].update(valid)
    if open_q in valid:  # the answer to the open question is explicit (a later inference can't flip it)
        d.setdefault("explicit", []).append(open_q)
    if valid:
        log.info("extracted from free text: %s", valid)
    return valid


# ------------------------------------------------------------------ answers (taps or mapped free text)
async def on_answer(contact, qid: str, key: str) -> None:
    from . import loop

    conv = st.conversation(be.attr(contact, "id"))
    if not conv.diagnosis:
        start(conv, None)
    d = conv.diagnosis
    use_area(d)
    d["turn"] = d.get("turn", 0) + 1  # a tap is a new turn
    if qid == SAFETY_QID:
        d["safety_done"] = True
        if key == "yes":
            await conclude(contact, conv, "gas_smell", 1.0, "Resident reports a gas smell (safety question).")
            return
        if open_question(d):  # a late "no gas" while another question is open: keep it open
            await out.text(contact, conv.case_id, "Thanks, noted.")
            return
        if await apply_centrix_shortcuts(contact, conv):
            return
        complaint = d.get("complaint") or ""
        await loop.run_tenant_turn(
            contact,
            f"[No gas smell. The resident's first message was: \"{complaint}\". Record every answer that message "
            "already gives (e.g. only the shower → q_scope=only_shower), then ask the next question.]")
        return
    record(conv, qid, key, authoritative=True)  # a tap is unambiguous
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
        await conclude(contact, conv, "planned_maintenance", 0.9, "Building notice for today in centrix.", force=True)
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
                       "A neighbour already reported the central boiler (open case in centrix).", force=True)
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


def conclusion_text(conv: st.Conversation, c: dict, translation: str | None = None,
                    override: str | None = None) -> str:
    """The cause's tenant message (or the model's translation of it), with the error code's meaning first
    if the resident hasn't heard it yet."""
    from . import error_codes

    if override:  # code-written text (escalation, neutral technician sentence); the code meaning still comes first
        d = conv.diagnosis or {}
        if conv.error_code and not d.get("code_explained") and override in NEUTRAL_TECHS:
            d["code_explained"] = True
            return code_sentence(conv) + " " + override
        return override
    own = c.get("tenant_message_de") if conv.lang == "de" else None
    if c.get("tenant_message_unconfirmed") and (conv.diagnosis or {}).get("answers", {}).get("q_radiators") != "yes":
        # the usual message states facts ("heating and hot water both off") the resident didn't give
        own = c.get("tenant_message_unconfirmed_de") if conv.lang == "de" else c["tenant_message_unconfirmed"]
        translation = None
    if translation and translation not in neutral_messages() and (conv.lang != "de" or not _looks_german(translation)):
        translation = None  # never a translated message for an English resident
    text = (translation or "").strip() or own or c["tenant_message"]
    d = conv.diagnosis or {}
    if conv.error_code and not d.get("code_explained") and (not translation or translation in neutral_messages()) \
            and c.get("outcome") != "self_help" and is_hot_water():
        d["code_explained"] = True
        text = (code_sentence(conv) if conv.lang == "de" else error_codes.resident_sentence(conv.error_code, "text")) \
            + " " + text
    return text


async def conclude(contact, conv: st.Conversation, cause_id: str, confidence: float, reasoning: str,
                   force: bool = False, translation: str | None = None, message: str | None = None,
                   trade_unknown: bool = False) -> dict:
    from . import flow

    d = conv.diagnosis or start(conv, None)
    hw = use_area(d) == HOT_WATER
    if d.get("concluded"):
        return {"ok": True, "note": "already concluded"}
    if cause_id != "gas_smell" and cause_id not in causes():
        raise ValueError(f"unknown cause {cause_id}")
    if cause_id != "gas_smell" and not force and d.get("conflicts"):
        q, new = next(iter(d["conflicts"].items()))
        raise ValueError(f"{q}: the resident said {d['answers'].get(q)} earlier and now {new}. Ask which is right "
                         "(clarify) before concluding.")
    if cause_id != "gas_smell" and not force:
        settled = decisive_self_help(d, conv.error_code)
        if settled and settled != cause_id:
            raise ValueError(f"The answers settle it: conclude with {settled}")
        missing = missing_core(d, cause_id)
        if missing:
            raise ValueError(f"{cause_id} needs answers you don't have yet ({', '.join(missing)}); ask "
                             f"{missing[0]} first (or pick a cause the answers support)")
        invented = invented_facts(d, reasoning)
        if invented:
            raise ValueError(f"Your reasoning mentions things the tenant never said ({', '.join(invented)}). "
                             "Only use answers_so_far and centrix facts.")
    if cause_id != "gas_smell" and d.get("answers") and not force:
        ranked = score(d, conv.error_code)
        mine = next((r for r in ranked if r["id"] == cause_id), None)
        best = ranked[0] if ranked else None
        likelier = best and mine and best["score"] >= mine["score"] and best["ok"] >= mine["ok"] \
            and best["unknown"] <= mine["unknown"] and _likelihood(best["id"]) < _likelihood(cause_id)
        if best and mine and best["id"] != cause_id and best["bad"] == 0 \
                and (best["ok"] >= mine["ok"] + 2 or likelier):
            raise ValueError(f"{best['id']} fits the answers at least as well ({best['ok']} vs {mine['ok']} "
                             f"signals) and is likelier; conclude with {best['id']} or ask a question that "
                             f"separates them")
        contra = contradictions(d, cause_id, conv.error_code)
        if contra and cause_id not in {r["id"] for r in score(d, conv.error_code)}:
            raise ValueError(f"{cause_id} contradicts the answers ({', '.join(contra)}); pick another cause "
                             "or ask a question")
    if hw and cause_id != "gas_smell" and missing_core(d, cause_id) and causes()[cause_id]["outcome"] == "technician" \
            and not (cause_id == "boiler_fault" and (conv.error_code or d["answers"].get("q_radiators") == "yes")):
        trade_unknown = True  # the answers don't say which trade: staff pick the company at approval
    if message is None and cause_id != "gas_smell" and (missing_core(d, cause_id) or trade_unknown):
        message = ""  # never explain a cause whose required answers are missing (e.g. 'radiators are warm')
    d["concluded"] = cause_id
    override = None
    if message is not None:  # escalation / not enough answers: no explanation of a cause we can't support
        override = message or neutral_message(conv)
    rec = diagnosis_record(conv, cause_id, confidence, reasoning)
    complaint = d.get("complaint") or ("No hot water" if hw else kb().get("title") or "Repair")
    # other areas: a case of their own (no link to the building's boiler case), the boiler only for heating jobs
    where = {} if hw else {"building_case": False,
                           "with_asset": (causes().get(cause_id) or {}).get("trade") == "heating"}
    case_type = "repair.hot_water" if hw else kb().get("case_type") or "repair.general"

    if cause_id == "gas_smell":
        sf = load_kb(HOT_WATER)["safety_first"]["if_yes"]
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
                                         type_=case_type, diagnosis=rec, **where)
            if not res.get("duplicate"):
                _store(res["case_id"], None, rec, opened=not res.get("already_open"))
            conv.step = st.SELF_HELP
        await out.text(contact, conv.case_id, conclusion_text(conv, c, translation, override))
        minutes = 2 if _demo_mode() else (c.get("follow_up_minutes") or 60)
        schedule_follow_up(contact, cause_id, minutes)
        return {"ok": True, "outcome": "self_help", "follow_up_minutes": minutes,
                "note": "Tip sent; no case dispatched. Do not send another message."}

    if outcome == "emergency":  # flooding, fire, break-in, someone stuck in the lift: safety steps first
        res = await flow.ensure_case(contact, summary=f"EMERGENCY: {c['label']}", symptoms=complaint,
                                     priority="emergency", type_=f"emergency.{d.get('area') or 'other'}",
                                     trade=c.get("trade"), diagnosis=rec, **where)
        cid = res["case_id"]
        _store(cid, c.get("trade"), rec, opened=not res.get("duplicate") and not res.get("already_open"))
        be.record_event(cid, "debye", "staff.alert", f"URGENT: {c['label']}. Safety steps sent to the tenant"
                        + (f"; {c['trade']} emergency service needed." if c.get("trade") else "."),
                        {"notify_staff": "urgent", "cause_id": cause_id, "trade": c.get("trade")})
        conv.step = st.CLOSED
        await out.text(contact, cid, conclusion_text(conv, c, translation, override))
        return {"ok": True, "outcome": "emergency", "case_id": cid,
                "note": "Safety message sent. Do not send another message."}

    if outcome == "technician":
        trade = None if trade_unknown else c.get("trade")
        type_ = "repair.hot_water" if trade_unknown else \
            "repair.heating" if trade == "heating" else f"repair.{trade or 'general'}"
        res = await flow.ensure_case(contact, summary=_title(c, conv) if not trade_unknown else "No hot water",
                                     symptoms=complaint, error_code=conv.error_code, type_=type_, trade=trade,
                                     diagnosis=rec, **({} if hw else {"priority": c.get("priority") or "normal"}),
                                     **where)
        cid = res["case_id"]
        if not res.get("duplicate"):
            _store(cid, trade, rec, opened=not res.get("already_open"))
        if res.get("duplicate"):
            await flow.send_duplicate_notice(contact, cid)
            return {"ok": True, "outcome": "technician", "case_id": cid, "duplicate": True}
        await out.text(contact, cid, conclusion_text(conv, c, translation, override))
        cs = st.case_state(cid)
        if not hw:
            cs.consent_purpose = c.get("label") or cs.consent_purpose
        cs.trade_unknown = trade_unknown
        if trade_unknown:
            be.record_event(cid, "debye", "staff.pick_trade", "Tenant wants a technician; the answers don't show "
                            "which trade. Please pick the company at approval.", {"best_guess": cause_id})
        else:
            try:
                ranking = be.rank_partners(cid)  # backend-core ranks by the case's trade
                if ranking:
                    cs.partner_id, cs.partner_name = be.attr(ranking[0], "partner_id"), be.attr(ranking[0], "name")
            except Exception:
                log.exception("rank_partners failed")
        await flow.request_consent(contact, cid)
        return {"ok": True, "outcome": "technician", "case_id": cid,
                "note": "Consent question sent. Do not send another message."}

    # caretaker / utility / management: a case for the record, no partner
    prio = {} if hw else {"priority": c.get("priority") or "normal"}
    res = await flow.ensure_case(contact, summary=_title(c, conv), symptoms=complaint, error_code=conv.error_code,
                                 type_=case_type, trade=c.get("trade"), diagnosis=rec, **prio, **where)
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
    elif outcome == "management":
        be.record_event(cid, "debye", "staff.management", f"Property manager to follow up: {c['label']}",
                        {"cause_id": cause_id, "contact_id": be.attr(contact, "id")})
    else:
        be.record_event(cid, "debye", "staff.utility_contact", f"Staff to contact the gas supplier: {c['label']}",
                        {"cause_id": cause_id})
    conv.step = st.DISPATCHED
    await out.text(contact, cid, conclusion_text(conv, c, translation, override))
    if not hw:
        from . import triage

        await triage.after_conclusion(contact, conv)  # a second problem from the first message comes next
    return {"ok": True, "outcome": outcome, "case_id": cid, "note": "Message sent. Do not send another message."}


def _title(c: dict, conv: st.Conversation) -> str:
    from . import error_codes

    if conv.error_code and is_hot_water():
        return error_codes.case_title(conv.error_code)
    if not is_hot_water():
        return f"{kb().get('title') or 'Repair'} – {c['label'][0].lower()}{c['label'][1:]}"
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
    if use_area(conv) != HOT_WATER:
        k = kb()
        q = say(conv, k.get("follow_up_question") or "just checking in: is it working again?",
                k.get("follow_up_question_de") or "kurze Nachfrage: Geht es wieder?")
        await out.buttons(contact, conv.case_id, f"Hi{' ' + name if name else ''}, {q}",
                          [Option(f"diagfu_yes:{cause_id}", (k.get("follow_up_yes") or "Yes, all good")[:20]),
                           Option(f"diagfu_no:{cause_id}", (k.get("follow_up_no") or "No, still broken")[:20])])
        return
    await out.buttons(contact, conv.case_id, f"Hi{' ' + name if name else ''}, just checking in: is the hot water back?",
                      [Option(f"diagfu_yes:{cause_id}", "Yes, all good"), Option(f"diagfu_no:{cause_id}", "Still cold")])


async def on_follow_up(contact, cause_id: str, fixed: bool) -> None:
    conv = st.conversation(be.attr(contact, "id"))
    hw = use_area(conv) == HOT_WATER
    if fixed:
        conv.step = st.CLOSED
        if conv.case_id and be.has("close_self_help"):
            try:
                be.close_self_help(conv.case_id, f"Tenant confirmed the hot water is back ({_label(cause_id)}).")
            except Exception:
                log.exception("close_self_help failed")
        await out.text(contact, conv.case_id, say(conv, "Good to hear. I'll close this then.", "Schön, dann schließe ich das hier."))
        queued = None if hw else getattr(conv, "triage", None)
        st.reset_conversation(be.attr(contact, "id"))
        if queued:
            from . import triage

            await triage.after_conclusion(contact, st.conversation(be.attr(contact, "id")), queued)
        return
    # still cold after the self-help tip: what the failure tells us is an answer; keep diagnosing
    conv.diagnosis = conv.diagnosis or start(conv, None)
    d = conv.diagnosis
    d["turn"] = d.get("turn", 0) + 1
    d["concluded"] = None
    d["facts"].append("self_help_failed")
    d.setdefault("failed_tips", []).append(cause_id)
    for qid, key in ((causes().get(cause_id) or {}).get("if_fails") or {}).items():
        d["answers"][qid] = key
    conv.step = st.DIAGNOSIS
    action, ident, conf = next_step(conv)
    if action == "ask" and len(d["asked"]) < MAX_QUESTIONS:
        await ask(contact, conv, ident, lead=say(conv, "Thanks for checking.", "Danke fürs Nachsehen."))
        return
    tech, supported = (ident, True) if action == "conclude" and causes().get(ident, {}).get("outcome") != "self_help" \
        and not missing_core(d, ident) else likeliest_technician(d, conv.error_code)
    if hw:
        await out.text(contact, conv.case_id, say(conv, "Thanks for letting me know, then I'll get a technician to look at it.", "Danke für die Rückmeldung, dann schicke ich einen Techniker."))
    await conclude(contact, conv, tech, 0.6, f"Still cold after the self-help tip for '{_label(cause_id)}'.",
                   force=True, message=None if supported else "")
