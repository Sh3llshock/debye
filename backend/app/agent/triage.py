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
_CEILING_RE = re.compile(r"\b(ceiling|from above|upstairs|decke|von oben)", re.I)


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
    r"warmwasser|warmes wasser|lauwarm|kein(e|en)? warm|dusche (ist |bleibt )?kalt|kalt duschen|ho?t ?wa?te?r|no hw)",
    re.I)
HEATING_RE = re.compile(
    r"\b(radiators?|heating|heater|heizung|heizkörper|heizt nicht|flat is (cold|freezing)|wohnung (ist )?kalt)", re.I)
_LEAK_RE = re.compile(r"\b(leak|drip|water (under|on the floor|everywhere)|undicht|tropft|ausläuft|pfütze)", re.I)
WEAK_WORDS = {"broken", "loose", "kaputt", "locker", "pay", "bill", "floor", "boden", "light", "lights", "door",
              "window", "fenster", "tür", "water", "wasser", "noise", "loud", "laut", "shower", "dusche", "toilet"}
SECOND_PROBLEM_RE = re.compile(
    r"\b(and also|also|plus|another (thing|problem|issue)|on top of that|as well as|separately|other thing|"
    r"außerdem|zusätzlich|und auch|noch (was|etwas)|ein anderes problem)\b|\band\b|\bund\b|[.;!?]\s+\S", re.I)
PROBLEM_RE = re.compile(
    r"\b(broken|not working|doesn'?t work|does not work|won'?t|can'?t|stopped|problem|issue|help|repair|fix|damaged|"
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
        pats.append((re.compile(r"(?<![\w])" + re.escape(k), re.I), weight))
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
    enum = [*choices, "none"]
    schema = {"type": "object", "additionalProperties": False, "required": ["primary", "second"],
              "properties": {"primary": {"type": "string", "enum": enum,
                                         "description": "Area of the problem the tenant reports first; 'none' if "
                                                        "the message reports no problem at all (a greeting, thanks)."},
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
                       + "\nPick by what is broken, not by the room. Never invent a second problem."},
                      {"role": "user", "content": text}],
            response_format={"type": "json_schema", "json_schema": {"name": "triage", "strict": True,
                                                                     "schema": schema}},
            **extra,
        )
        msg = r.choices[0].message
        if getattr(msg, "refusal", None) or not msg.content:
            return None
        res = json.loads(msg.content)
        primary = None if res.get("primary") == "none" else res.get("primary")
        second = None if res.get("second") in ("none", primary) else res.get("second")
        return primary, second
    except Exception:
        log.exception("triage classification failed")
        return None


async def classify(text: str | None) -> tuple[str | None, str | None]:
    """(primary area or None, queued second area or None)."""
    primary, second, ambiguous = classify_keywords(text)
    if text and (ambiguous or primary is None) and (primary is not None or PROBLEM_RE.search(text)):
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
    return await begin_area(contact, conv, primary, text, images)


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
                     images: list[str] | None = None) -> bool:
    """Same start as hot water (diagnosis.begin): record what the first message says, then the model asks the
    one best question of the area's KB or concludes."""
    from . import loop

    dg.start(conv, complaint, area)
    d = conv.diagnosis
    d["safety_done"] = True
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
        "already clear.]", images))


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
    await out.text(contact, None, f"Jetzt zu {label(area, 'de')}." if de else f"Now to {label(area)}.")
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

