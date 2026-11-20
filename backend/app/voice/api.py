"""Voice router: ElevenLabs server tools, post-call webhook, and the /call test page.

  POST /api/voice/tools/identify_caller   (header X-Debye-Voice-Secret)
  POST /api/voice/tools/report_issue      (header X-Debye-Voice-Secret)
  POST /api/voice/post_call               (ElevenLabs-Signature HMAC, or X-Debye-Voice-Secret)
  GET  /api/voice/signed_url?contact=c_202   signed URL for the browser session
  POST /api/voice/calls/{conversation_id}/end   the /call page reports the end of a session
  GET  /call?contact=c_202                 "Call Debye" test page (no phone number needed)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import app.channels.base  # noqa: F401  (exports .env into os.environ)

from . import calls

log = logging.getLogger("debye.voice")
router = APIRouter()

SECRET_HEADER = "X-Debye-Voice-Secret"
_PAGE = Path(__file__).with_name("call_page.html")


def _secret() -> str | None:
    return os.getenv("VOICE_TOOL_SECRET") or None


def _check_secret(value: str | None) -> None:
    secret = _secret()
    if not secret:
        raise HTTPException(503, "VOICE_TOOL_SECRET is not set on the server")
    if not value or not hmac.compare_digest(value, secret):
        raise HTTPException(401, "bad voice secret")


class ToolCaller(BaseModel):
    conversation_id: str | None = None
    contact_id: str | None = None  # web test page (dynamic variable)
    caller_id: str | None = None  # phone call (system__caller_id)


class ReportIssue(ToolCaller):
    summary: str = ""
    symptoms: str | None = None
    error_code: str | None = None
    all_radiators_cold: str | bool | None = None
    priority: str | None = None


@router.post("/api/voice/tools/identify_caller")
async def tool_identify_caller(body: ToolCaller, x_debye_voice_secret: str | None = Header(None)):
    _check_secret(x_debye_voice_secret)
    return await calls.identify_caller(body.conversation_id, body.contact_id, body.caller_id)


@router.post("/api/voice/tools/report_issue")
async def tool_report_issue(body: ReportIssue, x_debye_voice_secret: str | None = Header(None)):
    _check_secret(x_debye_voice_secret)
    return await calls.report_issue(
        body.conversation_id, body.contact_id, body.caller_id, body.summary, body.symptoms,
        body.error_code, body.all_radiators_cold, body.priority,
    )


def verify_elevenlabs_signature(raw: bytes, header: str | None, secret: str, tolerance: int = 1800) -> bool:
    """ElevenLabs-Signature: 't=<unix>,v0=<hex hmac_sha256(secret, f"{t}.{body}")>'."""
    if not header:
        return False
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    t, sig = parts.get("t"), parts.get("v0")
    if not t or not sig or not t.isdigit() or abs(time.time() - int(t)) > tolerance:
        return False
    mac = hmac.new(secret.encode(), f"{t}.".encode() + raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, sig)


@router.post("/api/voice/post_call")
async def post_call(request: Request, x_debye_voice_secret: str | None = Header(None),
                    elevenlabs_signature: str | None = Header(None)):
    raw = await request.body()
    wh_secret = os.getenv("ELEVENLABS_WEBHOOK_SECRET")
    if not (wh_secret and verify_elevenlabs_signature(raw, elevenlabs_signature, wh_secret)):
        _check_secret(x_debye_voice_secret)
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(400, "invalid JSON")
    if payload.get("type") not in (None, "post_call_transcription"):
        return {"ok": True, "ignored": payload.get("type")}
    data = payload.get("data") or payload
    return await calls.finish_call(data)


@router.get("/api/voice/signed_url")
async def get_signed_url(contact: str = "c_202"):
    agent_id = os.getenv("ELEVENLABS_AGENT_ID")
    if not agent_id:
        raise HTTPException(503, "ELEVENLABS_AGENT_ID is not set; run scripts/elevenlabs_agent.py")
    c = calls.resolve_contact(contact_id=contact)
    try:
        url = await calls.signed_url(agent_id)
    except Exception as e:
        log.exception("signed url failed")
        raise HTTPException(502, f"ElevenLabs: {type(e).__name__}")
    return {"signed_url": url, "contact_id": contact,
            "contact_name": calls.flow.first_name(c) if c else None}


@router.post("/api/voice/calls/{conversation_id}/end")
async def call_ended(conversation_id: str, background: BackgroundTasks):
    """The browser says the session ended; ElevenLabs needs a few seconds to process the call."""
    if not conversation_id.replace("_", "").isalnum():
        raise HTTPException(400, "bad conversation id")
    call = calls.get_call(conversation_id)
    if call and call.finished:
        return {"ok": True, "already_done": True}
    background.add_task(calls.finish_when_done, conversation_id, 120)
    return {"ok": True, "queued": True}


@router.get("/call", response_class=HTMLResponse, include_in_schema=False)
def call_page():
    return HTMLResponse(_PAGE.read_text(encoding="utf-8"))
