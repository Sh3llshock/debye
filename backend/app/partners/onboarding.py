"""Self-service partner onboarding (docs/connector-spec.md §9): defaults for the join form and a
validator that checks a manifest against the connector spec. Pure functions, no DB."""
from __future__ import annotations

import copy
import re
from typing import Any

from pydantic import ValidationError

from .manifest import Manifest

LIFECYCLE = {
    "deliver": ["requested", "accepted", "scheduled", "in_progress", "completed", "invoiced", "closed"],
    "sell": ["offered", "accepted", "signed", "active", "closed"],
    "any": ["declined", "needs_info", "cancelled"],
}
# What a deliver partner must report at minimum so the case can move from job sent to closed.
REQUIRED_EVENTS = {"deliver": ["accepted", "declined", "scheduled", "completed"],
                   "sell": ["accepted", "declined", "signed", "active"]}
OPS = {"eq", "in", "in_service_area", "gte", "lte"}
CONTEXT_ROOTS = ("property", "unit", "asset", "tenant", "case")
TRANSPORTS = {"api", "portal", "conversational"}
PRICING_MODELS = {"framework_agreement", "quote"}
DOCUMENTS = ["contract", "invoice", "visit_report", "meter_reading", "confirmation"]

TRADES = {  # trade → category, brands worth certifying, asset types for an eligibility rule
    "heating": {"category": "repair.heating", "brands": ["Vaillant", "Viessmann", "Buderus", "Wolf", "Junkers"],
                "asset_types": ["gas_boiler", "heat_pump"]},
    "plumbing": {"category": "repair.plumbing", "brands": ["Grohe", "Hansgrohe", "Geberit"], "asset_types": []},
    "electrical": {"category": "repair.electrical", "brands": ["Hager", "ABB", "Siemens"], "asset_types": []},
    "roofing": {"category": "repair.roofing", "brands": ["Velux", "Braas"], "asset_types": []},
    "locksmith": {"category": "repair.locksmith", "brands": ["ABUS", "DOM", "BKS"], "asset_types": []},
    "appliances": {"category": "repair.appliances", "brands": ["Bosch", "Miele", "Siemens"], "asset_types": []},
}

# Context a field-service partner needs; personal data always needs the resident's consent.
DEFAULT_CONTEXT = [
    {"key": "address", "source": "property.address", "pii": True, "consent_required": True},
    {"key": "unit_floor", "source": "unit.floor", "pii": False, "consent_required": False},
    {"key": "asset", "source": "asset", "pii": False, "consent_required": False},
    {"key": "error_code", "source": "case.error_code", "pii": False, "consent_required": False},
    {"key": "tenant_name", "source": "tenant.name", "pii": True, "consent_required": True},
    {"key": "tenant_phone", "source": "tenant.phone", "pii": True, "consent_required": True},
    {"key": "photos", "source": "case.documents[kind=photo]", "pii": True, "consent_required": True},
]


def slugify(name: str) -> str:
    s = name.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    s = re.sub(r"\b(gmbh|ag|kg|ug|ohg|e\.?k\.?|co)\b", "", s)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40] or "partner"


def schema() -> dict:
    """Defaults and choices for the join form (GET /api/partners/onboard/schema)."""
    return {
        "spec_version": "0.1",
        "trades": [{"id": k, **v} for k, v in TRADES.items()],
        "lifecycle": LIFECYCLE,
        "required_events": REQUIRED_EVENTS,
        "eligibility_ops": sorted(OPS),
        "transports": ["portal", "api", "conversational"],
        "pricing_models": sorted(PRICING_MODELS),
        "documents": DOCUMENTS,
        "default_required_context": copy.deepcopy(DEFAULT_CONTEXT),
        "defaults": {
            "base_postcode": "52062", "radius_km": 15,
            "pricing": {"model": "framework_agreement", "callout_fee_eur": 79, "hourly_eur": 65},
            "sla": {"urgent_response_hours": 4, "standard_response_hours": 48},
            "status_events": ["accepted", "declined", "scheduled", "in_progress", "completed", "invoiced"],
            "documents_returned": ["visit_report", "invoice"],
        },
    }


def _check(checks: list, cid: str, ok: bool, message: str) -> None:
    checks.append({"id": cid, "ok": bool(ok), "message": message})


def validate(raw: dict) -> tuple[Manifest | None, list[dict]]:
    """Checks a manifest against the spec. Returns (model or None, checks[{id, ok, message}]).
    The manifest is valid when every check is ok."""
    checks: list[dict] = []
    try:
        m = Manifest.model_validate(raw)
    except ValidationError as e:
        for err in e.errors():
            _check(checks, "schema", False, f"{'.'.join(map(str, err['loc']))}: {err['msg']}")
        return None, checks
    _check(checks, "schema", True, "Matches the manifest schema")

    _check(checks, "partner_id", bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{1,39}", m.partner_id)),
           "partner_id is a lowercase slug")
    _check(checks, "name", bool(m.name.strip()), "Has a display name")
    _check(checks, "kind", m.kind in ("deliver", "sell"), "kind is deliver or sell")
    _check(checks, "category", bool(re.fullmatch(r"[a-z]+(\.[a-z_]+)+", m.category)),
           f"category '{m.category}' is a dotted taxonomy")
    _check(checks, "triggers", bool(m.triggers) and all(re.fullmatch(r"[a-z]+(\.[a-z_]+)+", t) for t in m.triggers),
           f"Listens to {len(m.triggers)} centrix trigger(s)")
    trades = m.capabilities.get("trades") or []
    if m.kind == "deliver":
        _check(checks, "trades", bool(trades), "Names at least one trade (used for ranking)")

    area = m.service_area
    has_area = bool(area.get("postcodes")) or (
        bool(re.fullmatch(r"\d{5}", str(area.get("base_postcode", "")))) and (area.get("radius_km") or 0) > 0)
    _check(checks, "service_area", has_area, "Service area: postcodes or a radius around a postcode")

    bad_rules = [r for r in m.eligibility
                 if r.op not in OPS or r.field.split(".")[0] not in CONTEXT_ROOTS
                 or (r.op in ("in",) and not isinstance(r.value, list))]
    _check(checks, "eligibility", bool(m.eligibility) and not bad_rules,
           f"{len(m.eligibility)} eligibility rule(s), ops {', '.join(sorted({r.op for r in m.eligibility})) or '–'}"
           + (f"; invalid: {', '.join(r.field + ' ' + r.op for r in bad_rules)}" if bad_rules else ""))
    _check(checks, "eligibility_area", any(r.op == "in_service_area" for r in m.eligibility),
           "An in_service_area rule limits jobs to the service area")

    pii_unconsented = [c.key for c in m.required_context if c.pii and not c.consent_required]
    bad_source = [c.key for c in m.required_context if c.source.split(".")[0].split("[")[0] not in CONTEXT_ROOTS]
    _check(checks, "required_context", bool(m.required_context) and not bad_source,
           f"{len(m.required_context)} context field(s) from centrix"
           + (f"; unknown source: {', '.join(bad_source)}" if bad_source else ""))
    _check(checks, "consent", not pii_unconsented,
           f"Personal data needs consent: {len(m.consent_fields)} field(s) behind a consent flag"
           + (f"; missing on {', '.join(pii_unconsented)}" if pii_unconsented else ""))

    allowed = set(LIFECYCLE.get(m.kind, [])) | set(LIFECYCLE["any"])
    unknown = [s for s in m.status_events if s not in allowed]
    missing = [s for s in REQUIRED_EVENTS.get(m.kind, []) if s not in m.status_events]
    _check(checks, "status_events", not unknown and not missing,
           f"Reports {len(m.status_events)} lifecycle event(s)"
           + (f"; missing {', '.join(missing)}" if missing else "")
           + (f"; not in the lifecycle: {', '.join(unknown)}" if unknown else ""))

    tr = m.transport
    ttype = tr.get("type")
    if ttype == "api":
        t_ok = bool(re.fullmatch(r"https?://\S+", str(tr.get("base_url", ""))))
        t_msg = "API transport with a base_url"
    elif ttype == "conversational":
        t_ok = tr.get("channel") in ("whatsapp", "email") and bool(tr.get("address"))
        t_msg = "Conversational transport with channel and address"
    elif ttype == "portal":
        t_ok = bool(tr.get("url"))
        t_msg = "Portal transport (centrix partner page)"
    else:
        t_ok, t_msg = False, f"transport.type must be one of {', '.join(sorted(TRANSPORTS))}"
    _check(checks, "transport", t_ok, t_msg)

    if m.kind == "deliver":
        _check(checks, "pricing", m.pricing.get("model") in PRICING_MODELS,
               f"Pricing model {m.pricing.get('model') or '–'}")
        urgent = m.sla.get("urgent_response_hours")
        _check(checks, "sla", isinstance(urgent, (int, float)) and urgent > 0,
               f"SLA: answers urgent jobs within {urgent or '–'} h")
    bad_docs = [d for d in m.documents_returned if d not in DOCUMENTS]
    _check(checks, "documents", not bad_docs, "Returned documents are known kinds"
           + (f"; unknown: {', '.join(bad_docs)}" if bad_docs else ""))
    return m, checks


def is_valid(checks: list[dict]) -> bool:
    return all(c["ok"] for c in checks)


def build_manifest(form: dict[str, Any]) -> dict:
    """Optional helper: the same mapping the join form does in the browser, for scripts/tests.
    form: {name, trades[], brands[], postcodes[] | base_postcode+radius_km, pricing{}, transport{}, sla{}}."""
    pid = form.get("partner_id") or slugify(form["name"])
    trades = form.get("trades") or ["heating"]
    primary = TRADES.get(trades[0], {"category": f"repair.{trades[0]}", "asset_types": []})
    area = ({"postcodes": form["postcodes"]} if form.get("postcodes")
            else {"base_postcode": form.get("base_postcode", "52062"), "radius_km": form.get("radius_km", 15)})
    rules: list[dict] = []
    if trades == ["heating"] and primary.get("asset_types"):
        rules.append({"field": "asset.type", "op": "in", "value": primary["asset_types"]})
    rules.append({"field": "property.postcode", "op": "in_service_area"})
    d = schema()["defaults"]
    return {
        "partner_id": pid, "name": form["name"], "category": primary["category"], "kind": "deliver",
        "triggers": [f"case.{TRADES.get(t, {'category': 'repair.' + t})['category']}" for t in trades],
        "service_area": area,
        "capabilities": {"trades": trades, "brands_certified": form.get("brands", [])},
        "eligibility": rules,
        "pricing": form.get("pricing") or d["pricing"],
        "required_context": copy.deepcopy(DEFAULT_CONTEXT),
        "availability": {"mode": "static", "hours": "Mo–Fr 07:00–18:00"},
        "transport": form.get("transport") or {"type": "portal", "url": f"/partner/{pid}"},
        "status_events": list(d["status_events"]),
        "documents_returned": d["documents_returned"],
        "sla": form.get("sla") or d["sla"],
    }
