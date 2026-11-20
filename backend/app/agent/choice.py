"""Understand a free-text answer to an open question (buttons/list) and map it to an option id.

1. Fast path, no model: the number, the option's title, yes/no words, ordinals ("the first one"),
   a slot's time or weekday ("8-10", "Saturday works").
2. Model step: a small gpt-6-luna classification against the open options (strict schema,
   reasoning "none", 8 s timeout). Anything unclear → None, and the agent asks again.
The caller then runs the same deterministic handler as a tap, so nothing is confirmed to the
resident that wasn't actually recorded.
"""
from __future__ import annotations

import json
import logging
import os
import re

from app.channels.base import Option

log = logging.getLogger("debye.choice")

YES = {"yes", "y", "yeah", "yep", "yup", "sure", "ok", "okay", "k", "fine", "go ahead", "yes go ahead",
       "yes please", "please do", "of course", "sounds good", "do it", "alright", "all right", "absolutely",
       "ja", "klar", "gerne", "ja gerne", "passt", "okey", "si", "sí", "oui", "igen", "da", "jo"}
NO = {"no", "n", "nope", "nah", "no thanks", "rather not", "id rather not", "i'd rather not", "dont", "don't",
      "please dont", "please don't", "not now", "nein", "lieber nicht", "nee", "non", "nem", "ne"}
ORDINALS = {"first": 0, "1st": 0, "the first": 0, "the first one": 0, "first one": 0, "erste": 0, "ersten": 0,
            "second": 1, "2nd": 1, "the second": 1, "the second one": 1, "second one": 1, "zweite": 1, "zweiten": 1,
            "third": 2, "3rd": 2, "the third": 2, "third one": 2, "dritte": 2,
            "last": -1, "the last one": -1, "last one": -1}
WEEKDAYS = {"mon": ("monday", "montag", "mo"), "tue": ("tuesday", "dienstag", "di"),
            "wed": ("wednesday", "mittwoch", "mi"), "thu": ("thursday", "donnerstag", "do"),
            "fri": ("friday", "freitag", "fr"), "sat": ("saturday", "samstag", "sa"),
            "sun": ("sunday", "sonntag", "so")}

_YES_PREFIXES = ("consent_yes:", "fixed_yes:")
_NO_PREFIXES = ("consent_no:", "fixed_no:")


def _norm(text: str) -> str:
    t = text.strip().lower()
    t = re.sub(r"[\U0001F300-\U0001FAFF☀-➿👍👌🙏]", " ", t)  # emoji
    t = re.sub(r"[.!?,;:)(\"']", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _hours(text: str) -> list[str]:
    return re.findall(r"\d{1,2}", text)


def fast_match(text: str | None, options: list[Option]) -> Option | None:
    if not text or not options:
        return None
    t = _norm(text)
    if not t:
        return None
    is_question = text.strip().endswith("?")
    if t.isdigit() and 1 <= int(t) <= len(options):
        return options[int(t) - 1]
    for o in options:
        if _norm(o.title) == t:
            return o
    if t in ORDINALS:
        real = [o for o in options if not o.id.startswith("slot_none:")]
        i = ORDINALS[t]
        if real and -len(real) <= i < len(real):
            return real[i]
    words = set(t.split())
    if is_question:
        words = set()  # "is it ok if ...?" is not a yes
    if not is_question and t in YES or (words & {"yes", "sure", "ok", "okay", "ja", "klar"} and not words & {"no", "not", "nein", "nicht"}):
        hit = next((o for o in options if o.id.startswith(_YES_PREFIXES) or o.id.endswith(":yes")), None)
        if hit:
            return hit
    if not is_question and (t in NO or t.startswith(("no ", "nein "))):
        hit = next((o for o in options if o.id.startswith(_NO_PREFIXES) or o.id.endswith(":no")), None)
        if hit:
            return hit
    # slots: "8-10", "8 to 10", "Saturday works", "Sat"
    slots = [o for o in options if o.id.startswith("slot_") and not o.id.startswith("slot_none:")]
    if slots:
        hours = _hours(t)
        if hours:
            m = [o for o in slots if hours[:2] == _hours(o.title)[: len(hours[:2])] or
                 (len(hours) >= 2 and hours[:2] == _hours(o.title)[-2:])]
            if len(m) == 1:
                return m[0]
        for short, names in WEEKDAYS.items():
            if any(re.search(rf"\b{n}\b", t) for n in (short, *names)):
                m = [o for o in slots if re.search(rf"\b({short}|{'|'.join(names)})\b", o.title.lower())]
                if len(m) == 1:
                    return m[0]
    return None


async def model_match(text: str, options: list[Option], question: str | None = None) -> Option | None:
    """gpt-6-luna classification; None when unsure, no key or any error."""
    if not os.getenv("OPENAI_API_KEY") or (os.getenv("LLM_PROVIDER") or "openai").lower() != "openai":
        return None
    try:
        from openai import AsyncOpenAI

        from app.media import openai_base_url

        ids = [o.id for o in options] + ["none"]
        schema = {"type": "object", "additionalProperties": False, "required": ["choice"],
                  "properties": {"choice": {"type": "string", "enum": ids}}}
        listing = "\n".join(f"- {o.id}: {o.title}" for o in options)
        extra = {}
        effort = os.getenv("OPENAI_REASONING_EFFORT")
        effort = "none" if effort is None else effort
        if effort:
            extra["reasoning_effort"] = effort
        client = AsyncOpenAI(base_url=openai_base_url(), timeout=8, max_retries=0)
        r = await client.chat.completions.create(
            model=os.getenv("OPENAI_CHAT_MODEL") or "gpt-6-luna",
            messages=[
                {"role": "system", "content": "A resident answered a WhatsApp question in free text (any language). "
                 "If the answer addresses the question, pick the closest option, even when it isn't worded like "
                 "it (e.g. only the shower / hot water / one radiator affected → the 'just one / some' option; "
                 "'every one is freezing' → the 'all' option; 'neither, I'm away' → the 'none of these' option). "
                 "Pick 'none' only if the resident asks something back, is unsure, or talks about something else. "
                 "Consent is special: pick a yes/consent option only for a clear yes."},
                {"role": "user", "content": f"Question: {question or '(see options)'}\nOptions:\n{listing}\n\n"
                 f"Resident's answer: {text}"},
            ],
            response_format={"type": "json_schema",
                             "json_schema": {"name": "choice", "strict": True, "schema": schema}},
            **extra,
        )
        msg = r.choices[0].message
        if getattr(msg, "refusal", None) or not msg.content:
            return None
        choice = json.loads(msg.content).get("choice")
        return next((o for o in options if o.id == choice), None)
    except Exception:
        log.exception("choice classification failed")
        return None


async def match(text: str | None, options: list[Option], question: str | None = None) -> Option | None:
    if not text or not options:
        return None
    hit = fast_match(text, options)
    if hit is not None:
        return hit
    return await model_match(text, options, question)
