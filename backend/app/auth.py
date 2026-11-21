"""Demo sessions for the portals: signed, expiring tokens with a role, checked on the server.

Roles:  tenant (sub = contact id)  ·  staff (sub = property-manager contact id)
        partner (pid = partner id) ·  tech (sub = technician id, pid = their partner)

Login stays a demo (any non-empty password), but WHO you are and WHAT you may touch is enforced
here: a partner token only opens its own partner's jobs, a tenant token only that tenant's cases.

Token = base64url(JSON payload) "." base64url(HMAC-SHA256(payload)). Payload: sub, role, pid?, exp.
Secret: TENANT_TOKEN_SECRET (set it in .env so sessions and file links survive a restart); if it is
unset a random secret is generated per process (everyone logs in again after a restart).

Files are served only with a signed link (/files/<id>?exp=…&sig=…), which the API hands out to
people who may see that case, or with a token whose owner may see the document's case.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request
from pydantic import BaseModel
from sqlmodel import select

log = logging.getLogger("debye.auth")

ROLES = ("tenant", "staff", "partner", "tech")
TOKEN_TTL = int(float(os.getenv("TOKEN_TTL_HOURS", "12")) * 3600)
FILE_TTL = int(float(os.getenv("FILE_LINK_TTL_HOURS", "24")) * 3600)

_process_secret = secrets.token_bytes(32)
_warned = False


def _secret() -> bytes:
    global _warned
    raw = os.getenv("TENANT_TOKEN_SECRET")
    if raw:
        return raw.encode()
    if not _warned:
        log.warning("TENANT_TOKEN_SECRET is not set: using a random per-process secret "
                    "(sessions and file links end when the server restarts)")
        _warned = True
    return _process_secret


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(data: bytes) -> str:
    return _b64(hmac.new(_secret(), data, hashlib.sha256).digest())


# ------------------------------------------------------------------ tokens
@dataclass(frozen=True)
class Principal:
    role: str
    sub: str
    pid: str | None = None

    @property
    def contact_id(self) -> str | None:
        return self.sub if self.role in ("tenant", "staff") else None


def make_token(role: str, sub: str, pid: str | None = None, ttl: int | None = None) -> str:
    assert role in ROLES
    payload = {"sub": sub, "role": role, "exp": int(time.time()) + (ttl or TOKEN_TTL)}
    if pid:
        payload["pid"] = pid
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return f"{_b64(body)}.{_sign(body)}"


def read_token(token: str | None) -> Principal | None:
    if not token:
        return None
    token = token.strip().removeprefix("Bearer ").strip()
    try:
        body_b64, sig = token.split(".", 1)
        body = _unb64(body_b64)
        if not hmac.compare_digest(sig, _sign(body)):
            return None
        p = json.loads(body)
        if p.get("role") not in ROLES or int(p.get("exp", 0)) < time.time() or not p.get("sub"):
            return None
        return Principal(role=p["role"], sub=str(p["sub"]), pid=p.get("pid"))
    except Exception:
        return None


def principal_from(request: Request) -> Principal | None:
    """Authorization: Bearer <token>, or ?token= (EventSource, WebSocket and <img> cannot set headers)."""
    return read_token(request.headers.get("authorization") or request.query_params.get("token"))


def require(request: Request, *roles: str) -> Principal:
    p = principal_from(request)
    if p is None:
        raise HTTPException(401, "login required")
    if roles and p.role not in roles:
        raise HTTPException(403, "not allowed for this account")
    return p


def staff_only(request: Request) -> Principal:
    """FastAPI dependency for the property-management API."""
    return require(request, "staff")


def require_partner(request: Request, partner_id: str) -> Principal:
    p = require(request, "partner", "staff")
    if p.role == "partner" and p.pid != partner_id:
        raise HTTPException(403, "this is another partner's account")
    return p


def require_tech(request: Request, tech_id: str) -> Principal:
    """The technician themself, or their own company (partner token)."""
    from app.db import get_session
    from app.models import Technician

    p = require(request, "tech", "partner", "staff")
    if p.role == "tech" and p.sub != tech_id:
        raise HTTPException(403, "this is another technician's account")
    if p.role == "partner":
        with get_session() as s:
            t = s.get(Technician, tech_id)
        if not t or t.partner_id != p.pid:
            raise HTTPException(403, "this technician works for another partner")
    return p


# ------------------------------------------------------------------ who may see a case
def tenant_case_ids(s, contact_id: str) -> set[str]:
    from app.models import Case, CaseContact

    ids = {r.case_id for r in s.exec(select(CaseContact).where(CaseContact.contact_id == contact_id)).all()}
    ids |= {c.id for c in s.exec(select(Case).where(Case.reporter_contact_id == contact_id)).all()}
    return ids


def can_see_case(s, p: Principal, case) -> bool:
    if case is None:
        return False
    if p.role == "staff":
        return True
    data = case.data or {}
    if p.role == "partner":
        return case.partner_id == p.pid or p.pid in (data.get("declined_by") or []) \
            or data.get("pending_partner_id") == p.pid
    if p.role == "tech":
        return (data.get("technician") or {}).get("tech_id") == p.sub
    if p.role == "tenant":
        return case.id in tenant_case_ids(s, p.sub)
    return False


def can_see_event(p: Principal, message: dict) -> bool:
    """SSE filter: staff see everything, others only their own cases / own chat messages."""
    if p.role == "staff":
        return True
    kind = message.get("type") or ""
    ev = message.get("event") or {}
    case_id = message.get("case_id")
    if kind == "demo.reset":
        return True
    if kind.startswith("message."):
        # chat lines are the tenant's own; partners and technicians do not get them
        return p.role == "tenant" and ev.get("contact_id") == p.sub
    if not case_id:
        return False
    from app.db import get_session
    from app.models import Case

    try:
        with get_session() as s:
            return can_see_case(s, p, s.get(Case, case_id))
    except Exception:
        return False


# ------------------------------------------------------------------ signed file links
def file_sig(doc_id: str, exp: int) -> str:
    return _sign(f"file:{doc_id}:{exp}".encode())


def file_url(doc_id: str, ttl: int | None = None) -> str:
    """Link to /files/<id> that works for FILE_LINK_TTL_HOURS. Only hand it to people who may see it."""
    exp = int(time.time()) + (ttl or FILE_TTL)
    return f"/files/{doc_id}?exp={exp}&sig={file_sig(doc_id, exp)}"


def file_link_ok(doc_id: str, exp: str | None, sig: str | None) -> bool:
    try:
        e = int(exp or 0)
    except ValueError:
        return False
    return bool(sig) and e >= time.time() and hmac.compare_digest(sig, file_sig(doc_id, e))


def sign_media(items: list[dict]) -> list[dict]:
    """Replace "url" of media/document dicts by a signed link (helper for API views)."""
    out = []
    for m in items:
        d = dict(m)
        if d.get("document_id"):
            d["url"] = file_url(d["document_id"])
        out.append(d)
    return out


# ------------------------------------------------------------------ demo login (any password)
def _digits(s: str | None) -> str:
    d = re.sub(r"\D", "", s or "")
    return d[2:] if d.startswith("00") else d


def _phone_eq(a: str | None, b: str | None) -> bool:
    da, db = _digits(a), _digits(b)
    return len(da) >= 6 and da == db


class LoginBody(BaseModel):
    login: str
    password: str = ""
    role: str | None = None  # optional hint: "staff" | "partner" | "tech" | "tenant"


def find_account(login: str, role_hint: str | None = None) -> dict | None:
    """Email, phone, partner id or technician id → {role, sub, pid, name, to}."""
    from app.db import get_session
    from app.models import Contact, Partner, Technician

    q = (login or "").strip()
    if not q:
        return None
    low = q.lower()
    with get_session() as s:
        contacts = s.exec(select(Contact)).all()
        partners = s.exec(select(Partner)).all()
        techs = s.exec(select(Technician)).all()

    def match_contact(c) -> bool:
        return (c.email or "").lower() == low or _phone_eq(c.phone_e164, q) or c.name.lower() == low

    found: list[dict] = []
    for c in contacts:
        if not match_contact(c):
            continue
        if c.role == "pm":
            found.append({"role": "staff", "sub": c.id, "name": c.name, "to": "/staff"})
        elif c.role in ("tenant", "owner"):
            found.append({"role": "tenant", "sub": c.id, "name": c.name, "to": "/tenant"})
        elif c.role == "partner_staff" and c.partner_id:
            found.append({"role": "partner", "sub": c.partner_id, "pid": c.partner_id, "name": c.name,
                          "to": f"/partner/{c.partner_id}"})
    for t in techs:
        if t.id.lower() == low or _phone_eq(t.phone_e164, q):
            found.append({"role": "tech", "sub": t.id, "pid": t.partner_id, "name": t.name, "to": f"/tech/{t.id}"})
    for p in partners:
        m = p.manifest or {}
        tr = m.get("transport") or {}
        addrs = [tr.get("address"), (tr.get("notify") or {}).get("address"), m.get("email"),
                 (m.get("contact") or {}).get("email"), (m.get("contact") or {}).get("phone")]
        if p.id.lower() == low or any(a and (str(a).lower() == low or _phone_eq(str(a), q)) for a in addrs):
            if p.active:
                found.append({"role": "partner", "sub": p.id, "pid": p.id, "name": m.get("name") or p.id,
                              "to": f"/partner/{p.id}"})
    if role_hint:
        found = [f for f in found if f["role"] == role_hint]
    return found[0] if found else None


def login(body: LoginBody) -> dict:
    acc = find_account(body.login, body.role)
    if acc is None:
        raise HTTPException(404, "no account with that email, phone number or id")
    if not (body.password or "").strip():
        raise HTTPException(400, "password required")
    return {**acc, "token": make_token(acc["role"], acc["sub"], acc.get("pid")), "expires_in": TOKEN_TTL}
