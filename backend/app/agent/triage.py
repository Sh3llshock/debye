"""Triage: which household problem is this, and which diagnosis runs (docs/diagnosis.md, data/diagnosis/*.json).

A new report goes through route() before anything else:
  1. emergencies from the tenant's words (flooding, a burning smell or sparks, fire or smoke, a CO alarm,
     a break-in, someone trapped in the lift, the whole building dark): safety steps at once, no question;
  2. the area, from the KB router keywords (and one structured LLM call when the words are ambiguous);
     hot water and heating stay on their existing paths (route returns None);
  3. no area but clearly a problem ("something's broken"): one area question as a list;
  4. two problems in one message ("the tap drips and the window won't close"): the first is diagnosed,
     the second is queued and started by after_conclusion() once the first is settled.
Every area runs the same engine (agent/diagnosis.py) with its own KB.
"""
from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache

from app.channels.base import Option

from . import _backend as be
from . import diagnosis as dg
from . import outbound as out
from . import state as st

log = logging.getLogger("debye.triage")

HOT_WATER = dg.HOT_WATER
HEATING = "heating"  # radiators: the existing agent flow (ask_cold, the building's boiler case)
PASSTHROUGH = (HOT_WATER, HEATING)

# ------------------------------------------------------------------ emergencies (never asked, read from the words)
_NOT_ALARM = r"(?!\s*(alarm|detector|melder))"
EMERGENCIES: tuple[tuple[str, str, dict, re.Pattern], ...] = (
    # (area, cause, answers/facts to record, pattern)
    ("other", "co_alarm", {"fact": "co_alarm"}, re.compile(
        r"\b(carbon monoxide|co[- ]?(alarm|detector|melder|warner)|kohlenmonoxid)", re.I)),
    ("other", "fire_smoke", {"fact": "fire_smoke"}, re.compile(
        r"\b(on fire|fire in|there'?s a fire|flames?|(thick |black )?smoke" + _NOT_ALARM + r" (is )?(coming|everywhere|"
        r"in the|pouring|from the (kitchen|hallway|stairwell|flat))|es brennt|feuer|flammen|rauch" + _NOT_ALARM
        + r" (kommt|im|überall))", re.I)),
    ("electrics", "electrical_burning", {"fact": "burning_smell"}, re.compile(
        r"\b(burning smell|smell(s|ing)? (of |like )?burn(ing|t)|smells? burnt|spark(s|ed|ing)|melt(ed|ing) "
        r"(socket|plug|outlet|switch|cable)|smok(e|ing) (from|out of|coming out of) (the |a |my )?(socket|outlet|plug|"
        r"switch|fuse ?box|cable)|brandgeruch|riecht (verbrannt|verschmort|nach verbranntem)|verschmort|funken|"
        r"steckdose (qualmt|raucht))", re.I)),
    ("windows_doors", "break_in", {"fact": "break_in"}, re.compile(
        r"\b(broke(n)? into|break-?in|burglar(s|y|ized)?|burgled|robbed|(door|lock) (was |has been )?(forced|kicked "
        r"in|pried)|forced (open|the door|the lock)|einbruch|eingebrochen|aufgebrochen)", re.I)),
    ("lift", "person_trapped", {"li_state": "someone_trapped"}, re.compile(
        r"\b((i'?m|i am|we'?re|we are|someone|somebody|people|(my|a) \w+|he|she|they)( is| are|'s)? (stuck|trapped|"
        r"locked) in (the |a )?(lift|elevator)|stuck in (the |a )?(lift|elevator)|(im |in dem )?(aufzug|fahrstuhl) "
        r"(stecken|feststecken|eingeschlossen|steckt jemand|gefangen)|steck(e|en|t) im (aufzug|fahrstuhl))", re.I)),
    ("water_leak", "major_leak_flooding", {"lk_amount": "spreading"}, re.compile(
        r"\b(burst pipe|pipe (has |just )?burst|flood(ing|ed)|water (is )?(spreading|everywhere|pouring|gushing|"
        r"spraying)|spreading (all )?(over|across)|rohrbruch|überschwemm|wasser (läuft|steht|spritzt) überall|"
        r"alles (steht )?unter wasser)", re.I)),
)
_POWER_RE = re.compile(r"\b(power|electricity|lights?|strom|licht|blackout|stromausfall)", re.I)
_BUILDING_DARK_RE = re.compile(
    r"\b((whole|entire) (building|street|block|house|neighbou?rhood)|stairwell( is)? (dark|too)|neighbou?rs?\b.{0,25}"
    r"\b(no power|dark|out|too|as well)|(ganze[sn]?|gesamte[sn]?) (haus|straße|gebäude)|treppenhaus( ist)?( auch)? "
    r"dunkel|nachbarn\b.{0,25}\b(auch|kein strom))", re.I)
_CEILING_RE = re.compile(r"\b(s?c[ei]{1,3}l+i?n?g|from above|upstairs|decke|von oben)", re.I)  # ceeling, cieling


def emergency_from_text(text: str | None) -> tuple[str, str, dict] | None:
    """(area, cause_id, answers) when the words alone describe an emergency, else None."""
    if not text:
        return None
    for area, cause, rec, rx in EMERGENCIES:
        if rx.search(text):
            if cause == "major_leak_flooding" and _CEILING_RE.search(text) and "burst" not in text.lower():
                continue  # water through the ceiling is the roof/ceiling KB (caretaker / roofer), asked first
            return area, cause, rec
    if _POWER_RE.search(text) and _BUILDING_DARK_RE.search(text):
        return "electrics", "building_power_outage", {"el_scope": "building"}
    return None


# ------------------------------------------------------------------ areas from the words
HOT_WATER_STRONG_RE = re.compile(
    r"\b(hot water|warm water|lukewarm|no hot|(shower|water)( is| 's|'s)? (cold|freezing|not (hot|warm))|cold shower|"
    r"warmwasser|warmes wasser|lauwarm|kein(e|en)? warm|dusche (ist |bleibt )?kalt|kalt duschen|ho?t ?wa?te?r|no hw|"
    r"(shower|taps?|sinks?)\b[^.!?]{0,25}\b(runs? |is |are |stays? |goes |only )*(cold|freezing|lukewarm)|"
    r"dusche\b[^.!?]{0,25}\bkalt)",
    re.I)
HEATING_RE = re.compile(
    r"\b(radiators?|heating|heater|heizung|heizkörper|heizt nicht|flat is (cold|freezing)|wohnung (ist )?kalt)", re.I)
_LEAK_RE = re.compile(r"\b(leak|drip|water (under|on the floor|everywhere)|undicht|tropft|ausläuft|pfütze)", re.I)
WEAK_WORDS = {"broken", "loose", "kaputt", "locker", "pay", "bill", "floor", "boden", "light", "lights", "door",
              "window", "fenster", "tür", "water", "wasser", "noise", "loud", "laut", "shower", "dusche", "toilet"}
SECOND_PROBLEM_RE = re.compile(
    r"\b(and also|also|plus|another (thing|problem|issue)|on top of that|as well as|separately|other thing|"
    r"außerdem|zusätzlich|und auch|noch (was|etwas)|ein anderes problem|ein weiteres problem)\b", re.I)
_GAS_APPLIANCE_RE = re.compile(r"\b(gas )?(stove|hob|cooker|herd|gasherd)\b", re.I)  # a hot-water clue, not a 2nd problem
PROBLEM_RE = re.compile(
    r"\b(broken|not working|isn'?t working|is not working|doesn'?t work|does not work|won'?t|can'?t|stopped|problem|issue|help|repair|fix|damaged|"
    r"faulty|stuck|leak|kaputt|funktioniert nicht|geht nicht|defekt|reparatur|problem|hilfe|beschädigt)", re.I)
MENU_AREAS = ("water_leak", "blocked_drain", "electrics", "windows_doors", "appliances", "mold_damp", "management",
              "other")  # plus hot water and heating: 10 rows, the WhatsApp list maximum


@lru_cache(maxsize=1)
def kb_areas() -> tuple[str, ...]:
    """Areas with a KB of their own (everything except hot water)."""
    return tuple(a for a in dg.areas() if a != HOT_WATER and dg.load_kb(a).get("router"))


@lru_cache(maxsize=None)
def _keyword_patterns(area: str) -> tuple[tuple[re.Pattern, float], ...]:
    pats = []
    for kw in dg.load_kb(area)["router"].get("keywords") or []:
        k = kw.lower().strip()
        weight = 0.3 if k in WEAK_WORDS else (2.0 if " " in k else 1.0)
        # short single words only with an English ending ('lock' → locks/locked, never German 'locker')
        tail = r"(?:s|es|ed|ing)?(?!\w)" if " " not in k and len(k) <= 5 else ""
        pats.append((re.compile(r"(?<![\w])" + re.escape(k) + tail, re.I), weight))
    return tuple(pats)


def _hits(area: str, text: str) -> list[tuple[int, float]]:
    """(position, weight) of every keyword of the area in the text."""
    out_ = []
    for rx, w in _keyword_patterns(area):
        out_.extend((m.start(), w) for m in rx.finditer(text))
    return out_


def scores(text: str | None) -> dict[str, float]:
    """Keyword score per area (hot water and heating included), highest first."""
    t = text or ""
    s: dict[str, float] = {}
    for a in kb_areas():
        hits = _hits(a, t)
        if hits:
            s[a] = round(sum(w for _, w in hits), 2)
    if "water_leak" in s and "appliances" in s and _LEAK_RE.search(t):
        s["water_leak"] += 1.5  # "the washing machine is leaking": the hose/valve, the leak KB covers it
    if HOT_WATER_STRONG_RE.search(t):
        s[HOT_WATER] = s.get(HOT_WATER, 0) + 2.0
    elif dg.applies(t) and not s:
        s[HOT_WATER] = 1.0  # "my boiler", "the shower": hot water only when nothing else fits
    if HEATING_RE.search(t):
        s[HEATING] = s.get(HEATING, 0) + 1.5
        if "water_leak" in s and re.search(r"\b(radiator|heizkörper)\b.{0,40}\b(leak|drip|undicht|tropft)", t, re.I):
            s.pop(HEATING)  # "the radiator is leaking" is a leak, not cold heating
    return dict(sorted(s.items(), key=lambda kv: -kv[1]))


def _first_pos(area: str, text: str) -> int:
    if area == HOT_WATER:
        m = HOT_WATER_STRONG_RE.search(text) or dg.HOT_WATER_RE.search(text)
        return m.start() if m else 10 ** 6
    if area == HEATING:
        m = HEATING_RE.search(text)
        return m.start() if m else 10 ** 6
    hits = _hits(area, text)
    return min((p for p, w in hits if w >= 1), default=min((p for p, _ in hits), default=10 ** 6))


def classify_keywords(text: str | None) -> tuple[str | None, str | None, bool]:
    """(primary, second, ambiguous). second is set only when the message clearly reports two problems."""
    t = text or ""
    s = {a: v for a, v in scores(t).items() if v >= 1}
    weak = scores(t)
    if not s:
        top = next(iter(weak), None)
        return top, None, bool(top)  # only weak words ("the door", "broken"): a guess the LLM may correct
    ranked = list(s)
    if len(ranked) == 1:
        return ranked[0], None, False
    if HOT_WATER in s and HOT_WATER_STRONG_RE.search(t) and not SECOND_PROBLEM_RE.search(t)             and not any(rx.search(t) for _, _, _, rx in EMERGENCIES):
        return HOT_WATER, None, False  # "since the plumber fixed the leak, the shower only runs cold": hot water
    if HOT_WATER in s and "appliances" in s and _GAS_APPLIANCE_RE.search(t) and not SECOND_PROBLEM_RE.search(t):
        s.pop("appliances")  # "no hot water and the gas stove won't light either": the gas supply (hot-water KB)
        ranked = list(s)
        if len(ranked) == 1:
            return ranked[0], None, False
    a, b = ranked[0], ranked[1]
    if SECOND_PROBLEM_RE.search(t) and s[b] >= 1:
        first, second = sorted((a, b), key=lambda x: _first_pos(x, t))
        return first, second, False
    return a, None, s[a] - s[b] < 1


async def classify_llm(text: str) -> tuple[str | None, str | None] | None:
    """One strict structured-output call: the area of the main problem and of a second, separate one.
    None without an OpenAI key or on any error (keywords decide then)."""
    if not os.getenv("OPENAI_API_KEY") or (os.getenv("LLM_PROVIDER") or "openai").lower() != "openai":
        return None
    from openai import AsyncOpenAI

    from app.media import openai_base_url

    choices = {HOT_WATER: "No hot water or lukewarm water (shower, taps, boiler display).",
               HEATING: "Radiators or the heating are cold or not working."}
    choices.update({a: dg.load_kb(a)["router"]["description"] for a in kb_areas()})
    enum = [*choices, "unclear", "none"]
    schema = {"type": "object", "additionalProperties": False, "required": ["primary", "second"],
              "properties": {"primary": {"type": "string", "enum": enum,
                                         "description": "Area of the problem the tenant reports first; 'unclear' "
                                                        "if it is a problem but the message does not say what is "
                                                        "affected ('something is broken', 'I have a problem'); "
                                                        "'none' if it reports no problem (a greeting, thanks)."},
                             "second": {"type": "string", "enum": enum,
                                        "description": "Area of a SECOND, separate problem in the same message; "
                                                       "'none' if there is only one problem."}}}
    extra = {}
    effort = os.getenv("OPENAI_REASONING_EFFORT")
    effort = "none" if effort is None else effort
    if effort:
        extra["reasoning_effort"] = effort
    try:
        client = AsyncOpenAI(base_url=openai_base_url(), timeout=8, max_retries=0)
        r = await client.chat.completions.create(
            model=os.getenv("OPENAI_CHAT_MODEL") or "gpt-6-luna",
            messages=[{"role": "system", "content": "Sort a tenant's message to their property manager into one "
                       "area. Areas:\n" + "\n".join(f"- {k}: {v}" for k, v in choices.items())
                       + "\nPick by what is broken, not by the room. Water from the ceiling or from above is "
                       "roof_ceiling_leak, never water_leak. Tenants write with typos, slang and in German "
                       "('ceeling' = ceiling, 'toylet' = toilet, 'radiater' = radiator): read what they mean. "
                       "Never invent a second problem."},
                      {"role": "user", "content": text}],
            response_format={"type": "json_schema", "json_schema": {"name": "triage", "strict": True,
                                                                     "schema": schema}},
            **extra,
        )
        msg = r.choices[0].message
        if getattr(msg, "refusal", None) or not msg.content:
            return None
        res = json.loads(msg.content)
        primary = None if res.get("primary") in ("none", "unclear") else res.get("primary")
        second = None if res.get("second") in ("none", "unclear", primary) else res.get("second")
        return primary, second
    except Exception:
        log.exception("triage classification failed")
        return None


# ------------------------------------------------------------------ planner (a stronger model plans the diagnosis)
HOLDING_EN = "Let me look into it, one moment."
HOLDING_DE = "Ich schaue mir das kurz an, einen Moment."


def planner_enabled() -> bool:
    return os.getenv("PLANNER_ENABLED", "0").lower() in ("1", "true", "yes", "on")


def _kb_brief(area: str, detail: bool) -> dict:
    k = dg.load_kb(area)
    out = {"area": area, "what": k["router"]["description"]}
    if detail:
        out["questions"] = {q["id"]: {"text": q["text"], "answers": list(q["answers"])} for q in k["questions"]}
        out["causes"] = {c["id"]: {"label": c["label"], "signals": c["signals"], "outcome": c["outcome"]}
                         for c in k["causes"]}
        out["strategy"] = k.get("strategy")
    return out


async def plan(text: str, candidates: list[str]) -> dict | None:
    """One structured call to PLANNER_MODEL: the area, the likeliest causes (ranked) and the best 1-3 questions
    from that area's KB. None if disabled, slow or invalid (keywords and Luna decide then)."""
    if not os.getenv("OPENAI_API_KEY") or (os.getenv("LLM_PROVIDER") or "openai").lower() != "openai":
        return None
    from openai import AsyncOpenAI

    from app.media import openai_base_url

    detail = [a for a in candidates if a in kb_areas()] or list(kb_areas())
    briefs = [_kb_brief(a, a in detail) for a in kb_areas()]
    enum = [HOT_WATER, HEATING, *kb_areas(), "unclear"]
    schema = {"type": "object", "additionalProperties": False,
              "required": ["area", "likely_causes", "questions", "reason"],
              "properties": {
                  "area": {"type": "string", "enum": enum},
                  "likely_causes": {"type": "array", "items": {"type": "string"},
                                    "description": "cause ids of that area, likeliest first (max 3)"},
                  "questions": {"type": "array", "items": {"type": "string"},
                                "description": "question ids of that area to ask, best first (0-3); skip what the "
                                               "message already answers; empty if the message already decides it"},
                  "reason": {"type": "string", "description": "one sentence"}}}
    system = ("You plan how a property manager's WhatsApp assistant triages a tenant's first message. Pick the area "
              "(by what is broken, not by the room; hot water and radiators keep their own areas; 'unclear' if the "
              "message says nothing about what is affected), rank the likeliest causes of that area and pick the "
              "fewest questions (0-3, one topic each) that best separate them, cheap self-checks first. Use only ids "
              "from the knowledge below. Never invent facts.\n" + json.dumps(briefs, ensure_ascii=False))
    extra = {}
    effort = os.getenv("PLANNER_REASONING_EFFORT", "low")
    if effort and effort != "none":
        extra["reasoning_effort"] = effort
    try:
        client = AsyncOpenAI(base_url=openai_base_url(), timeout=float(os.getenv("PLANNER_TIMEOUT", "8")),
                             max_retries=0)
        r = await client.chat.completions.create(
            model=os.getenv("PLANNER_MODEL") or "gpt-6-sol",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
            response_format={"type": "json_schema", "json_schema": {"name": "plan", "strict": True, "schema": schema}},
            **extra)
        msg = r.choices[0].message
        if getattr(msg, "refusal", None) or not msg.content:
            return None
        p = json.loads(msg.content)
    except Exception:
        log.exception("triage planner failed")
        return None
    area = p.get("area")
    if area in kb_areas():
        k = dg.load_kb(area)
        qids, cids = {q["id"] for q in k["questions"]}, {c["id"] for c in k["causes"]}
        p["questions"] = [q for q in p.get("questions") or [] if q in qids][:3]
        p["likely_causes"] = [c for c in p.get("likely_causes") or [] if c in cids][:3]
    log.info("triage planner: %s", p)
    return p


async def classify(text: str | None) -> tuple[str | None, str | None]:
    """(primary area or None, queued second area or None)."""
    primary, second, ambiguous = classify_keywords(text)
    # the model decides the area (typos, slang, German); keywords are the fast path only for hot water / heating
    # (their flows are unchanged) and the fallback when the model is down
    if text and (ambiguous or primary not in PASSTHROUGH) and (primary is not None or PROBLEM_RE.search(text)):
        llm = await classify_llm(text)
        if llm is not None and llm[0] is not None:
            return llm
    return primary, second


# ------------------------------------------------------------------ state
def _t(conv: st.Conversation) -> dict:
    if conv.triage is None:
        conv.triage = {}
    return conv.triage


def label(area: str, lang: str = "en") -> str:
    if area == HOT_WATER:
        return "das Warmwasser" if lang == "de" else "the hot water"
    if area == HEATING:
        return "die Heizung" if lang == "de" else "the heating"
    k = dg.load_kb(area)
    return (k.get("label_de") if lang == "de" else k.get("label")) or ("das Problem" if lang == "de" else "the problem")


def _menu() -> list[Option]:
    rows = [Option(f"triage:{HOT_WATER}", "Hot water"), Option(f"triage:{HEATING}", "Heating / radiators")]
    for a in MENU_AREAS:
        if a in kb_areas():
            rows.append(Option(f"triage:{a}", dg.load_kb(a)["router"]["button"][:24]))
    return rows[:10]


def _menu_de() -> list[Option]:
    rows = [Option(f"triage:{HOT_WATER}", "Warmwasser"), Option(f"triage:{HEATING}", "Heizung")]
    for a in MENU_AREAS:
        if a in kb_areas():
            r = dg.load_kb(a)["router"]
            rows.append(Option(f"triage:{a}", (r.get("button_de") or r["button"])[:24]))
    return rows[:10]


# ------------------------------------------------------------------ entry points
async def route(contact, conv: st.Conversation, text: str | None, images: list[str] | None = None) -> bool | None:
    """A message before any case or diagnosis exists. Returns None when the existing paths should handle it
    (hot water, heating, a greeting), else the 'interrupted' flag of the turn it started."""
    if not text:
        return None
    t = _t(conv)
    em = emergency_from_text(text)
    if em:
        return await start_emergency(contact, conv, text, *em)
    if t.get("asked"):  # the answer to "what is it about?" (typed instead of tapped)
        return await on_area_text(contact, conv, text, images)
    kw_primary, kw_second, ambiguous = classify_keywords(text)
    the_plan = None
    if planner_enabled() and (kw_primary not in PASSTHROUGH or ambiguous) \
            and (kw_primary is not None or PROBLEM_RE.search(text)):
        # a stronger model picks the area and plans the questions; the resident sees a holding message meanwhile
        await out.text(contact, None, HOLDING_DE if conv.lang == "de" else HOLDING_EN)
        the_plan = await plan(text, [a for a in scores(text) if a not in PASSTHROUGH][:3])
    if the_plan and the_plan.get("area") == "unclear" and not kw_second:
        await ask_area(contact, conv, text)
        return False
    if the_plan and the_plan.get("area") in (*PASSTHROUGH, *kb_areas()):
        primary, second = the_plan["area"], kw_second if kw_second != the_plan["area"] else None
    else:
        primary, second = await classify(text)
    if primary is None:
        if PROBLEM_RE.search(text) and not dg.applies(text):
            await ask_area(contact, conv, text)
            return False
        return None  # "hi", "thanks": the agent answers
    if primary in PASSTHROUGH and second and second not in PASSTHROUGH:
        primary, second = second, primary  # an area with its own KB first; hot water / heating after it
    if second:
        t["queued"] = {"area": second, "text": text}
    t["area"] = primary
    if primary in PASSTHROUGH:
        return None  # hot water: diagnosis.begin in the router; heating: the agent's existing flow
    return await begin_area(contact, conv, primary, text, images,
                            plan_=the_plan if the_plan and the_plan.get("area") == primary else None)


async def start_emergency(contact, conv: st.Conversation, text: str, area: str, cause: str, rec: dict) -> bool:
    """Safety steps at once (the KB's tenant_message), staff alerted, an emergency case. No question first."""
    log.info("triage: emergency %s/%s from %r", area, cause, text[:60])
    if not conv.diagnosis or conv.diagnosis.get("concluded") or dg.area_of(conv) != area:
        dg.start(conv, text, area)
    d = conv.diagnosis
    d["safety_done"] = True
    _t(conv)["area"] = area
    for k, v in rec.items():
        if k == "fact":
            d["facts"].append(v)
        else:
            d["answers"][k] = v
            d.setdefault("explicit", []).append(k)
    conv.tenant_texts.append(text)
    await dg.conclude(contact, conv, cause, 0.95, f"Emergency in the tenant's words: \"{text[:120]}\"", force=True)
    return False


async def ask_area(contact, conv: st.Conversation, text: str) -> None:
    """'Something is broken': one question, which area (a list; typed answers are understood too)."""
    t = _t(conv)
    t["asked"] = True
    t["complaint"] = text
    conv.tenant_texts.append(text)
    de = conv.lang == "de"
    await out.list_(contact, None,
                    "Okay. Worum geht es?" if de else "Ok. What is it about?",
                    "Auswählen" if de else "Choose", _menu_de() if de else _menu(),
                    "Bereich" if de else "Area")


async def on_area_text(contact, conv: st.Conversation, text: str, images: list[str] | None = None) -> bool | None:
    t = _t(conv)
    complaint = f"{t.get('complaint') or ''}\n{text}".strip()
    area, _second = await classify(text)
    if area is None and conv.pending_options:
        from . import choice

        opt = await choice.match(text, conv.pending_options, conv.pending_question)
        if opt is not None and opt.id.startswith("triage:"):
            area = opt.id.partition(":")[2]
    if area is None:
        area, _second = await classify(complaint)
    return await chose_area(contact, conv, area or "other", complaint, images)


async def on_button(contact, area: str) -> bool:
    """A tap on the area list (triage:<area>)."""
    conv = st.conversation(be.attr(contact, "id"))
    conv.pending_options, conv.pending_question = [], None
    t = _t(conv)
    complaint = t.get("complaint") or ""
    if area not in (*PASSTHROUGH, *kb_areas()):
        area = "other"
    await chose_area(contact, conv, area, complaint, None, tapped=True)
    return True


async def chose_area(contact, conv: st.Conversation, area: str, complaint: str, images: list[str] | None,
                     tapped: bool = False) -> bool:
    from . import loop

    t = _t(conv)
    t["asked"] = False
    t["area"] = area
    conv.pending_options, conv.pending_question = [], None
    if area == HOT_WATER:
        return bool(await dg.begin(contact, conv, complaint or "No hot water", images))
    if area == HEATING:
        return bool(await loop.run_tenant_turn(
            contact, f"[The resident says the problem is the heating: \"{complaint}\". Continue with the heating flow.]"))
    return await begin_area(contact, conv, area, complaint, images)


async def begin_area(contact, conv: st.Conversation, area: str, complaint: str | None,
                     images: list[str] | None = None, plan_: dict | None = None, lead: str | None = None) -> bool:
    """Same start as hot water (diagnosis.begin): record what the first message says, then the model asks the
    one best question of the area's KB (following the planner's plan, if any) or concludes."""
    from . import loop

    dg.start(conv, complaint, area)
    d = conv.diagnosis
    d["safety_done"] = True
    if plan_:
        d["plan"] = {"likely_causes": plan_.get("likely_causes") or [], "questions": plan_.get("questions") or [],
                     "reason": plan_.get("reason")}
    _t(conv)["area"] = area
    if complaint and complaint not in conv.tenant_texts:
        conv.tenant_texts.append(complaint)
    await dg.extract_answers(conv, complaint)
    if complaint and dg.FRUSTRATED_RE.search(complaint):
        await dg.escalate_now(contact, conv, complaint)
        return False
    settled = dg.decisive_self_help(d, conv.error_code)
    if settled:
        await dg.conclude(contact, conv, settled, 0.85, "Decisive first message: "
                          + ", ".join(f"{q}={k}" for q, k in d["answers"].items()), force=True)
        return False
    k = dg.kb()
    return bool(await loop.run_tenant_turn(
        contact,
        f"[New report, area {area} ({k.get('title') or k.get('symptom')}): \"{complaint}\". Record every answer this "
        "message already gives, then ask the one question that best splits the likeliest causes, or conclude if it's "
        "already clear." + (" Follow <diagnosis>.plan: its questions in order (skip answered ones), its causes "
                            "likeliest first." if d.get("plan") else "")
        + (f" The resident corrected the area: use lead_in \"{lead}\" and don't repeat earlier questions." if lead else "")
        + "]", images))


async def after_conclusion(contact, conv: st.Conversation, queued_from: dict | None = None) -> None:
    """The first problem is settled (tip confirmed, caretaker told, consent answered): start the queued second one."""
    t = queued_from if queued_from is not None else (conv.triage or {})
    q = t.pop("queued", None) if t else None
    if not q:
        return
    conv = st.conversation(be.attr(contact, "id"))
    area, text = q["area"], q.get("text") or ""
    if conv.diagnosis and not conv.diagnosis.get("concluded") and dg.area_of(conv) != area:
        return  # something else is running already
    conv.case_id = None  # the second problem gets a case of its own
    conv.step = st.NEW
    conv.diagnosis = None
    conv.triage = {"area": area, "second": True}
    de = conv.lang == "de"
    await out.text(contact, None, f"Jetzt kümmere ich mich um {label(area, 'de')}." if de else f"Now to {label(area)}.")
    log.info("triage: starting the queued second problem (%s)", area)
    if area == HEATING:
        from . import loop

        await loop.run_tenant_turn(contact, f"[Second problem from the resident's first message: \"{text}\". Handle "
                                            "the heating problem now; the other one is already dealt with.]")
        return
    if area == HOT_WATER:
        await dg.begin(contact, conv, text)
        return
    await begin_area(contact, conv, area, text)



# ------------------------------------------------------------------ re-route mid-conversation, escape option
REJECT_RE = re.compile(
    r"\b(i (already )?said|i told you|already (said|told)|none of (these|those|them)|neither|not (that|any of)|"
    r"something else|nothing like that|wrong|no,? it'?s (the|my|from)|it'?s (coming )?from (the )?|"
    r"hab(e)? ich (doch )?(schon )?gesagt|nichts davon|keins davon|keine davon|etwas anderes|was anderes)", re.I)
MAX_REROUTES = 2


async def reroute_llm(current: str, question: str | None, complaint: str, reply: str) -> str | None:
    """Does the reply say the problem belongs to another area? The new area, or None (stay)."""
    if not os.getenv("OPENAI_API_KEY") or (os.getenv("LLM_PROVIDER") or "openai").lower() != "openai":
        return None
    from openai import AsyncOpenAI

    from app.media import openai_base_url

    choices = {HOT_WATER: "No hot water or lukewarm water.", HEATING: "Radiators or the heating are cold."}
    choices.update({a: dg.load_kb(a)["router"]["description"] for a in kb_areas()})
    schema = {"type": "object", "additionalProperties": False, "required": ["area"],
              "properties": {"area": {"type": "string", "enum": [*choices, "same"],
                                      "description": "the area the problem really belongs to; 'same' if the reply "
                                                     "fits the current area (an answer, 'I don't know', small talk)"}}}
    try:
        client = AsyncOpenAI(base_url=openai_base_url(), timeout=6, max_retries=0)
        r = await client.chat.completions.create(
            model=os.getenv("OPENAI_CHAT_MODEL") or "gpt-6-luna",
            messages=[{"role": "system", "content": "A tenant reported a problem; the assistant sorted it into area "
                       f"'{current}' and asked: \"{question or ''}\". Decide from the tenant's reply whether the "
                       "problem belongs to another area (they correct the assistant, reject the options, or say "
                       "where it really comes from). Tenants write with typos ('ceeling' = ceiling). Water from the "
                       "ceiling or from above is roof_ceiling_leak. Areas:\n"
                       + "\n".join(f"- {k}: {v}" for k, v in choices.items())},
                      {"role": "user", "content": f"First message: {complaint}\nReply: {reply}"}],
            response_format={"type": "json_schema", "json_schema": {"name": "reroute", "strict": True,
                                                                     "schema": schema}},
            **({"reasoning_effort": os.getenv("OPENAI_REASONING_EFFORT") or "none"}
               if (os.getenv("OPENAI_REASONING_EFFORT") or "none") else {}))
        area = json.loads(r.choices[0].message.content or "{}").get("area")
    except Exception:
        log.exception("triage re-route failed")
        return None
    return None if area in (None, "same", current) else area


def _reroute_trigger(conv: st.Conversation, text: str) -> bool:
    if REJECT_RE.search(text):
        return True
    cur = dg.area_of(conv)
    other = {a: v for a, v in scores(text).items() if a != cur and v >= 1}
    return bool(other) or bool(_CEILING_RE.search(text) and cur != "roof_ceiling_leak")


async def maybe_reroute(contact, conv: st.Conversation, text: str | None, force: bool = False) -> bool:
    """During a diagnosis of another area: 'I said the ceiling', 'none of these', 'it comes from upstairs'.
    Switch to the right area (the first message plus this reply as the complaint) instead of asking again."""
    d = conv.diagnosis or {}
    cur = dg.area_of(conv)
    if not text or not d or d.get("concluded") or cur == HOT_WATER or conv.case_id:
        return False
    t = _t(conv)
    if t.get("reroutes", 0) >= MAX_REROUTES or not (force or _reroute_trigger(conv, text)):
        return False
    q = dg.open_question(d)
    qtext = (dg.questions().get(q) or {}).get("text") if q else None
    complaint = d.get("complaint") or ""
    new = await reroute_llm(cur, qtext, complaint, text)
    if new is None and not os.getenv("OPENAI_API_KEY"):  # model down: keywords
        kw = [a for a, v in scores(text).items() if a != cur and v >= 1]
        new = kw[0] if kw else ("roof_ceiling_leak" if _CEILING_RE.search(text) and cur != "roof_ceiling_leak" else None)
    if not new:
        return False
    log.info("triage: re-routing %s -> %s after %r", cur, new, text[:60])
    t["reroutes"] = t.get("reroutes", 0) + 1
    t["area"] = new
    conv.pending_options, conv.pending_question = [], None
    merged = f"{complaint}\n{text}".strip()
    if new in PASSTHROUGH:
        conv.diagnosis = None
        if new == HOT_WATER:
            await dg.begin(contact, conv, merged)
        else:
            from . import loop

            await loop.run_tenant_turn(contact, f"[The resident's problem is the heating: \"{merged}\".]")
        return True
    lead = "Verstanden." if conv.lang == "de" else "Got it, sorry."
    await begin_area(contact, conv, new, merged, lead=lead)
    return True


async def on_escape(contact, qid: str) -> None:
    """'Something else' tapped on a question's options: re-route if the problem is elsewhere, else unknown."""
    conv = st.conversation(be.attr(contact, "id"))
    d = conv.diagnosis or {}
    if await maybe_reroute(contact, conv, f"none of these options fit: {d.get('last_text') or ''}", force=True):
        return
    from . import loop

    d.setdefault("dont_know", []).append(qid)
    await loop.run_tenant_turn(contact, f"[None of the options for {qid} fit; record_answer({qid}, 'unknown') and "
                                        "continue with the next question or conclude.]")
