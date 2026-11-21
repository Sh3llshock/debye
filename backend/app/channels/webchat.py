"""WhatsApp-lookalike web chat over WebSocket: hidden stage fallback.

Mount with:  from app.channels.webchat import router as webchat_router
Open /chat/{contact_id} (e.g. /chat/c_202) in a phone browser after logging in at /tenant as that
tenant (the socket needs their tenant token). Same router,
same agent; replies go here while this is the contact's last-used channel.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import mimetypes
import uuid
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from .base import (
    MAX_BUTTON_TITLE,
    MAX_BUTTONS,
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

log = logging.getLogger("debye.webchat")


class WebChatChannel(Channel):
    name = "webchat"

    def __init__(self) -> None:
        self.sockets: dict[str, set[WebSocket]] = defaultdict(set)  # phone -> sockets

    async def _send(self, to: str, frame: dict) -> str:
        frame["id"] = f"web.{uuid.uuid4().hex[:10]}"
        dead = []
        for ws in list(self.sockets.get(normalize_phone(to), ())):
            try:
                await ws.send_text(json.dumps(frame, ensure_ascii=False))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.sockets[normalize_phone(to)].discard(ws)
        return frame["id"]

    async def send_text(self, to, text):
        return await self._send(to, {"type": "text", "text": text})

    async def send_buttons(self, to, text, options):
        opts = clamp_options(options, MAX_BUTTONS, MAX_BUTTON_TITLE)
        return await self._send(
            to, {"type": "buttons", "text": text, "options": [{"id": o.id, "title": o.title} for o in opts]}
        )

    async def send_list(self, to, text, button_label, rows, section_title="Optionen"):
        rs = clamp_options(rows, MAX_LIST_ROWS, MAX_ROW_TITLE)
        return await self._send(
            to,
            {
                "type": "list",
                "text": text,
                "button": button_label,
                "rows": [{"id": r.id, "title": r.title} for r in rs],
            },
        )

    async def send_media(self, to, kind, path, caption=None, mime=None):
        return await self._send(to, {"type": "media", "kind": kind, "name": Path(path).name, "caption": caption})

    async def download_media(self, media: Media) -> str:
        # Webchat uploads are saved on receipt; media_id is already a local path.
        media.local_path = media.local_path or media.media_id
        return media.local_path


channel = WebChatChannel()
register(channel)

router = APIRouter(tags=["webchat"])


def _save_data_url(data_url: str) -> Media | None:
    try:
        header, b64 = data_url.split(",", 1)
        mime = header.split(";")[0].removeprefix("data:") or "application/octet-stream"
        raw = base64.b64decode(b64)
    except (ValueError, binascii.Error):
        return None
    ext = mimetypes.guess_extension(mime) or ""
    dest = storage_dir() / "inbound" / f"web_{uuid.uuid4().hex[:10]}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return Media(media_id=str(dest), mime=mime, local_path=str(dest))


@router.websocket("/ws/chat/{contact_id}")
async def chat_socket(ws: WebSocket, contact_id: str):
    from app import auth
    from app import router as msg_router
    from app.agent import _backend as be

    # only the tenant themself: a tenant token (?token=, from the tenant portal login) for this contact
    who = auth.read_token(ws.query_params.get("token"))
    if who is None or who.role != "tenant" or who.sub != contact_id:
        await ws.close(code=4401)
        return
    await ws.accept()
    contact = be.get_contact(contact_id)
    phone = be.attr(contact, "phone_e164")
    if not phone:
        await ws.send_text(json.dumps({"type": "text", "text": "Unbekannter Kontakt."}))
        await ws.close()
        return
    phone = normalize_phone(phone)
    channel.sockets[phone].add(ws)
    try:
        while True:
            data = json.loads(await ws.receive_text())
            msg = InboundMessage(channel="webchat", from_phone=phone, wa_message_id=f"web.{uuid.uuid4().hex}")
            msg.text = data.get("text") or None
            msg.button_id = data.get("button_id")
            msg.button_title = data.get("title")
            if data.get("file"):
                m = _save_data_url(data["file"])
                if m:
                    msg.media.append(m)
            remember(phone, "webchat")
            try:
                await msg_router.handle_inbound(msg)
            except Exception:
                log.exception("webchat inbound failed")
    except WebSocketDisconnect:
        pass
    finally:
        channel.sockets[phone].discard(ws)


@router.get("/chat/{contact_id}", response_class=HTMLResponse, include_in_schema=False)
async def chat_page(contact_id: str):
    import re

    from fastapi import HTTPException

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", contact_id):  # it is written into the page
        raise HTTPException(404, "not found")
    return HTMLResponse(_PAGE.replace("__CONTACT__", contact_id))


_PAGE = """<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Debye</title>
<style>
:root{--bg:#efeae2;--out:#d9fdd3;--in:#fff;--bar:#008069;--txt:#111b21;--sub:#667781;--btn:#027eb5}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--txt);height:100dvh;display:flex;flex-direction:column}
header{background:var(--bar);color:#fff;padding:12px 16px;display:flex;gap:12px;align-items:center}
header .av{width:38px;height:38px;border-radius:50%;background:#fff3;display:grid;place-items:center;font-weight:700}
header small{display:block;opacity:.8;font-size:12px}
#log{flex:1;overflow-y:auto;padding:12px 10px;display:flex;flex-direction:column;gap:6px}
.b{max-width:82%;padding:7px 10px;border-radius:8px;white-space:pre-wrap;line-height:1.35;font-size:15px;box-shadow:0 1px .5px #0002}
.in{background:var(--in);align-self:flex-start}.out{background:var(--out);align-self:flex-end}
.acts{display:flex;flex-direction:column;gap:1px;margin-top:6px;border-top:1px solid #0001}
.acts button{background:none;border:0;color:var(--btn);padding:8px;font-size:15px;cursor:pointer}
.acts button:disabled{color:var(--sub)}
form{display:flex;gap:8px;padding:8px;background:#f0f2f5}
input[type=text]{flex:1;border:0;border-radius:20px;padding:10px 14px;font-size:15px}
form button,label.att{border:0;background:var(--bar);color:#fff;border-radius:50%;width:42px;height:42px;font-size:18px;cursor:pointer;display:grid;place-items:center}
</style></head><body>
<header><div class="av">D</div><div>Debye<small>AI assistant · reltix</small></div></header>
<div id="log"></div>
<form id="f"><label class="att" title="Foto">📷<input id="file" type="file" accept="image/*,application/pdf" hidden></label>
<input id="t" type="text" placeholder="Nachricht" autocomplete="off"><button>➤</button></form>
<script>
const log=document.getElementById('log');const proto=location.protocol==='https:'?'wss':'ws';
const tok=localStorage.getItem('debye-tenant-token');if(!tok)location.href='/tenant';
let ws;function connect(){ws=new WebSocket(`${proto}://${location.host}/ws/chat/__CONTACT__?token=${encodeURIComponent(tok||'')}`);ws.onmessage=e=>render(JSON.parse(e.data));ws.onclose=()=>setTimeout(connect,1500)}connect();
function bubble(cls,text){const d=document.createElement('div');d.className='b '+cls;d.textContent=text;log.appendChild(d);log.scrollTop=1e9;return d}
function send(obj,shown){ws.send(JSON.stringify(obj));bubble('out',shown)}
function render(m){const d=bubble('in',m.text||m.caption||('['+(m.kind||'')+'] '+(m.name||'')));
 const opts=m.options||m.rows;if(!opts)return;const a=document.createElement('div');a.className='acts';
 if(m.type==='list'){const h=document.createElement('div');h.style.cssText='color:#667781;font-size:13px;padding:4px 8px';h.textContent='☰ '+(m.button||'Auswählen');a.appendChild(h)}
 opts.forEach(o=>{const b=document.createElement('button');b.textContent=o.title;b.onclick=()=>{a.querySelectorAll('button').forEach(x=>x.disabled=true);send({button_id:o.id,title:o.title},o.title)};a.appendChild(b)});d.appendChild(a);log.scrollTop=1e9}
document.getElementById('f').onsubmit=e=>{e.preventDefault();const t=document.getElementById('t');if(!t.value.trim())return;send({text:t.value},t.value);t.value=''};
document.getElementById('file').onchange=e=>{const f=e.target.files[0];if(!f)return;const r=new FileReader();r.onload=()=>send({file:r.result},'📎 '+f.name);r.readAsDataURL(f);e.target.value=''};
</script></body></html>"""
