"""Partner onboarding API (docs/connector-spec.md §9 "Onboarding a partner in 2 minutes").

GET  /api/partners/onboard/schema    defaults and choices for the join form
POST /api/partners/onboard/validate  {manifest} → {valid, checks[]} (live checklist)
POST /api/partners/onboard           {manifest, technicians[]} → partner is live and rankable
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


class OnboardIn(BaseModel):
    manifest: dict
    technicians: list[TechIn] = []


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
        manifest["onboarding"] = {"at": now_iso(), "via": "/partners/join"}
        manifest.pop("technicians", None)
        s.merge(Partner(id=m.partner_id, manifest=manifest, active=True))

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
    log.info("onboarded partner %s with %d technician(s)", m.partner_id, len(techs))
    return {"partner_id": m.partner_id, "name": m.name, "portal_url": f"/partner/{m.partner_id}",
            "technicians": techs, "manifest": manifest, "file": file, "checks": checks}
