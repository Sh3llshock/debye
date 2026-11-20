"""Debye agent turn (technical-plan §7.2).

LLM_PROVIDER picks the model: "openai" (default, agent/openai_loop.py,
OPENAI_CHAT_MODEL, default gpt-6-luna) or "anthropic" (the Claude loop below).
The agent speaks only through tools. If the model errors, refuses or takes longer
than TURN_TIMEOUT, and nothing has been sent yet this turn, the scripted
fallback for the current step runs instead (flow.scripted_fallback).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from pathlib import Path

from . import _backend as be
from . import flow
from . import openai_loop
from . import state as st
from .errors import NoCredentials, RefusalError
from .prompts import FALLBACK_HANDOFF, TENANT_SYSTEM
from .tools import SCHEMAS, TurnContext, execute

log = logging.getLogger("debye.agent")

MODEL = "claude-opus-5-5"
TURN_TIMEOUT = float(os.getenv("AGENT_TIMEOUT", "20"))
MAX_ITERATIONS = 6
_KEEP_BLOCKS = {"text", "thinking", "redacted_thinking", "tool_use"}

_client = None
last_turn_fallback = False  # for tests / debugging: did the last turn use a scripted reply?


def llm_provider() -> str:
    return (os.getenv("LLM_PROVIDER") or "openai").strip().lower()


def get_client():
    """Lazily created so tests can replace it (set_client) and imports never need a key."""
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.AsyncAnthropic(timeout=TURN_TIMEOUT, max_retries=1)
    return _client


def set_client(client) -> None:
    global _client
    _client = client


def _dump(block) -> dict:
    return block.model_dump(exclude_none=True) if hasattr(block, "model_dump") else dict(block)


def _image_block(path: str) -> dict | None:
    suffix = Path(path).suffix.lower()
    mime = {".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}.get(suffix, "image/jpeg")
    try:
        data = base64.standard_b64encode(Path(path).read_bytes()).decode()
    except OSError:
        return None
    return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}}


def build_user_content(contact, conv: st.Conversation, text: str | None, image_paths: list[str]) -> list[dict]:
    ctx = flow.unit_context_for(contact)
    facts = {
        "contact": {"id": be.attr(contact, "id"), "name": be.attr(contact, "name"),
                    "language": be.attr(contact, "language", "de")},
        "unit_context": ctx,
    }
    status = {"case_id": conv.case_id, "step": conv.step}
    if conv.step == st.TRIAGE and st.TRIAGE in conv.asked_at:
        status["waiting_for"] = "resident's tap on 'Überall kalt' / 'Nur ein Raum' (already asked, do not repeat)"
    elif conv.step == st.CONSENT:
        status["waiting_for"] = "resident's consent tap (already asked, do not repeat)"
    if conv.error_code:
        status["error_code_already_explained"] = conv.error_code
    content: list[dict] = []
    for p in image_paths:
        blk = _image_block(p)
        if blk:
            content.append(blk)
    content.append(
        {
            "type": "text",
            "text": f"<centrix_context>{json.dumps(facts, ensure_ascii=False, default=str)}</centrix_context>\n"
            f"<state>{json.dumps(status)}</state>\n"
            f"<resident_message>{text or '(no text)'}</resident_message>",
        }
    )
    return content


async def _run_loop(messages: list, ctx: TurnContext) -> list:
    if _client is None and not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        # Without an explicit key the SDK probes other credential sources, which stalled a turn ~40 s.
        raise NoCredentials("ANTHROPIC_API_KEY not set")
    client = get_client()
    for _ in range(MAX_ITERATIONS):
        response = await client.beta.messages.create(
            model=MODEL,
            max_tokens=4000,
            system=TENANT_SYSTEM,
            tools=SCHEMAS,
            tool_choice={"type": "auto"},
            messages=messages,
            output_config={"effort": ctx.effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            log.warning("Claude refused: %s", getattr(response, "stop_details", None))
            raise RefusalError()
        content = [_dump(b) for b in response.content if getattr(b, "type", None) in _KEEP_BLOCKS]
        messages.append({"role": "assistant", "content": content})
        if response.stop_reason != "tool_use":
            return messages
        results = [await execute(b, ctx) for b in response.content if getattr(b, "type", None) == "tool_use"]
        messages.append({"role": "user", "content": results})  # all results in ONE user message
    log.warning("agent hit MAX_ITERATIONS")
    return messages


async def run_tenant_turn(contact, text: str | None, image_paths: list[str] | None = None) -> None:
    """One Debye turn for a tenant message (text/transcript and/or photos)."""
    global last_turn_fallback
    last_turn_fallback = False
    conv = st.conversation(be.attr(contact, "id"))
    if text:
        conv.tenant_texts.append(text)
    provider = llm_provider()
    if conv.history_provider != provider:  # histories are provider-specific
        conv.history, conv.history_provider = [], provider
    ctx = TurnContext(contact=contact, conv=conv, effort="low")
    blocks = build_user_content(contact, conv, text, image_paths or [])
    if provider == "openai":
        user_msg = {"role": "user", "content": openai_loop.to_openai_content(blocks)}
        runner = openai_loop.run_loop(list(conv.history) + [user_msg], ctx, TURN_TIMEOUT)
    else:
        user_msg = {"role": "user", "content": blocks}
        runner = _run_loop(list(conv.history) + [user_msg], ctx)
    t0 = time.perf_counter()
    try:
        messages = await asyncio.wait_for(runner, timeout=TURN_TIMEOUT)
        log.info("agent turn (%s) %.2fs, tools=%s", provider, time.perf_counter() - t0, ",".join(ctx.calls) or "-")
        if messages[-1]["role"] in ("user", "tool"):  # ended on tool results (iteration cap): close cleanly
            if provider == "openai":
                messages.append({"role": "assistant", "content": "(turn ended)"})
            else:
                messages.append({"role": "assistant", "content": [{"type": "text", "text": "(turn ended)"}]})
        conv.history = messages
        await flow.link_if_building_case_open(contact, conv)
        if ctx.sent == 0:
            log.warning("agent turn sent nothing; using scripted fallback")
            last_turn_fallback = True
            await flow.scripted_fallback(contact, conv, image_paths)
        return
    except RefusalError:
        last_turn_fallback = True
        if ctx.sent == 0:
            from . import outbound

            await outbound.text(contact, conv.case_id, FALLBACK_HANDOFF)
    except Exception as exc:  # timeout, API error, bug: the resident still gets an answer
        log.warning("agent turn failed (%s: %s); scripted fallback", type(exc).__name__, exc)
        last_turn_fallback = True
        if ctx.sent == 0:
            await flow.scripted_fallback(contact, conv, image_paths)
    # Keep history valid (alternating, no dangling tool calls) after a failed turn.
    only_text = [b for b in user_msg["content"] if b["type"] == "text"]
    if provider == "openai":
        conv.history = list(conv.history) + [
            {"role": "user", "content": only_text},
            {"role": "assistant", "content": "(scripted reply sent)"},
        ]
    else:
        conv.history = list(conv.history) + [
            {"role": "user", "content": only_text},
            {"role": "assistant", "content": [{"type": "text", "text": "(scripted reply sent)"}]},
        ]
