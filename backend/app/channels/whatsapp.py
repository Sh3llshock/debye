"""WhatsApp Cloud API adapter (technical-plan §5.1).

Mount with:  from app.channels.whatsapp import router as whatsapp_router
             app.include_router(whatsapp_router)

Fake-send mode (no Meta account needed): on when WA_TOKEN is empty or
WA_FAKE_SEND=1. Outbound messages are printed and kept in an in-memory outbox,
readable at GET /webhooks/whatsapp/_outbox (DEMO_MODE=1 only). Inbound media ids
of the form `local:<path>` are read from disk, so scripts/simulate.py can send
real audio/photo/PDF files.
"""
from __future__ import annotations

import hashlib
import hmac
import itertools
import json
import logging
import mimetypes
import os
import shutil
import time
import uuid
from collections import OrderedDict
from pathlib import Path

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from .base import (
    MAX_BUTTON_TITLE,
    MAX_BUTTONS,
    MAX_LIST_BUTTON,
    MAX_LIST_ROWS,
    MAX_ROW_TITLE,
    Channel,
    InboundMessage,
    Media,
    Option,
    clamp_options,
    normalize_phone,
    register,
    remember,
    storage_dir,
)

log = logging.getLogger("debye.whatsapp")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default) or default


def fake_send_enabled() -> bool:
    return _env("WA_FAKE_SEND") == "1" or not _env("WA_TOKEN")


def _graph() -> str:
    return f"https://graph.facebook.com/{_env('WA_GRAPH_VERSION', 'v21.0')}"


# ------------------------------------------------------------------ outbox (fake mode)
_outbox: list[dict] = []
_seq = itertools.count(1)


def outbox(since: int = 0) -> list[dict]:
    return [m for m in _outbox if m["seq"] > since]


def clear_outbox() -> None:
    _outbox.clear()


# ------------------------------------------------------------------ dedupe
_seen: OrderedDict[str, float] = OrderedDict()


def already_seen(message_id: str | None) -> bool:
    """True if this wa_message_id was processed before (Meta retries webhooks)."""
    if not message_id:
        return False
    if message_id in _seen:
        return True
    try:  # survives restarts: backend-core stores wa_message_id on every logged message
        from app.agent import _backend as be

        if be._services().message_seen(message_id):
            return True
    except Exception:
        pass
    _seen[message_id] = time.time()
    while len(_seen) > 5000:
        _seen.popitem(last=False)
    return False


# ------------------------------------------------------------------ channel
class WhatsAppChannel(Channel):
    name = "whatsapp"

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15)
        return self._client

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {_env('WA_TOKEN')}"}

    async def _post(self, to: str, payload: dict) -> str | None:
        body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to.lstrip("+"), **payload}
        if fake_send_enabled():
            entry = {"seq": next(_seq), "to": normalize_phone(to), "ts": time.time(), "payload": body}
            _outbox.append(entry)
            line = f"[fake-send -> {entry['to']}] {json.dumps(payload, ensure_ascii=False)}"
            try:
                print(line, flush=True)
            except UnicodeEncodeError:  # Windows console / redirected stdout in cp1252
                print(line.encode("ascii", "backslashreplace").decode(), flush=True)
            return f"fake.{uuid.uuid4().hex[:12]}"
        url = f"{_graph()}/{_env('WA_PHONE_NUMBER_ID')}/messages"
        r = await self.client.post(url, headers=self._headers(), json=body)
        if r.status_code >= 400:
            log.error("WhatsApp send failed %s: %s", r.status_code, r.text)
            r.raise_for_status()
        data = r.json()
        return (data.get("messages") or [{}])[0].get("id")

    async def send_text(self, to: str, text: str) -> str | None:
        return await self._post(to, {"type": "text", "text": {"body": text[:4096], "preview_url": False}})

    async def send_buttons(self, to: str, text: str, options: list[Option]) -> str | None:
        opts = clamp_options(options, MAX_BUTTONS, MAX_BUTTON_TITLE)
        return await self._post(
            to,
            {
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": text[:1024]},
                    "action": {
                        "buttons": [{"type": "reply", "reply": {"id": o.id, "title": o.title}} for o in opts]
                    },
                },
            },
        )

    async def send_list(
        self, to: str, text: str, button_label: str, rows: list[Option], section_title: str = "Optionen"
    ) -> str | None:
        rs = clamp_options(rows, MAX_LIST_ROWS, MAX_ROW_TITLE)
        return await self._post(
            to,
            {
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": text[:4096]},
                    "action": {
                        "button": button_label[:MAX_LIST_BUTTON],
                        "sections": [
                            {"title": section_title[:24], "rows": [{"id": r.id, "title": r.title} for r in rs]}
                        ],
                    },
                },
            },
        )

    async def send_media(
        self, to: str, kind: str, path: str, caption: str | None = None, mime: str | None = None
    ) -> str | None:
        """kind ∈ image | audio | document | video. Uploads the file, then sends it by id."""
        mime = mime or mimetypes.guess_type(path)[0] or "application/octet-stream"
        if fake_send_enabled():
            media_obj: dict = {"id": f"local:{path}"}
        else:
            with open(path, "rb") as f:
                r = await self.client.post(
                    f"{_graph()}/{_env('WA_PHONE_NUMBER_ID')}/media",
                    headers=self._headers(),
                    data={"messaging_product": "whatsapp", "type": mime},
                    files={"file": (Path(path).name, f, mime)},
                )
            r.raise_for_status()
            media_obj = {"id": r.json()["id"]}
        if caption and kind in ("image", "document", "video"):
            media_obj["caption"] = caption[:1024]
        if kind == "document":
            media_obj["filename"] = Path(path).name
        return await self._post(to, {"type": kind, kind: media_obj})

    async def download_media(self, media: Media) -> str:
        ext = mimetypes.guess_extension(media.mime.split(";")[0].strip()) or ""
        if media.mime.startswith("audio/ogg"):
            ext = ".ogg"
        dest = storage_dir() / "inbound" / f"{uuid.uuid4().hex[:10]}{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if media.media_id.startswith("sim-"):
            from app.demo import sim_media_path  # backend-core simulator uploads

            shutil.copyfile(sim_media_path(media.media_id), dest)
        elif media.media_id.startswith("local:"):
            src = Path(media.media_id[len("local:") :])
            if not src.is_absolute() and not src.exists():
                # repo-relative paths from the simulator (cwd is usually backend/)
                alt = Path(__file__).resolve().parents[3] / src
                src = alt if alt.exists() else src
            shutil.copyfile(src, dest)
        else:
            r = await self.client.get(f"{_graph()}/{media.media_id}", headers=self._headers())
            r.raise_for_status()
            url = r.json()["url"]
            r2 = await self.client.get(url, headers=self._headers())
            r2.raise_for_status()
            dest.write_bytes(r2.content)
        media.local_path = str(dest)
        return str(dest)


channel = WhatsAppChannel()
register(channel)


# ------------------------------------------------------------------ webhook parsing
def parse_webhook(body: dict) -> list[InboundMessage]:
    """Turns a Meta webhook body into normalized messages. Ignores status updates."""
    out: list[InboundMessage] = []
    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts", [])}
            for st in value.get("statuses", []):
                log.debug("status %s for %s", st.get("status"), st.get("id"))
            for m in value.get("messages", []):
                msg = InboundMessage(
                    channel="whatsapp",
                    from_phone=normalize_phone(m.get("from", "")),
                    wa_message_id=m.get("id"),
                    profile_name=names.get(m.get("from")),
                )
                t = m.get("type")
                if t == "text":
                    msg.text = m["text"].get("body")
                elif t == "interactive":
                    it = m["interactive"]
                    reply = it.get("button_reply") or it.get("list_reply") or {}
                    msg.button_id = reply.get("id")
                    msg.button_title = reply.get("title")
                elif t == "button":  # template quick-reply
                    msg.button_id = m["button"].get("payload")
                    msg.button_title = m["button"].get("text")
                elif t in ("audio", "image", "document", "video", "sticker"):
                    obj = m[t]
                    msg.media.append(
                        Media(
                            media_id=obj["id"],
                            mime=obj.get("mime_type", "application/octet-stream"),
                            filename=obj.get("filename"),
                            caption=obj.get("caption"),
                        )
                    )
                    msg.text = obj.get("caption")
                else:
                    msg.text = None
                    log.info("unsupported WhatsApp message type %s", t)
                out.append(msg)
    return out


def verify_signature(raw: bytes, header: str | None) -> bool:
    secret = _env("WA_APP_SECRET")
    if not secret:
        return True  # local dev / simulator without a Meta app
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256=") :])


async def process_inbound(msg: InboundMessage) -> None:
    from app import router as msg_router  # late import: router imports agent, services

    try:
        await msg_router.handle_inbound(msg)
    except Exception:  # never let a background task die silently
        log.exception("failed to handle inbound %s", msg.wa_message_id)


# ------------------------------------------------------------------ FastAPI routes
router = APIRouter(tags=["whatsapp"])


@router.get("/webhooks/whatsapp")
async def verify(
    hub_mode: str = Query("", alias="hub.mode"),
    hub_verify_token: str = Query("", alias="hub.verify_token"),
    hub_challenge: str = Query("", alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token and hub_verify_token == _env("WA_VERIFY_TOKEN"):
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="verification failed")


@router.post("/webhooks/whatsapp")
async def webhook(request: Request, background: BackgroundTasks):
    raw = await request.body()
    if not verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="bad signature")
    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return {"ok": True}
    for msg in parse_webhook(body):
        if already_seen(msg.wa_message_id):
            log.info("duplicate %s ignored", msg.wa_message_id)
            continue
        remember(msg.from_phone, "whatsapp")
        background.add_task(process_inbound, msg)
    return {"ok": True}  # 200 immediately; processing runs after the response


@router.get("/webhooks/whatsapp/_outbox")
async def get_outbox(since: int = 0):
    if _env("DEMO_MODE") != "1":
        raise HTTPException(status_code=404)
    return {"fake_send": fake_send_enabled(), "messages": outbox(since)}
