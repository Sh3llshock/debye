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
            s.merge(Partner(id=m["partner_id"], manifest=m, active=True))
        s.commit()
    log.info("seeded database")
