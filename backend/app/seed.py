"""Loads data/seed.json (+ optional gitignored data/seed.local.json) and partners/*.json.

seed.local.json overrides by id: any object in a list with the same "id" is merged over the
seed one (e.g. {"contacts": [{"id": "c_202", "phone_e164": "+4915..."}]}); new ids are added.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from .config import reset_clock, settings
from .db import create_all, drop_all, get_session
from .models import Asset, Contact, Contract, Notice, Partner, Property, Technician, Unit

log = logging.getLogger("debye.seed")


def _merge_lists(base: list[dict], override: list[dict]) -> list[dict]:
    by_id = {o.get("id"): dict(o) for o in base}
    order = [o.get("id") for o in base]
    for o in override:
        oid = o.get("id")
        if oid in by_id:
            by_id[oid].update(o)
        else:
            by_id[oid] = dict(o)
            order.append(oid)
    return [by_id[i] for i in order]


def load_seed_data() -> dict:
    data_dir = Path(settings.data_dir)
    data = json.loads((data_dir / "seed.json").read_text(encoding="utf-8"))
    local = data_dir / "seed.local.json"
    if local.exists():
        override = json.loads(local.read_text(encoding="utf-8"))
        for key, value in override.items():
            if isinstance(value, list) and isinstance(data.get(key), list):
                data[key] = _merge_lists(data[key], value)
            else:
                data[key] = value
        log.info("applied seed.local.json override")
    return data


def load_manifests() -> list[dict]:
    out = []
    for f in sorted(Path(settings.partners_dir).glob("*.json")):
        out.append(json.loads(f.read_text(encoding="utf-8")))
    return out


def _seed_partner_docs(s, m: dict) -> None:
    """Self-onboarded partners keep their document facts in the manifest (onboarding.documents);
    after a reset the Document rows come back as text stand-ins."""
    from sqlmodel import select
    from .db import next_id
    from .models import Document
    docs = (m.get("onboarding") or {}).get("documents") or []
    if not docs or s.exec(select(Document).where(Document.partner_id == m["partner_id"])).first():
        return
    folder = Path(settings.storage_dir) / "partners" / m["partner_id"]
    folder.mkdir(parents=True, exist_ok=True)
    for meta in docs:
        dtype = meta.get("doc_type", "doc")
        fname = Path(str(meta.get("filename") or dtype)).stem + ".txt"
        path = folder / f"{dtype}_{fname}"
        path.write_text(chr(10).join(f"{k}: {v}" for k, v in meta.items()), encoding="utf-8")
        s.add(Document(id=next_id(s, Document, "doc"), partner_id=m["partner_id"], kind="partner_doc",
                       filename=fname, mime="text/plain", path=str(path), extracted=meta))
        s.flush()


def _seed_whatsapp_contact(s, m: dict) -> None:
    """A partner that registered with WhatsApp keeps its verified number in its manifest
    (transport.address). After a reset that is enough: its staff contact comes back from it."""
    from sqlmodel import select
    from .db import next_id
    tr = m.get("transport") or {}
    phone = tr.get("address")
    if tr.get("type") != "conversational" or tr.get("channel") != "whatsapp" or not phone:
        return
    s.flush()
    c = s.exec(select(Contact).where(Contact.phone_e164 == phone)).first()
    if c is None:
        s.add(Contact(id=next_id(s, Contact, "c"), role="partner_staff", name=m.get("name") or m["partner_id"],
                      phone_e164=phone, partner_id=m["partner_id"], language=tr.get("language", "de"),
                      whatsapp_opt_in=True))
    elif c.role == "partner_staff":
        c.partner_id, c.whatsapp_opt_in = m["partner_id"], True
        s.add(c)
    s.flush()


def _whatsapp_demo(s) -> None:
    """PARTNER_WHATSAPP_DEMO=+4917...: Heizung Schmidt runs its jobs on WhatsApp from that phone
    (as if it had done the handshake), and Tom Schmidt (c_301) is that number."""
    import os
    phone = (os.getenv("PARTNER_WHATSAPP_DEMO") or "").strip().replace(" ", "")
    if not phone:
        return
    from sqlmodel import select
    from .config import now_iso
    phone = phone if phone.startswith("+") else "+" + phone.lstrip("0")
    pid = os.getenv("PARTNER_WHATSAPP_DEMO_ID", "heizung-schmidt")
    p = s.get(Partner, pid)
    if p is None:
        return
    for other in s.exec(select(Contact).where(Contact.phone_e164 == phone)).all():
        if other.partner_id != pid:
            other.phone_e164 = None  # the demo phone belongs to the partner now
            s.add(other)
    s.flush()
    staff = s.exec(select(Contact).where(Contact.partner_id == pid, Contact.role == "partner_staff")).first()
    if staff:
        staff.phone_e164, staff.whatsapp_opt_in = phone, True
        s.add(staff)
    p.manifest = {**p.manifest, "transport": {
        "type": "conversational", "channel": "whatsapp", "address": phone,
        "language": (p.manifest.get("transport") or {}).get("language", "de"),
        "verified_at": now_iso(), "link_id": "demo", "url": f"/partner/{pid}"}}
    s.add(p)
    log.info("partner %s runs on WhatsApp (%s)", pid, phone)


def seed(reset: bool = False) -> None:
    if reset:
        drop_all()
        storage = Path(settings.storage_dir)
        if storage.exists():
            shutil.rmtree(storage, ignore_errors=True)
        reset_clock()
    create_all()
    Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)

    with get_session() as s:
        if s.get(Property, "prop_12") is not None and not reset:
            return  # already seeded
        data = load_seed_data()
        for p in data.get("properties", []):
            ec = p.get("energy_certificate") or {}
            s.merge(Property(
                id=p["id"], address=p["address"], postcode=p["postcode"], city=p["city"],
                building_year=p.get("building_year"), heating_type=p.get("heating_type"),
                heating_central=bool(p.get("heating_central")),
                fibre_available=bool(p.get("fibre_available")),
                energy_class=ec.get("class"), energy_valid_until=ec.get("valid_until"),
            ))
        for u in data.get("units", []):
            s.merge(Unit(id=u["id"], property_id=u["property_id"], floor=u.get("floor"),
                         size_sqm=u.get("size_sqm"), rooms=u.get("rooms"),
                         meters=u.get("meters", []), access=u.get("access") or {}))
        for a in data.get("assets", []):
            s.merge(Asset(id=a["id"], property_id=a["property_id"], unit_id=a.get("unit_id"),
                          type=a["type"], make=a.get("make"), model=a.get("model"),
                          installed=a.get("installed"), last_service=a.get("last_service"),
                          known_error_codes=a.get("known_error_codes", {})))
        for c in data.get("contacts", []):
            s.merge(Contact(id=c["id"], role=c["role"], name=c["name"],
                            phone_e164=c.get("phone_e164"), email=c.get("email"),
                            language=c.get("language", "de"), unit_id=c.get("unit_id"),
                            partner_id=c.get("partner_id"), move_in=c.get("move_in"),
                            whatsapp_opt_in=bool(c.get("whatsapp_opt_in"))))
        for k in data.get("contracts", []):
            s.merge(Contract(id=k["id"], type=k["type"], unit_id=k.get("unit_id"),
                             contact_id=k.get("contact_id"), partner_id=k.get("partner_id"),
                             data=k.get("data", {})))
        from .partners.technicians import seed_busy
        for t in data.get("technicians", []):
            s.merge(Technician(id=t["id"], partner_id=t["partner_id"], name=t["name"],
                               phone_e164=t.get("phone_e164"), skills=t.get("skills", []),
                               busy=seed_busy(t.get("busy", []))))
        for n in data.get("notices", []):
            s.merge(Notice(id=n["id"], property_id=n["property_id"], title=n["title"],
                           body=n.get("body", ""), kind=n.get("kind", "maintenance"),
                           active=bool(n.get("active")), starts=n.get("starts"), ends=n.get("ends")))
        seeded_techs = {t["id"] for t in data.get("technicians", [])}
        for m in load_manifests():
            # onboarded partners (POST /api/partners/onboard) carry their technician roster
            for t in m.pop("technicians", None) or []:
                if t.get("id") and t["id"] not in seeded_techs:
                    s.merge(Technician(id=t["id"], partner_id=m["partner_id"], name=t["name"],
                                       phone_e164=t.get("phone_e164"), skills=t.get("skills", []),
                                       busy=seed_busy(t.get("busy", []))))
            # self-onboarded partners keep their review state across a reset (feature 1)
            status = (m.get("onboarding") or {}).get("status") or "active"
            review = (m.get("onboarding") or {}).get("review") or {}
            s.merge(Partner(id=m["partner_id"], manifest=m, active=status == "active",
                            status=status, review=review))
            _seed_partner_docs(s, m)
            _seed_whatsapp_contact(s, m)
        _whatsapp_demo(s)
        s.commit()
    log.info("seeded database")
