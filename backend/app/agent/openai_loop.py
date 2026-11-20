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
from .prompts import TENANT_SYSTEM
from .tools import SCHEMAS, TurnContext, execute

log = logging.getLogger("debye.agent.openai")

DEFAULT_MODEL = "gpt-6-luna"
MAX_ITERATIONS = 6

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
        from openai import AsyncOpenAI

        from app.media import openai_base_url

        _client = AsyncOpenAI(base_url=openai_base_url(), timeout=timeout, max_retries=1)
    return _client


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


async def run_loop(messages: list, ctx: TurnContext, timeout: float) -> list:
    if _client is None and not os.getenv("OPENAI_API_KEY"):
        raise NoCredentials("OPENAI_API_KEY not set")
    client = get_client(timeout)
    extra = {}
    effort = reasoning_effort()
    if effort:
        extra["reasoning_effort"] = effort
    for _ in range(MAX_ITERATIONS):
        response = await client.chat.completions.create(
            model=chat_model(),
            messages=[{"role": "system", "content": TENANT_SYSTEM}, *messages],
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
            return messages
        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                content = "Error: arguments were not valid JSON"
            else:
                result = await execute(SimpleNamespace(id=tc.id, name=tc.function.name, input=args), ctx)
                content = result["content"]
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})
    log.warning("agent hit MAX_ITERATIONS")
    return messages
