"""Twilio WhatsApp (sandbox) adapter: same Channel interface as the Meta adapter.

Selected with WA_PROVIDER=twilio (default when TWILIO_ACCOUNT_SID is set). The routes are
included in app.channels.whatsapp.router, so main.py needs no change:
  POST /webhooks/twilio              inbound messages (form-encoded), X-Twilio-Signature checked
  POST /webhooks/twilio/status       delivery status callbacks (logged; failures at WARNING)
  GET  /webhooks/twilio/media/{tok}  short-lived public URLs for outbound media (voice notes)

The sandbox can't send interactive buttons/lists without Content templates, so they go out
as numbered text ("1 = Überall kalt") and the reply ("1", "1.", or the option text) is
mapped back to the same button id. Router and flow logic stay unchanged.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import mimetypes
import os
import re
import secrets
import time
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse, Response

from .base import Channel, InboundMessage, Media, Option, normalize_phone, remember, storage_dir

log = logging.getLogger("debye.twilio")

API = "https://api.twilio.com/2010-04-01"
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
MEDIA_TTL_S = 3600
PENDING_TTL_S = 24 * 3600


def _env(name: str) -> str:
    return os.getenv(name, "") or ""


def wa_provider() -> str:
    """WA_PROVIDER=twilio|meta; default twilio when TWILIO_ACCOUNT_SID is set."""
    p = _env("WA_PROVIDER").strip().lower()
    if p in ("twilio", "meta"):
        return p
    return "twilio" if _env("TWILIO_ACCOUNT_SID") else "meta"


def twilio_ready() -> bool:
    return bool(_env("TWILIO_ACCOUNT_SID") and _env("TWILIO_AUTH_TOKEN") and _env("TWILIO_WHATSAPP_FROM"))


def public_base_url() -> str:
    return (_env("PUBLIC_BASE_URL") or "http://localhost:8000").rstrip("/")


def to_e164(raw: str) -> str:
    """'whatsapp:+49 151 …' → '+49151…'."""
    raw = (raw or "").strip()
    if raw.lower().startswith("whatsapp:"):
        raw = raw[len("whatsapp:"):]
    return normalize_phone(re.sub(r"[^\d+]", "", raw))


# ------------------------------------------------------------------ numbered replies (buttons/lists fallback)
_pending: dict[str, tuple[float, list[Option]]] = {}  # phone -> (sent_at, options)


def numbered_text(body: str, options: list[Option], intro: str = "Reply with the number:") -> str:
    lines = [f"{i} = {o.title}" for i, o in enumerate(options, start=1)]
    return f"{body}\n\n{intro}\n" + "\n".join(lines)


def remember_options(phone: str, options: list[Option]) -> None:
    _pending[normalize_phone(phone)] = (time.time(), list(options))


def match_numbered_reply(phone: str, body: str | None) -> Option | None:
    """'1', '1.', '1)', ' 2 ' or the option's title (case-insensitive) → that option; clears it."""
    key = normalize_phone(phone)
    entry = _pending.get(key)
    if not entry or not body:
        return None
    sent_at, options = entry
    if time.time() - sent_at > PENDING_TTL_S:
        _pending.pop(key, None)
        return None
    text = body.strip().strip(".)!").strip().casefold()
    chosen = None
    if text.isdigit() and 1 <= int(text) <= len(options):
        chosen = options[int(text) - 1]
    else:
        chosen = next((o for o in options if o.title.strip().casefold() == text), None)
    if chosen is not None:
        _pending.pop(key, None)
    return chosen


# ------------------------------------------------------------------ public media URLs for outbound media
_media: dict[str, tuple[float, str, str]] = {}  # token -> (expires_at, path, mime)


def public_media_url(path: str, mime: str | None = None) -> str:
    token = secrets.token_urlsafe(18)
    mime = mime or mimetypes.guess_type(path)[0] or "application/octet-stream"
    _media[token] = (time.time() + MEDIA_TTL_S, path, mime)
    for t in [t for t, (exp, _, _) in _media.items() if exp < time.time()]:
        _media.pop(t, None)
    return f"{public_base_url()}/webhooks/twilio/media/{token}{Path(path).suffix}"


# ------------------------------------------------------------------ signature
def expected_signature(url: str, params: dict[str, str], auth_token: str) -> str:
    data = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    digest = hmac.new(auth_token.encode(), data.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def candidate_urls(request: Request) -> list[str]:
    path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    urls = [public_base_url() + path]
    proto = request.headers.get("x-forwarded-proto")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if host:
        urls.append(f"{proto or request.url.scheme}://{host}{path}")
        urls.append(f"https://{host}{path}")
    urls.append(str(request.url))
    return list(dict.fromkeys(urls))


def verify_twilio_signature(request: Request, params: dict[str, str]) -> bool:
    token = _env("TWILIO_AUTH_TOKEN")
    if not token or _env("TWILIO_VALIDATE_SIGNATURE") == "0":
        return True
    got = request.headers.get("X-Twilio-Signature", "")
    if not got:
        return False
    return any(hmac.compare_digest(expected_signature(u, params, token), got) for u in candidate_urls(request))


# ------------------------------------------------------------------ inbound parsing
def parse_twilio(params: dict[str, str]) -> InboundMessage:
    phone = to_e164(params.get("From", ""))
    msg = InboundMessage(
        channel="whatsapp",
        from_phone=phone,
        wa_message_id=params.get("MessageSid") or params.get("SmsMessageSid"),
        text=(params.get("Body") or "").strip() or None,
        profile_name=params.get("ProfileName"),
    )
    if params.get("ButtonPayload"):  # quick-reply content (if ever used)
        msg.button_id, msg.button_title, msg.text = params["ButtonPayload"], params.get("ButtonText"), None
    else:
        opt = match_numbered_reply(phone, msg.text)
        if opt is not None:
            msg.button_id, msg.button_title, msg.text = opt.id, opt.title, None
    try:
        n = int(params.get("NumMedia") or 0)
    except ValueError:
        n = 0
    for i in range(n):
        url = params.get(f"MediaUrl{i}")
        if url:
            msg.media.append(Media(media_id=url, mime=params.get(f"MediaContentType{i}") or "application/octet-stream"))
    return msg


# ------------------------------------------------------------------ channel
class TwilioChannel(Channel):
    name = "whatsapp"  # same logical channel; the dispatcher in whatsapp.py picks the provider

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=20, follow_redirects=True)
        return self._client

    def _auth(self) -> tuple[str, str]:
        return (_env("TWILIO_ACCOUNT_SID"), _env("TWILIO_AUTH_TOKEN"))

    async def _send(self, to: str, body: str = "", media_url: str | None = None) -> str | None:
        data = {"From": _env("TWILIO_WHATSAPP_FROM"), "To": f"whatsapp:{normalize_phone(to)}"}
        if body:
            data["Body"] = body[:1600]
        if media_url:
            data["MediaUrl"] = media_url
        if not public_base_url().startswith("http://localhost"):
            data["StatusCallback"] = f"{public_base_url()}/webhooks/twilio/status"
        r = await self.client.post(f"{API}/Accounts/{_env('TWILIO_ACCOUNT_SID')}/Messages.json", data=data,
                                   auth=self._auth())
        if r.status_code >= 400:
            log.error("Twilio send failed %s: %s", r.status_code, r.text[:300])
            r.raise_for_status()
        sid = r.json().get("sid")
        log.info("Twilio message %s queued to %s", sid, data["To"])
        return sid

    async def send_text(self, to: str, text: str) -> str | None:
        return await self._send(to, text)

    async def send_buttons(self, to: str, text: str, options: list[Option]) -> str | None:
        remember_options(to, options)
        return await self._send(to, numbered_text(text, options))

    async def send_list(self, to, text, button_label, rows, section_title="Optionen") -> str | None:
        remember_options(to, rows)
        return await self._send(to, numbered_text(text, rows))

    async def send_media(self, to, kind, path, caption=None, mime=None) -> str | None:
        return await self._send(to, caption or "", media_url=public_media_url(path, mime))

    async def download_media(self, media: Media) -> str:
        ext = mimetypes.guess_extension(media.mime.split(";")[0].strip()) or ""
        if media.mime.startswith("audio/ogg"):
            ext = ".ogg"
        dest = storage_dir() / "inbound" / f"{uuid.uuid4().hex[:10]}{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = await self.client.get(media.media_id, auth=self._auth())  # Twilio redirects to a CDN URL
        r.raise_for_status()
        dest.write_bytes(r.content)
        media.local_path = str(dest)
        return str(dest)


channel = TwilioChannel()

# ------------------------------------------------------------------ routes
router = APIRouter(tags=["twilio"])


async def _form_params(request: Request) -> dict[str, str]:
    form = await request.form()
    return {k: str(v) for k, v in form.multi_items()}


@router.post("/webhooks/twilio")
async def twilio_webhook(request: Request, background: BackgroundTasks):
    from . import whatsapp as wa

    params = await _form_params(request)
    if not verify_twilio_signature(request, params):
        log.warning("Twilio webhook with bad signature (check PUBLIC_BASE_URL = the URL set in Twilio)")
        raise HTTPException(status_code=403, detail="bad signature")
    msg = parse_twilio(params)
    if not msg.from_phone or msg.from_phone == "+":
        return Response(EMPTY_TWIML, media_type="text/xml")
    if wa.already_seen(msg.wa_message_id):
        log.info("duplicate %s ignored", msg.wa_message_id)
        return Response(EMPTY_TWIML, media_type="text/xml")
    remember(msg.from_phone, "whatsapp")
    background.add_task(wa.process_inbound, msg)
    return Response(EMPTY_TWIML, media_type="text/xml")  # fast 200; processing runs afterwards


@router.post("/webhooks/twilio/status")
async def twilio_status(request: Request):
    params = await _form_params(request)
    if not verify_twilio_signature(request, params):
        raise HTTPException(status_code=403, detail="bad signature")
    status = params.get("MessageStatus")
    if status in ("failed", "undelivered") or params.get("ErrorCode"):
        log.warning("Twilio delivery FAILED for %s: status=%s error=%s %s", params.get("MessageSid"), status,
                    params.get("ErrorCode"), params.get("ErrorMessage", ""))
    else:
        log.info("Twilio status %s for %s", status, params.get("MessageSid"))
    return Response(status_code=204)


@router.api_route("/webhooks/twilio/media/{token}", methods=["GET", "HEAD"])
async def twilio_media(token: str):
    entry = _media.get(token.split(".")[0])  # URL carries the file suffix for Twilio's type sniffing
    if not entry or entry[0] < time.time():
        raise HTTPException(status_code=404)
    _, path, mime = entry
    return FileResponse(path, media_type=mime)
