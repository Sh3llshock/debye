"""Experimental diagnosis planner (OFF by default: PLANNER_ENABLED=1 turns it on).

On the tenant's first hot-water message Debye sends a short holding message, then a stronger model
(PLANNER_MODEL, default gpt-6-sol, same EU OpenAI endpoint and key) reads the first message, the
centrix context (unit, boiler, error codes, open cases) and the KB, and returns a structured plan:
ranked candidate causes with probabilities, the best next 1-3 questions in order (with which answer
rules which cause in or out), self-help to try, and when to stop. The plan is stored in
conv.diagnosis["plan"] and shown to Luna every turn as guidance; Luna still runs the conversation
and the tools, and the code guards still apply. One re-plan is allowed when an answer contradicts
the plan or the tenant volunteers something the plan didn't expect.
"""
from __future__ import annotations

import json
import logging
import os
import time

log = logging.getLogger("debye.planner")

HOLDING = ("Let me look into it, one moment.", "Ich schaue mir das kurz an, einen Moment.")


def enabled() -> bool:
    return (os.getenv("PLANNER_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")


def model() -> str:
    return os.getenv("PLANNER_MODEL") or "gpt-6-sol"


def _schema(kb: dict) -> dict:
    cause_ids = [c["id"] for c in kb["causes"]] + ["gas_smell"]
    q_ids = [q["id"] for q in kb["questions"] if q.get("ask", True)]
    obj = lambda props: {"type": "object", "additionalProperties": False,  # noqa: E731
                         "properties": props, "required": list(props)}
    return obj({
        "causes": {"type": "array", "description": "the likeliest causes, most likely first (max 5)",
                   "items": obj({"id": {"type": "string", "enum": cause_ids},
                                 "probability": {"type": "number", "description": "0..1"},
                                 "why": {"type": "string", "description": "one short reason, only from the facts given"}})},
        "questions": {"type": "array", "description": "the best next 1-3 questions, in order",
                      "items": obj({"id": {"type": "string", "enum": q_ids},
                                    "if_answers": {"type": "array", "items": obj({
                                        "answer": {"type": "string"},
                                        "rules_in": {"type": "array", "items": {"type": "string", "enum": cause_ids}},
                                        "rules_out": {"type": "array", "items": {"type": "string", "enum": cause_ids}}})}})},
        "self_help": {"type": "array", "items": {"type": "string", "enum": cause_ids},
                      "description": "cheap self-help causes worth a 'try this' tip early"},
        "stop_when": {"type": "string", "description": "when to stop asking and conclude (one sentence)"},
    })


SYSTEM = """You plan a short WhatsApp diagnosis for a tenant with no hot water. Use ONLY the facts given \
(the tenant's messages, the building data, the knowledge base). Never assume a fact the tenant didn't \
give: 'my shower is cold' says nothing about the sinks. Rank the likeliest causes with probabilities, \
then choose the best 1-3 questions (at most 3 in total, ids from the KB; never the gas stove), cheapest \
self-help checks early, each question splitting the likeliest causes. Say when to stop and conclude."""


async def make_plan(contact, conv, reason: str = "first message") -> dict | None:
    """Calls the planner model; stores the plan in conv.diagnosis['plan'] (None on any error)."""
    from openai import AsyncOpenAI

    from app.media import openai_base_url

    from . import diagnosis, flow

    d = conv.diagnosis
    kb = diagnosis.kb()
    ctx = flow.unit_context_for(contact) if contact is not None else {}
    facts = {
        "tenant_messages": list(dict.fromkeys(t for t in (d.get("complaint"), d.get("last_text")) if t)),
        "answers_so_far": d.get("answers", {}),
        "tenant_doesnt_know": d.get("dont_know", []),
        "already_asked": d.get("asked", []),
        "centrix_facts": d.get("facts", []),
        "error_code": conv.error_code,
        "building": ctx,
        "previous_plan": d.get("plan"),
        "reason": reason,
    }
    kb_view = {"questions": [{"id": q["id"], "text": q["text"], "answers": q["answers"]} for q in kb["questions"]
                             if q.get("ask", True)],
               "causes": [{"id": c["id"], "label": c["label"], "signals": c["signals"], "outcome": c["outcome"],
                           "requires": c.get("requires", [])} for c in kb["causes"]],
               "likelihood_order": kb.get("likelihood_order", []), "strategy": kb.get("strategy", [])}
    extra = {}
    effort = os.getenv("PLANNER_REASONING_EFFORT", "low")
    if effort:
        extra["reasoning_effort"] = effort
    t0 = time.perf_counter()
    try:
        client = AsyncOpenAI(base_url=openai_base_url(), timeout=float(os.getenv("PLANNER_TIMEOUT", "25")),
                             max_retries=0)
        r = await client.chat.completions.create(
            model=model(),
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": "Knowledge base:\n" + json.dumps(kb_view, ensure_ascii=False)
                       + "\n\nFacts:\n" + json.dumps(facts, ensure_ascii=False, default=str)}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": "plan", "strict": True, "schema": _schema(kb)}},
            **extra,
        )
        plan = json.loads(r.choices[0].message.content)
    except Exception as exc:  # the diagnosis works without a plan
        log.warning("planner failed (%s: %s)", type(exc).__name__, exc)
        return None
    usage = getattr(r, "usage", None)
    rec = d.setdefault("planner_usage", [])
    rec.append({"reason": reason, "seconds": round(time.perf_counter() - t0, 2),
                "prompt_tokens": getattr(usage, "prompt_tokens", 0), "completion_tokens": getattr(usage, "completion_tokens", 0)})
    plan["made_for"] = reason
    d["plan"] = plan
    log.info("plan (%s, %.1fs): %s / next %s", reason, rec[-1]["seconds"],
             [(c["id"], c["probability"]) for c in plan["causes"][:3]], [q["id"] for q in plan["questions"]])
    return plan


def next_question(d: dict) -> str | None:
    """The plan's first question that is not answered, asked or unknown yet."""
    plan = (d or {}).get("plan")
    if not plan:
        return None
    done = set(d.get("answers", {})) | set(d.get("asked", [])) | set(d.get("dont_know", []))
    return next((q["id"] for q in plan["questions"] if q["id"] not in done), None)


def guidance(d: dict) -> dict | None:
    """What Luna sees in <diagnosis>.plan."""
    plan = (d or {}).get("plan")
    if not plan:
        return None
    return {"likeliest": [{"id": c["id"], "p": c["probability"], "why": c["why"]} for c in plan["causes"][:4]],
            "next_question": next_question(d), "questions": plan["questions"], "self_help": plan["self_help"],
            "stop_when": plan["stop_when"],
            "note": "Guidance from a planner model. Follow it unless the tenant's answers point elsewhere."}


def should_replan(conv, before: dict) -> bool:
    """Once: an answer rules out the plan's top cause, or the tenant volunteered an answer the plan's
    questions didn't cover, or an answer contradicts an earlier one."""
    from . import diagnosis

    d = conv.diagnosis
    plan = d.get("plan")
    if not plan or d.get("replanned"):
        return False
    new = {q: k for q, k in d["answers"].items() if before.get(q) != k}
    planned = {q["id"] for q in plan["questions"]}
    top = plan["causes"][0]["id"] if plan["causes"] else None
    if d.get("conflicts"):
        return True
    if top and top in diagnosis.causes() and diagnosis.contradictions(d, top, conv.error_code):
        return True
    return any(q not in planned and q != diagnosis.open_question(d) for q in new)
