"""/tryDebye: judges and visitors register their phone as a demo tenant, then talk to Debye on WhatsApp.

Sign-ups are stored in data/try.local.json (gitignored, like seed.local.json) and loaded by seed.py,
so they survive /demo/reset. Every sign-up becomes a tenant in the demo flat TRY_UNIT_ID (unit_2a).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from .config import settings
from .db import get_session
from .models import Contact

log = logging.getLogger("debye.try")
router = APIRouter(prefix="/api/try", tags=["try"])

TRY_UNIT_ID = "unit_2a"
DEBYE_WHATSAPP = "+31 6 82886557"
_lock = threading.Lock()


def signups_path() -> Path:
    return Path(settings.data_dir) / "try.local.json"


def load_signups() -> list[dict]:
    p = signups_path()
    if not p.exists():
        return []
    try:
        return list(json.loads(p.read_text(encoding="utf-8")).get("contacts", []))
    except Exception:  # a broken file must never stop the seed
        log.exception("could not read %s", p)
        return []


def normalize(raw: str) -> str | None:
    import unicodedata
    s = unicodedata.normalize("NFKC", raw or "")  # full-width ＋ and digits from phone keyboards
    s = s.replace("(0)", "")  # "+32 (0)469 …"
    core = re.sub(r"[^\d+]", "", s)  # drops spaces, dashes, brackets and invisible direction marks
    s = ("+" if core.startswith("+") else "") + core.replace("+", "")
    if s.startswith("00"):
        s = "+" + s[2:]
    if not s.startswith("+"):
        return None
    return s if re.fullmatch(r"\+[1-9]\d{7,14}", s) else None


class RegisterBody(BaseModel):
    name: str
    phone: str
    consent: bool = False


@router.post("/register")
async def register(body: RegisterBody) -> dict:
    name = (body.name or "").strip()[:60]
    phone = normalize(body.phone)
    if not name:
        raise HTTPException(422, "Please enter your first name.")
    if not phone:
        raise HTTPException(422, "Please enter your number with the country code, e.g. +49 151 2345 6789.")
    if not body.consent:
        raise HTTPException(422, "Please agree that Debye may message you on WhatsApp for this demo.")
    cid = "c_try_" + hashlib.sha1(phone.encode()).hexdigest()[:10]
    entry = {"id": cid, "role": "tenant", "name": name, "phone_e164": phone, "language": "en",
             "unit_id": TRY_UNIT_ID, "move_in": "2025-10-01", "whatsapp_opt_in": True}
    with get_session() as s:
        existing = s.exec(select(Contact).where(Contact.phone_e164 == phone)).first()
        if existing and not existing.id.startswith("c_try_"):
            cid = existing.id  # already a demo tenant (e.g. Luka): just tell them to write
        else:
            c = s.get(Contact, cid) or Contact(id=cid, role="tenant", name=name)
            for k, v in entry.items():
                setattr(c, k, v)
            s.add(c)
            s.commit()
            with _lock:
                items = [x for x in load_signups() if x.get("id") != cid] + [entry]
                p = signups_path()
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({"contacts": items}, indent=1), encoding="utf-8")
    log.info("try: registered %s as %s", cid, TRY_UNIT_ID)
    return {"ok": True, "contact_id": cid, "debye_whatsapp": DEBYE_WHATSAPP,
            "wa_link": "https://wa.me/" + re.sub(r"\D", "", DEBYE_WHATSAPP) + "?text=Hi%20Debye"}
