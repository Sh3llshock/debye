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
                "summary": {"type": "string", "description": "short German title, e.g. 'Heizung kalt, Fehler F.28'"},
                "symptoms": {"type": "string", "description": "what the resident reported, in German"},
                "error_code": {"type": ["string", "null"], "description": "display code like F.28, or null"},
                "priority": {"type": "string", "enum": ["emergency", "urgent", "normal"]},
            }
        ),
    },
    {
        "name": "record_triage_answer",
        "description": "Use when the resident answers 'are all radiators cold?' by typing instead of tapping. "
        "Finds the installer and asks the resident for consent automatically.",
        "input_schema": _obj({"case_id": {"type": "string"}, "all_radiators_cold": {"type": "boolean"}}),
    },
]

for s in SCHEMAS:
    s["strict"] = True


async def _reply(ctx: TurnContext, text: str) -> dict:
    await out.text(ctx.contact, ctx.conv.case_id, text)
    ctx.sent += 1
    return {"ok": True, "delivered": True}


async def _ask_buttons(ctx: TurnContext, text: str, options: list[dict]) -> dict:
    if not options:
        raise ValueError("options must not be empty")
    await out.buttons(ctx.contact, ctx.conv.case_id, text, [Option(o["id"], o["title"]) for o in options])
    ctx.sent += 1
    return {"ok": True, "delivered": True}


async def _ask_list(ctx: TurnContext, text: str, button_label: str, rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("rows must not be empty")
    await out.list_(ctx.contact, ctx.conv.case_id, text, button_label, [Option(r["id"], r["title"]) for r in rows])
    ctx.sent += 1
    return {"ok": True, "delivered": True}


async def _open_case(ctx: TurnContext, summary: str, symptoms: str, error_code: str | None, priority: str) -> dict:
    res = await flow.ensure_case(
        ctx.contact, summary=summary, symptoms=symptoms, error_code=error_code, priority=priority
    )
    if res.get("duplicate"):
        return {"case_id": res["case_id"], "duplicate": True,
                "next": "Tell the resident it is already reported and being handled. Ask nothing else."}
    if res.get("already_open"):
        return {"case_id": res["case_id"], "duplicate": False, "note": "case was already open for this resident"}
    return {"case_id": res["case_id"], "duplicate": False,
            "next": f"Ask with ask_buttons: ids cold_all:{res['case_id']} / cold_some:{res['case_id']}."}


async def _record_triage(ctx: TurnContext, case_id: str, all_radiators_cold: bool) -> dict:
    case_id = ctx.conv.case_id or case_id
    await flow.on_cold(ctx.contact, case_id, all_radiators_cold)
    ctx.sent += 1
    return {"ok": True, "note": "Consent question was sent to the resident. Do not send another message."}


IMPLS: dict[str, Callable[..., Awaitable[dict]]] = {
    "reply": _reply,
    "ask_buttons": _ask_buttons,
    "ask_list": _ask_list,
    "open_case": _open_case,
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
