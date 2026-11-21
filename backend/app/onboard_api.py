"""Partner onboarding API (docs/connector-spec.md §9 "Onboarding a partner in 2 minutes").

GET  /api/partners/onboard/schema    defaults and choices for the join form
POST /api/partners/onboard/validate  {manifest} → {valid, checks[]} (live checklist)
POST /api/partners/onboard           {manifest, technicians[], documents[], company} → partner saved as
                                     pending_review; staff approve it on the Partners page (feature 1)
POST /api/partners/onboard/from-website {url} → {fields, manifest_draft} to pre-fill the form (nothing saved)
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .config import now_iso, settings
from .db import get_session
from .models import Partner, Technician
from .partners import onboarding

log = logging.getLogger("debye.onboard")
router = APIRouter(prefix="/api/partners/onboard", tags=["onboarding"])


class TechIn(BaseModel):
    name: str
    skills: list[str] = []
    phone_e164: str | None = None


class DocIn(BaseModel):
    """A licence / insurance document from the join form (Welcome.tsx)."""
    doc_type: str  # trade_licence | insurance | gas_registry | vat
    filename: str = ""
    number: str | None = None
    valid_until: str | None = None
    coverage_eur: float | None = None
    issuer: str | None = None
    company_name: str | None = None
    data_url: str | None = None  # optional "data:<mime>;base64,..." of the uploaded file


class CompanyIn(BaseModel):
    name: str | None = None
    street: str | None = None
    postcode: str | None = None
    city: str | None = None
    vat_id: str | None = None


class OnboardIn(BaseModel):
    manifest: dict
    technicians: list[TechIn] = []
    documents: list[DocIn] = []
    company: CompanyIn | None = None
    whatsapp_link_id: str | None = None  # verified handshake (POST /whatsapp/start) for a WhatsApp transport


class WhatsAppStartIn(BaseModel):
    phone: str | None = None
    company: str | None = None


class ValidateIn(BaseModel):
    manifest: dict


@router.get("/schema")
def get_schema() -> dict:
    return onboarding.schema()


class WebsiteIn(BaseModel):
    url: str


@router.post("/from-website")
async def from_website(body: WebsiteIn) -> dict:
    from .partners import website
    try:
        return await website.autofill(body.url)
    except website.BlockedUrl as e:
        raise HTTPException(400, str(e)) from None


@router.post("/whatsapp/start")
def whatsapp_start(body: WhatsAppStartIn) -> dict:
    """Step 1 of the WhatsApp handshake: a one-time code + wa.me link for the company's phone."""
    from .partners import wa_partner
    return wa_partner.start(body.phone, body.company)


@router.get("/whatsapp/{link_id}")
def whatsapp_status(link_id: str) -> dict:
    """Polled by the join form: pending → received → replied → verified."""
    from .partners import wa_partner
    v = wa_partner.status(link_id)
    if v is None:
        raise HTTPException(404, "unknown link")
    return v


@router.post("/validate")
def validate(body: ValidateIn) -> dict:
    _, checks = onboarding.validate(body.manifest)
    return {"valid": onboarding.is_valid(checks), "checks": checks}


def _tech_id(partner_id: str, name: str, taken: set[str]) -> str:
    first = re.sub(r"[^a-z0-9]+", "", onboarding.slugify(name.split()[0] if name.split() else name)) or "tech"
    base = f"tech_{first}_{partner_id.split('-')[-1][:12]}"
    tid, n = base, 2
    while tid in taken:
        tid, n = f"{base}{n}", n + 1
    taken.add(tid)
    return tid


@router.post("")
def onboard(body: OnboardIn) -> dict:
    raw = dict(body.manifest)
    pid = str(raw.get("partner_id") or "")
    if raw.get("transport", {}).get("type") == "portal" and pid:
        raw["transport"] = {**raw["transport"], "url": f"/partner/{pid}"}  # centrix owns the portal URL
    link = None
    tr = raw.get("transport") or {}
    if tr.get("type") == "conversational" and tr.get("channel") == "whatsapp":
        from .partners import wa_partner
        link = wa_partner.verified_link(body.whatsapp_link_id or tr.get("link_id"))
        if link is None:
            raise HTTPException(422, {"message": "Connect WhatsApp first: send the code to Debye and tap the "
                                                 "test button", "checks": []})
        raw["transport"] = wa_partner.transport_from_link(link, pid, tr.get("language") or "de")
    m, checks = onboarding.validate(raw)
    if m is None or not onboarding.is_valid(checks):
        raise HTTPException(422, {"message": "manifest does not match the connector spec",
                                  "checks": [c for c in checks if not c["ok"]]})
    with get_session() as s:
        existing = s.get(Partner, m.partner_id)
        if existing and not (existing.manifest or {}).get("onboarding"):
            # seeded partners can't be overwritten from the public form; re-onboarding is fine
            raise HTTPException(409, f"partner {m.partner_id} already exists")
        manifest = m.model_dump(mode="json", exclude_none=True)
        docs_meta = [_doc_meta(d) for d in body.documents]
        manifest["onboarding"] = {"at": now_iso(), "via": "/partners/join", "status": "pending_review",
                                  "company": body.company.model_dump(exclude_none=True) if body.company else {},
                                  "documents": docs_meta}
        manifest.pop("technicians", None)
        # new partners wait for a reltix staff review before they are ranked (feature 1)
        s.merge(Partner(id=m.partner_id, manifest=manifest, active=False, status="pending_review",
                        review={}))
        _store_documents(s, m.partner_id, body.documents, docs_meta)

        # replace this partner's technicians (re-onboarding the same partner stays idempotent)
        from sqlmodel import select
        for t in s.exec(select(Technician).where(Technician.partner_id == m.partner_id)).all():
            s.delete(t)
        s.flush()
        taken = {t.id for t in s.exec(select(Technician)).all()}
        techs = []
        for t in body.technicians:
            if not t.name.strip():
                continue
            tid = _tech_id(m.partner_id, t.name.strip(), taken)
            s.add(Technician(id=tid, partner_id=m.partner_id, name=t.name.strip(),
                             phone_e164=t.phone_e164, skills=t.skills, busy=[]))
            techs.append({"tech_id": tid, "name": t.name.strip(), "skills": t.skills,
                          "phone_e164": t.phone_e164, "url": f"/tech/{tid}"})
        s.commit()

    file = None
    if settings.demo_mode:  # the manifest becomes a file like every other partner (survives a reset)
        path = Path(settings.partners_dir) / f"{m.partner_id}.json"
        roster = [{"id": t["tech_id"], "name": t["name"], "skills": t["skills"],
                   **({"phone_e164": t["phone_e164"]} if t["phone_e164"] else {})} for t in techs]
        path.write_text(json.dumps({**manifest, "technicians": roster}, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        file = f"partners/{path.name}"
    if link is not None:
        from .partners import wa_partner
        wa_partner.attach_to_partner(link.id, m.partner_id, link.profile_name or m.name)
    log.info("onboarded partner %s with %d technician(s), pending review", m.partner_id, len(techs))
    from .events import record_event
    record_event(None, "partner", "partner.applied",
                 f"{m.name} registered as a partner – waiting for review",
                 {"partner_id": m.partner_id, "partner_name": m.name, "documents": len(docs_meta)})
    return {"partner_id": m.partner_id, "name": m.name, "portal_url": f"/partner/{m.partner_id}",
            "status": "pending_review",
            "technicians": techs, "manifest": manifest, "file": file, "checks": checks}


def _doc_meta(d: DocIn) -> dict:
    return {k: v for k, v in d.model_dump(exclude={"data_url"}).items() if v not in (None, "")}


def _store_documents(s, partner_id: str, docs: list[DocIn], metas: list[dict]) -> None:
    """Document rows linked to the partner (kind partner_doc). The file is the upload if the form
    sent one, else a short text stand-in so staff can still open something."""
    import base64
    from sqlmodel import select
    from .db import next_id
    from .models import Document
    for old in s.exec(select(Document).where(Document.partner_id == partner_id)).all():
        s.delete(old)
    s.flush()
    folder = Path(settings.storage_dir) / "partners" / partner_id
    folder.mkdir(parents=True, exist_ok=True)
    for d, meta in zip(docs, metas):
        fname = Path(d.filename or f"{d.doc_type}.txt").name or f"{d.doc_type}.txt"
        mime, data = "text/plain", None
        if d.data_url and d.data_url.startswith("data:") and "," in d.data_url:
            head, b64 = d.data_url.split(",", 1)
            mime = head[5:].split(";")[0] or "application/octet-stream"
            try:
                data = base64.b64decode(b64)[:5_000_000]
            except ValueError:
                data = None
        if data is None:
            mime = "text/plain"
            fname = Path(fname).stem + ".txt"
            data = chr(10).join(f"{k}: {v}" for k, v in meta.items()).encode("utf-8")
        path = folder / f"{d.doc_type}_{fname}"
        path.write_bytes(data)
        s.add(Document(id=next_id(s, Document, "doc"), partner_id=partner_id, kind="partner_doc",
                       filename=fname, mime=mime, path=str(path), extracted=meta, created_at=now_iso()))
        s.flush()
