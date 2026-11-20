"""Linked-phone WhatsApp (demo route): Debye on a regular WhatsApp account via bridge/ (Baileys).

Selected with WA_PROVIDER=wweb. The bridge runs next to the backend:
  bridge → POST /webhooks/wweb   {from_e164, message_id, text, media:[{base64|path, mime, filename}], push_name}
  backend → POST {WWEB_BRIDGE_URL}/send        {to_e164, text}
            POST {WWEB_BRIDGE_URL}/send-media  {to_e164, path, mime, caption, ptt}
Both directions are signed: X-Wweb-Signature: sha256=<hex HMAC-SHA256 of the raw body, key WWEB_SECRET>.
Buttons and lists go out as numbered text (same fallback as Twilio); "1" / the option text maps back
to the same button id, so router and flow stay unchanged. The routes are included in the WhatsApp router.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from . import twilio as tw  # numbered-reply helpers
from .base import Channel, InboundMessage, Media, Option, normalize_phone, remember, storage_dir

log = logging.getLogger("debye.wweb")

MEDIA_PREFIX = "wweb-local:"


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default) or default


def bridge_url() -> str:
    return _env("WWEB_BRIDGE_URL", "http://127.0.0.1:3010").rstrip("/")


def sign(raw: bytes) -> str:
    return "sha256=" + hmac.new(_env("WWEB_SECRET").encode(), raw, hashlib.sha256).hexdigest()


def verify(raw: bytes, header: str | None) -> bool:
    if not _env("WWEB_SECRET"):
        return True  # local dev; the bridge warns about it too
    return bool(header) and hmac.compare_digest(sign(raw), header)


# ------------------------------------------------------------------ inbound parsing
def _save_media(item: dict) -> Media | None:
    mime = (item.get("mime") or "application/octet-stream").split(";")[0].strip()
    ext = ".ogg" if mime.startswith("audio/ogg") else (mimetypes.guess_extension(mime) or "")
    dest = storage_dir() / "inbound" / f"wweb_{uuid.uuid4().hex[:10]}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if item.get("base64"):
        try:
            dest.write_bytes(base64.b64decode(item["base64"]))
        except (binascii.Error, ValueError):
            log.warning("bad base64 media ignored")
            return None
    elif item.get("path") and Path(item["path"]).is_file():
        dest.write_bytes(Path(item["path"]).read_bytes())
    else:
        return None
    return Media(media_id=f"{MEDIA_PREFIX}{dest}", mime=item.get("mime") or mime, filename=item.get("filename"),
                 local_path=str(dest))


def parse_wweb(payload: dict) -> InboundMessage:
    phone = normalize_phone(str(payload.get("from_e164") or ""))
    msg = InboundMessage(
        channel="whatsapp",
        from_phone=phone,
        wa_message_id=f"wweb.{payload.get('message_id')}" if payload.get("message_id") else None,
        text=(payload.get("text") or "").strip() or None,
        profile_name=payload.get("push_name"),
    )
    opt = tw.match_numbered_reply(phone, msg.text)
    if opt is not None:
        msg.button_id, msg.button_title, msg.text = opt.id, opt.title, None
    for item in payload.get("media") or []:
        m = _save_media(item)
        if m:
            msg.media.append(m)
    return msg


# ------------------------------------------------------------------ channel
class WWebChannel(Channel):
    name = "whatsapp"  # same logical channel; the dispatcher in whatsapp.py picks the provider

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30)
        return self._client

    async def _post(self, path: str, payload: dict) -> str | None:
        raw = json.dumps(payload, ensure_ascii=False).encode()
        r = await self.client.post(f"{bridge_url()}{path}", content=raw,
                                   headers={"content-type": "application/json", "x-wweb-signature": sign(raw)})
        if r.status_code >= 400:
            log.error("bridge %s failed %s: %s", path, r.status_code, r.text[:300])
            r.raise_for_status()
        mid = (r.json() or {}).get("id")
        log.info("bridge sent %s to %s (%s)", path, payload.get("to_e164"), mid)
        return mid

    async def send_text(self, to: str, text: str) -> str | None:
        return await self._post("/send", {"to_e164": normalize_phone(to), "text": text})

    async def send_buttons(self, to: str, text: str, options: list[Option]) -> str | None:
        tw.remember_options(to, options)
        return await self.send_text(to, tw.natural_text(text, options))

    async def send_list(self, to, text, button_label, rows, section_title="Optionen") -> str | None:
        tw.remember_options(to, rows)
        return await self.send_text(to, tw.natural_text(text, rows, is_list=True))

    async def send_media(self, to, kind, path, caption=None, mime=None) -> str | None:
        mime = mime or mimetypes.guess_type(path)[0] or "application/octet-stream"
        return await self._post("/send-media", {
            "to_e164": normalize_phone(to), "path": str(Path(path).resolve()), "mime": mime,
            "caption": caption, "ptt": kind == "audio", "filename": Path(path).name,
        })

    async def download_media(self, media: Media) -> str:
        path = media.local_path or media.media_id[len(MEDIA_PREFIX):]
        media.local_path = path
        return path


channel = WWebChannel()

# ------------------------------------------------------------------ routes
router = APIRouter(tags=["wweb"])


@router.post("/webhooks/wweb")
async def wweb_webhook(request: Request, background: BackgroundTasks):
    from . import whatsapp as wa

    raw = await request.body()
    if not verify(raw, request.headers.get("x-wweb-signature")):
        log.warning("wweb webhook with bad signature (WWEB_SECRET differs between bridge and backend?)")
        raise HTTPException(status_code=401, detail="bad signature")
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="bad json")
    msg = parse_wweb(payload)
    if not msg.from_phone or msg.from_phone == "+":
        return {"ok": True, "ignored": "no sender"}
    if wa.already_seen(msg.wa_message_id):
        return {"ok": True, "duplicate": True}
    remember(msg.from_phone, "whatsapp")
    background.add_task(wa.process_inbound, msg)
    return {"ok": True}
