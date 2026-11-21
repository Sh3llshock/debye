"""Tenant web portal channel ("web"): the same Debye as on WhatsApp, in the browser.

Mount with:  from app.channels.web import router as web_router

Inbound web messages go through the same router and agent as WhatsApp
(`app.router.handle_inbound`), so the conversation state and cases are shared. While
the web is the contact's last-used channel, Debye's replies (and later updates from
staff or the partner) are delivered here: they are stored as Message rows like every
other message, and the page picks them up from GET /api/tenant/messages, nudged by
the existing SSE stream (/api/stream, message.out with contact_id).

Interactive questions (buttons / lists) are kept per outbound message id, so the page
can render them as tappable chips.

Demo login: email or phone of a seeded tenant/owner, any non-empty password.
WEB_MIRROR_WHATSAPP=1 also sends every web reply to the contact's WhatsApp (off by default).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import re
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlmodel import or_, select

from .base import (
    MAX_BUTTON_TITLE,
    MAX_BUTTONS,
    MAX_LIST_ROWS,
    MAX_ROW_TITLE,
    Channel,
    InboundMessage,
    Media,
    clamp_options,
    get_channel,
    normalize_phone,
    register,
    remember,
    storage_dir,
)

log = logging.getLogger("debye.web")

CHANNEL = "web"
TENANT_ROLES = ("tenant", "owner")


# ------------------------------------------------------------------ channel
class _Frames:
    """Interactive extras per outbound message id (options, list label), kept on disk so the
    chips survive a restart. Plain text is in the Message table already."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, dict] | None = None

    def _path(self) -> Path:
        return storage_dir() / "web_frames.json"

    def _load(self) -> dict[str, dict]:
        if self._data is None:
            try:
                self._data = json.loads(self._path().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._data = {}
        return self._data

    def put(self, mid: str, frame: dict) -> None:
        with self._lock:
            data = self._load()
            data[mid] = frame
            if len(data) > 2000:  # keep the file small
                for k in list(data)[: len(data) - 2000]:
                    data.pop(k, None)
            try:
                self._path().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            except OSError:
                log.warning("could not write web_frames.json")

    def get(self, mid: str | None) -> dict | None:
        if not mid:
            return None
        with self._lock:
            return self._load().get(mid)

    def clear(self) -> None:
        with self._lock:
            self._data = {}
            try:
                self._path().unlink(missing_ok=True)
            except OSError:
                pass


frames = _Frames()


def _mirror() -> Channel | None:
    if os.getenv("WEB_MIRROR_WHATSAPP") != "1":
        return None
    try:
        return get_channel("whatsapp")
    except KeyError:
        return None


class WebChannel(Channel):
    """Outbound: nothing to push over a socket; the Message row (logged by agent.outbound) is the
    delivery. We only return an id and remember the interactive extras for that id."""

    name = CHANNEL

    def _id(self) -> str:
        return f"web.{uuid.uuid4().hex[:12]}"

    async def _mirror(self, method: str, *args) -> None:
        ch = _mirror()
        if ch is None:
            return
        try:
            await getattr(ch, method)(*args)
        except Exception:
            log.exception("WhatsApp mirror of a web reply failed")

    async def send_text(self, to, text):
        await self._mirror("send_text", to, text)
        return self._id()

    async def send_buttons(self, to, text, options):
        mid = self._id()
        opts = clamp_options(options, MAX_BUTTONS, MAX_BUTTON_TITLE)
        frames.put(mid, {"type": "buttons", "text": text, "options": [{"id": o.id, "title": o.title} for o in opts]})
        await self._mirror("send_buttons", to, text, options)
        return mid

    async def send_list(self, to, text, button_label, rows, section_title="Optionen"):
        mid = self._id()
        rs = clamp_options(rows, MAX_LIST_ROWS, MAX_ROW_TITLE)
        frames.put(
            mid,
            {"type": "list", "text": text, "button": button_label, "options": [{"id": r.id, "title": r.title} for r in rs]},
        )
        await self._mirror("send_list", to, text, button_label, rows, section_title)
        return mid

    async def send_media(self, to, kind, path, caption=None, mime=None):
        mid = self._id()
        frames.put(mid, {"type": "media", "kind": kind, "caption": caption, "name": Path(path).name})
        await self._mirror("send_media", to, kind, path, caption, mime)
        return mid

    async def download_media(self, media: Media) -> str:
        # Uploads are saved on receipt; media_id is the local path.
        media.local_path = media.local_path or media.media_id
        return media.local_path


channel = WebChannel()
register(channel)


# ------------------------------------------------------------------ auth (demo)
def _secret() -> bytes:
    return (os.getenv("TENANT_PORTAL_SECRET") or "debye-tenant-portal-demo").encode()


def make_token(contact_id: str) -> str:
    sig = hmac.new(_secret(), contact_id.encode(), hashlib.sha256).hexdigest()[:32]
    raw = f"{contact_id}.{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def contact_from_token(token: str | None):
    from app.db import get_session
    from app.models import Contact

    if not token:
        return None
    token = token.removeprefix("Bearer ").strip()
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
        cid, sig = raw.rsplit(".", 1)
    except Exception:
        return None
    good = hmac.new(_secret(), cid.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, good):
        return None
    with get_session() as s:
        c = s.get(Contact, cid)
    return c if c and c.role in TENANT_ROLES else None


def _require(authorization: str | None):
    c = contact_from_token(authorization)
    if c is None:
        raise HTTPException(401, "not logged in")
    return c


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def find_contact(login: str):
    """Email (case-insensitive) or phone (spaces, dashes, 00/+ ignored) of a tenant or owner."""
    from app.db import get_session
    from app.models import Contact

    login = (login or "").strip()
    if not login:
        return None
    with get_session() as s:
        rows = s.exec(select(Contact).where(Contact.role.in_(TENANT_ROLES))).all()  # type: ignore[attr-defined]
    if "@" in login:
        low = login.lower()
        return next((c for c in rows if (c.email or "").lower() == low), None)
    d = _digits(login)
    if d.startswith("00"):
        d = d[2:]
    if len(d) < 6:
        return None
    return next((c for c in rows if c.phone_e164 and _digits(c.phone_e164) == d), None)


# ------------------------------------------------------------------ views
def _first_name(name: str) -> str:
    return (name or "").split(" ")[0]


def _contact_view(c) -> dict:
    return {"contact_id": c.id, "name": c.name, "first_name": _first_name(c.name), "email": c.email,
            "phone": c.phone_e164, "language": c.language, "unit_id": c.unit_id, "role": c.role}


def _home_view(s, c) -> dict | None:
    from app.models import Asset, Contact, Contract, Property, Unit

    if not c.unit_id:
        return None
    u = s.get(Unit, c.unit_id)
    if not u:
        return None
    p = s.get(Property, u.property_id)
    assets = s.exec(select(Asset).where(Asset.property_id == u.property_id,
                                        or_(Asset.unit_id == u.id, Asset.unit_id == None))).all()  # noqa: E711
    assets.sort(key=lambda a: a.unit_id is None)  # the flat's own appliance first
    owner = None
    lease = s.exec(select(Contract).where(Contract.unit_id == u.id, Contract.type == "lease")).first()
    owner_id = (lease.data or {}).get("owner_contact_id") if lease else None
    if owner_id:
        o = s.get(Contact, owner_id)
        owner = o.name if o else None
    if owner is None:
        o = s.exec(select(Contact).where(Contact.role == "owner")).first()
        owner = o.name if o else None
    return {
        "unit_id": u.id, "floor": u.floor, "rooms": u.rooms, "size_sqm": u.size_sqm,
        "address": p.address if p else None, "postcode": p.postcode if p else None, "city": p.city if p else None,
        "landlord": owner,
        "assets": [{"asset_id": a.id, "type": a.type, "make": a.make, "model": a.model, "installed": a.installed,
                    "last_service": a.last_service, "central": a.unit_id is None} for a in assets],
    }


def _pending(contact_id: str) -> dict | None:
    from app.agent import state as st

    conv = st.conversation(contact_id)
    if not conv.pending_options:
        return None
    return {"question": conv.pending_question,
            "options": [{"id": o.id, "title": o.title} for o in conv.pending_options]}


def _case_ids_for(s, contact_id: str) -> list[str]:
    from app.models import Case, CaseContact

    ids = {r.case_id for r in s.exec(select(CaseContact).where(CaseContact.contact_id == contact_id)).all()}
    ids |= {c.id for c in s.exec(select(Case).where(Case.reporter_contact_id == contact_id)).all()}
    return sorted(ids)


CLOSED_STATUSES = ("closed",)  # "invoiced" still waits for the tenant's "is it fixed?"


def _case_view(s, case, contact_id: str, full: bool = False) -> dict:
    """Tenant-safe view: no ranking, no other tenants' messages, no internal approval rules."""
    from app import services
    from app.models import Asset, CaseEvent, Document, Partner

    data = case.data or {}
    pid = case.partner_id or data.get("pending_partner_id") or ((data.get("ranking") or [{}])[0].get("partner_id"))
    partner = s.get(Partner, pid) if pid else None
    tech = data.get("technician") or {}
    diag = data.get("diagnosis") or {}
    approval = data.get("approval") or {}
    out = {
        "case_id": case.id, "title": case.title, "status": case.status, "priority": case.priority,
        "type": case.type, "created_at": case.created_at, "updated_at": case.updated_at,
        "closed_at": case.closed_at, "closed": case.status in CLOSED_STATUSES,
        "resolution": data.get("resolution"),
        "error_code": case.error_code, "error_label": services.error_label(case.error_code),
        "partner_name": (partner.manifest or {}).get("name") if partner else None,
        "technician_name": tech.get("name"),
        "slot": {"start": case.slot_start, "end": case.slot_end} if case.slot_start else None,
        "approval": {"required": bool(approval.get("required")), "granted": bool(approval.get("granted")),
                     "rejected": bool(approval.get("rejected"))},
        "diagnosis": {"label": diag.get("label"), "confidence": diag.get("confidence"),
                      "outcome": diag.get("outcome")} if diag else None,
    }
    if full:
        asset = s.get(Asset, case.asset_id) if case.asset_id else None
        docs = s.exec(select(Document).where(Document.case_id == case.id)).all()
        events = s.exec(select(CaseEvent).where(CaseEvent.case_id == case.id)
                        .order_by(CaseEvent.ts, CaseEvent.id)).all()
        out.update({
            "summary": case.summary,
            "asset": {"type": asset.type, "make": asset.make, "model": asset.model,
                      "last_service": asset.last_service} if asset else None,
            "proposed_slots": data.get("proposed_slots") or [],
            "documents": [{"document_id": d.id, "kind": d.kind, "filename": d.filename, "mime": d.mime,
                           "url": f"/files/{d.id}"} for d in docs if d.kind in ("photo", "report", "invoice")],
            "completion": {"notes": (data.get("completion") or {}).get("notes")} if data.get("completion") else None,
            "events": [{"ts": e.ts, "actor": e.actor, "kind": e.kind} for e in events],
            "first_channel": None,
        })
    return out


def _messages(s, contact_id: str, case_id: str | None) -> list[dict]:
    from app.models import Document, Message

    q = select(Message).where(Message.contact_id == contact_id)
    q = q.where(Message.case_id == case_id) if case_id else q.where(Message.case_id == None)  # noqa: E711
    rows = s.exec(q.order_by(Message.ts, Message.id)).all()
    out = []
    for m in rows:
        fr = frames.get(m.wa_message_id) if m.direction == "out" else None
        media = []
        for d_id in m.media_ids or []:
            d = s.get(Document, d_id) if isinstance(d_id, str) else None
            if d:
                media.append({"document_id": d.id, "url": f"/files/{d.id}", "mime": d.mime, "kind": d.kind})
        text = m.text
        if fr and fr.get("type") in ("buttons", "list"):
            text = fr.get("text") or text
        out.append({
            "id": m.id, "ts": m.ts, "direction": m.direction, "channel": m.channel, "text": text,
            "options": (fr or {}).get("options") or [], "list_button": (fr or {}).get("button"),
            "media": media,
        })
    return out


# ------------------------------------------------------------------ API
router = APIRouter(prefix="/api/tenant", tags=["tenant"])


class LoginBody(BaseModel):
    login: str
    password: str = ""


def _demo_creds() -> tuple[str, str]:
    """Shared demo login for a hosted demo (env only, never in the repo). Unset = old behaviour."""
    return os.environ.get("DEMO_LOGIN", "").strip(), os.environ.get("DEMO_PASSWORD", "")


@router.post("/login")
def login(body: LoginBody) -> dict:
    demo_login, demo_pw = _demo_creds()
    if demo_login and (body.login or "").strip() == demo_login:
        if not hmac.compare_digest(body.password or "", demo_pw):
            raise HTTPException(401, "wrong password")
        c = find_contact(os.environ.get("DEMO_TENANT", "jonas@example.com"))
        if c is None:
            raise HTTPException(404, "demo tenant not found")
        return {"token": make_token(c.id), "contact": _contact_view(c)}
    c = find_contact(body.login)
    if c is None:
        raise HTTPException(404, "no tenancy with that email or phone number")
    if not (body.password or "").strip():
        raise HTTPException(400, "password required")
    if demo_pw and not hmac.compare_digest(body.password, demo_pw):
        raise HTTPException(401, "wrong password")
    return {"token": make_token(c.id), "contact": _contact_view(c)}


auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


@auth_router.post("/partner-login")
def partner_login(body: LoginBody) -> dict:
    """Server-side check for the partner login page. {"demo": {...}} for the shared demo login,
    {"demo": null} to let the page look the partner up itself; 401 on a wrong password."""
    demo_login, demo_pw = _demo_creds()
    if demo_pw and not hmac.compare_digest(body.password or "", demo_pw):
        raise HTTPException(401, "wrong password")
    if demo_login and (body.login or "").strip() == demo_login:
        pid = os.environ.get("DEMO_PARTNER", "heizung-schmidt")
        return {"demo": {"to": f"/partner/{pid}", "pid": pid}}
    return {"demo": None}


@router.get("/me")
def me(authorization: str | None = Header(default=None)) -> dict:
    from app.agent import state as st
    from app.db import get_session

    c = _require(authorization)
    conv = st.conversation(c.id)
    with get_session() as s:
        home = _home_view(s, c)
    return {"contact": _contact_view(c), "home": home,
            "conversation": {"case_id": conv.case_id, "step": conv.step, "pending": _pending(c.id)}}


@router.get("/cases")
def my_cases(authorization: str | None = Header(default=None)) -> list[dict]:
    from app.db import get_session
    from app.models import Case

    c = _require(authorization)
    with get_session() as s:
        cases = [s.get(Case, i) for i in _case_ids_for(s, c.id)]
        views = [_case_view(s, k, c.id) for k in cases if k]
    views.sort(key=lambda v: v["created_at"] or "", reverse=True)
    return views


@router.get("/cases/{case_id}")
def my_case(case_id: str, authorization: str | None = Header(default=None)) -> dict:
    from app.db import get_session
    from app.models import Case, Message

    c = _require(authorization)
    with get_session() as s:
        if case_id not in _case_ids_for(s, c.id):
            raise HTTPException(404, "case not found")
        case = s.get(Case, case_id)
        view = _case_view(s, case, c.id, full=True)
        first = s.exec(select(Message).where(Message.case_id == case_id, Message.contact_id == c.id,
                                             Message.direction == "in").order_by(Message.ts, Message.id)).first()
        view["first_channel"] = first.channel if first else None
    return view


@router.get("/messages")
def history(
    case_id: str | None = Query(default=None, description="a case id, or omit for the current conversation"),
    authorization: str | None = Header(default=None),
) -> dict:
    """Messages of one case (both channels), or of the current conversation: the contact's current
    case if the agent has one, else the messages not linked to any case yet."""
    from app.agent import state as st
    from app.db import get_session

    c = _require(authorization)
    conv = st.conversation(c.id)
    with get_session() as s:
        if case_id and case_id not in _case_ids_for(s, c.id):
            raise HTTPException(404, "case not found")
        cid = case_id or conv.case_id
        msgs = _messages(s, c.id, cid)
    current = (cid or None) == (conv.case_id or None)
    if not current and cid and not conv.case_id:
        # after a restart the agent's state is gone: treat the tenant's newest open case as current
        from app.models import Case

        with get_session() as s:
            open_ids = [k.id for k in (s.get(Case, i) for i in _case_ids_for(s, c.id))
                        if k and k.status not in CLOSED_STATUSES]
        current = bool(open_ids) and cid == max(open_ids)
    pending = _pending(c.id) if current else None
    if current and pending is None and msgs and msgs[-1]["direction"] == "out" and msgs[-1]["options"]:
        # agent state is in memory; after a restart the last question's chips still work
        # (button ids carry the case id, so the router handles them without that state)
        pending = {"question": msgs[-1]["text"], "options": msgs[-1]["options"]}
    return {"case_id": cid, "current": current, "messages": msgs, "pending": pending}


_tasks: set[asyncio.Task] = set()


def _save_upload(f: UploadFile) -> Media:
    data = f.file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "file too large")
    mime = (f.content_type or mimetypes.guess_type(f.filename or "")[0] or "application/octet-stream").split(";")[0]
    if not (mime.startswith("image/") or mime.startswith("audio/") or mime == "application/pdf"):
        raise HTTPException(415, "photos, voice notes or PDFs only")
    ext = Path(f.filename or "").suffix.lower() or (mimetypes.guess_extension(mime) or "")
    dest = storage_dir() / "inbound" / f"web_{uuid.uuid4().hex[:10]}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return Media(media_id=str(dest), mime=mime, filename=f.filename or dest.name, local_path=str(dest))


def _restore_case_from_button(contact_id: str, button_id: str | None) -> None:
    """Agent state lives in memory. After a restart a chip tap like `fixed_yes:case_0010` would be
    logged without a case (the router logs before it reads the id), so it vanished from the case
    thread. Point the conversation back at that case first, if it is one of this tenant's."""
    if not button_id:
        return
    from app import router as msg_router
    from app.agent import state as st
    from app.db import get_session

    m = msg_router.BUTTON_RE.match(button_id)
    case_id = m.group("case") if m else None
    conv = st.conversation(contact_id)
    if not case_id or case_id == "new" or conv.case_id:
        return
    with get_session() as s:
        if case_id in _case_ids_for(s, contact_id):
            conv.case_id = case_id


@router.post("/messages")
async def send(
    text: str | None = Form(default=None),
    button_id: str | None = Form(default=None),
    button_title: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    wait: bool = Query(default=False, description="answer only after Debye's turn (tests, scripts)"),
    authorization: str | None = Header(default=None),
) -> dict:
    """Text, a chip tap (button_id + button_title) and/or one photo. Debye answers asynchronously;
    the reply shows up in GET /messages (the SSE stream announces it as message.out)."""
    from app import router as msg_router

    c = _require(authorization)
    if not c.phone_e164:
        raise HTTPException(409, "this contact has no phone number on file")
    text = (text or "").strip() or None
    msg = InboundMessage(channel=CHANNEL, from_phone=normalize_phone(c.phone_e164),
                         wa_message_id=f"web.in.{uuid.uuid4().hex}", text=text,
                         button_id=(button_id or None), button_title=(button_title or None),
                         profile_name=c.name)
    if file is not None and (file.filename or file.size):
        msg.media.append(_save_upload(file))
    if not (msg.text or msg.button_id or msg.media):
        raise HTTPException(400, "empty message")
    remember(msg.from_phone, CHANNEL)  # replies and later updates come to the web page
    _restore_case_from_button(c.id, msg.button_id)

    async def run() -> None:
        try:
            await msg_router.handle_inbound(msg)
        except Exception:
            log.exception("web inbound failed")

    if wait:
        await run()
    else:
        t = asyncio.create_task(run())
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)
    return {"ok": True, "id": msg.wa_message_id}
