"""Debye agent on OpenAI (default provider): Chat Completions tool-calling loop.

Same tools, strict schemas, persona and "speak only through tools" rule as the
Claude loop. gpt-6-luna only accepts function tools on Chat Completions with
reasoning_effort "none" (otherwise it asks for the Responses API); measured
~1.3 s per call that way vs ~4.3 s on the Responses API with effort "low".
"""
from __future__ import annotations

import json
import logging
import os
from types import SimpleNamespace

from .errors import NoCredentials, RefusalError
from .prompts import LOCAL_SYSTEM, TENANT_SYSTEM
from .tools import SCHEMAS, TurnContext, execute

log = logging.getLogger("debye.agent.openai")

DEFAULT_MODEL = "gpt-6-luna"
MAX_ITERATIONS = 6
SENDING_TOOLS = {"reply", "ask_buttons", "ask_list", "record_triage_answer", "ask_question", "conclude_diagnosis"}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": s["name"],
            "description": s["description"],
            "parameters": s["input_schema"],
            "strict": True,
        },
    }
    for s in SCHEMAS
]

_client = None


def chat_model() -> str:
    return os.getenv("OPENAI_CHAT_MODEL") or DEFAULT_MODEL


def reasoning_effort() -> str | None:
    """OPENAI_REASONING_EFFORT; default "none". Set to "" to omit the parameter (non-reasoning models)."""
    v = os.getenv("OPENAI_REASONING_EFFORT")
    return "none" if v is None else (v or None)


def get_client(timeout: float):
    global _client
    if _client is None:
        from app import local_llm

        if local_llm.enabled():
            _client = local_llm.client(timeout, max_retries=0)
            return _client
        from openai import AsyncOpenAI

        from app.media import openai_base_url

        _client = AsyncOpenAI(base_url=openai_base_url(), timeout=timeout, max_retries=1)
    return _client


# Local models have a small context window and slow CPU prefill: send only the latest messages.
LOCAL_HISTORY_MESSAGES = 12


def trim_history(messages: list, keep: int = LOCAL_HISTORY_MESSAGES) -> list:
    """Last `keep` messages, starting at a user message (never at a dangling tool result)."""
    if len(messages) <= keep:
        return messages
    tail = messages[-keep:]
    while tail and tail[0].get("role") != "user":
        tail = tail[1:]
    return tail or messages[-1:]


def set_client(client) -> None:
    global _client
    _client = client


def to_openai_content(blocks: list[dict]) -> list[dict]:
    """Anthropic-style user blocks (text / base64 image) → Chat Completions content parts."""
    out = []
    for b in blocks:
        if b.get("type") == "image":
            src = b["source"]
            out.append({"type": "image_url", "image_url": {"url": f"data:{src['media_type']};base64,{src['data']}"}})
        elif b.get("type") == "text":
            out.append({"type": "text", "text": b["text"]})
    return out


def _in_diagnosis(ctx: TurnContext) -> bool:
    try:
        from . import diagnosis

        return bool(diagnosis.active(ctx.conv))
    except Exception:
        return False


def repair_call(name: str, args: dict, ctx: TurnContext) -> tuple[str, dict]:
    """qwen3.5:2b sometimes jumps straight to the triage buttons without opening the case. The intent is
    clear (a heating fault), so open the case instead; local_follow_up then asks the triage question."""
    opts = args.get("options") if isinstance(args, dict) else None
    is_cold = name == "ask_buttons" and isinstance(opts, list) and any(
        str((o or {}).get("id", "")).startswith(("cold_all:", "cold_some:")) for o in opts if isinstance(o, dict))
    if is_cold and not getattr(ctx.conv, "case_id", None) and not _in_diagnosis(ctx):
        said = " ".join((getattr(ctx.conv, "tenant_texts", None) or [])[-3:]).strip() or "Heating not working"
        log.info("local model asked triage before open_case; opening the case first")
        return "open_case", {"summary": "No heating / hot water", "symptoms": said[:500], "error_code": None,
                             "priority": "urgent"}
    return name, args


async def local_follow_up(done: list[tuple[str, dict, str]], ctx: TurnContext) -> bool:
    """Guardrails for small local models (LLM_PROVIDER=ollama), measured failure modes of qwen3.5:2b:
    it asked a neighbour the triage buttons on a duplicate case, wrote unclear button texts and
    retried a rejected ask_buttons until the turn timed out. The model still diagnoses (symptom,
    error code from the photo, summary, priority); the message that follows open_case /
    note_error_code is sent deterministically, exactly like the scripted flow. Returns True if sent."""
    from . import flow

    for name, args, content in done:
        try:
            res = json.loads(content)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(res, dict):
            continue
        if name == "open_case" and res.get("case_id") and args.get("priority") != "emergency":
            cid = res["case_id"]
            if res.get("duplicate"):
                await flow.send_duplicate_notice(ctx.contact, cid)
            elif res.get("note"):  # resident's own case was already open: let the model continue
                return False
            else:
                from .tools import _clean_code

                code = _clean_code(args.get("error_code"))
                prefix = "Oh no, a cold flat is the worst 😕 I'm on it."
                if code and res.get("explain_error_code"):
                    said = " ".join(getattr(ctx.conv, "tenant_texts", []) or []).upper()
                    sentence = res["explain_error_code"] if code.upper().replace(".", "") in said.replace(".", "")                         else res.get("explain_error_code_if_from_photo") or res["explain_error_code"]
                    ctx.conv.error_code = code
                    prefix = f"Oh no 😕 {sentence} I'm on it."
                await flow.ask_cold(ctx.contact, cid, prefix=prefix)
            ctx.sent += 1
            return True
        if name == "note_error_code" and res.get("explain_error_code"):
            await flow.out.text(ctx.contact, ctx.conv.case_id, res["explain_error_code"])
            ctx.sent += 1
            return True
    return False


async def run_loop(messages: list, ctx: TurnContext, timeout: float) -> list:
    from app import local_llm

    local = local_llm.enabled()
    if _client is None and not local and not os.getenv("OPENAI_API_KEY"):
        raise NoCredentials("OPENAI_API_KEY not set")
    client = get_client(timeout)
    if local:
        model, extra = local_llm.model(), local_llm.extra_params()
        messages = trim_history(messages)
    else:
        model, extra = chat_model(), {}
        effort = reasoning_effort()
        if effort:
            extra["reasoning_effort"] = effort
    for _ in range(MAX_ITERATIONS):
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": LOCAL_SYSTEM if local else TENANT_SYSTEM}, *messages],
            tools=TOOLS,
            tool_choice="auto",
            **extra,
        )
        choice = response.choices[0]
        msg = choice.message
        if getattr(msg, "refusal", None):
            log.warning("OpenAI refused: %s", msg.refusal)
            raise RefusalError()
        tool_calls = list(msg.tool_calls or [])
        assistant: dict = {"role": "assistant", "content": msg.content or None}
        if tool_calls:
            assistant["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in tool_calls
            ]
        elif assistant["content"] is None:
            assistant["content"] = ""
        messages.append(assistant)
        if not tool_calls:
            if local and ctx.sent == 0 and (msg.content or "").strip() and not _in_diagnosis(ctx):
                # Small local models sometimes answer in plain text instead of calling reply:
                # deliver that text instead of dropping it and falling back to the script.
                log.info("local model answered without a tool; sending its text as a reply")
                await execute(SimpleNamespace(id="plain", name="reply", input={"text": msg.content.strip()}), ctx)
            return messages
        done = []
        for tc in tool_calls:
            args, name = {}, tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                content = "Error: arguments were not valid JSON"
            else:
                if local:
                    name, args = repair_call(name, args, ctx)
                result = await execute(SimpleNamespace(id=tc.id, name=name, input=args), ctx)
                content = result["content"]
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})
            done.append((name, args, content))
        if local and ctx.sent == 0 and await local_follow_up(done, ctx):
            messages.append({"role": "assistant", "content": ""})
            return messages
        if local and ctx.sent and all(tc.function.name in SENDING_TOOLS for tc in tool_calls):
            # The resident has their answer; on a CPU another round trip would only add ~10-20 s for
            # the model to say "done". Close the turn here (history stays valid for the next turn).
            messages.append({"role": "assistant", "content": ""})
            return messages
    log.warning("agent hit MAX_ITERATIONS")
    return messages
