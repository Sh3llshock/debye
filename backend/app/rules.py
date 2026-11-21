"""Rules in code, not in the prompt (technical-plan §7.5)."""
from __future__ import annotations

from sqlmodel import Session, select

from .models import Case, Consent, Contract, Partner


class RuleViolation(Exception):
    """code ∈ consent_missing | approval_required | ..."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(code)
        self.code = code
        self.message = message or code

    def __str__(self) -> str:
        return self.code


# Consent field aliases: manifests say tenant_name / tenant_phone, the UI and reltix payload
# say name / phone. Both spellings count as the same field.
FIELD_ALIASES = {
    "tenant_name": "name",
    "tenant_phone": "phone",
    "floor": "unit_floor",
}


def norm_field(f: str) -> str:
    return FIELD_ALIASES.get(f, f)


def consents_for_case(session: Session, case_id: str, partner_id: str) -> list[Consent]:
    return list(session.exec(select(Consent).where(
        Consent.case_id == case_id, Consent.partner_id == partner_id,
        Consent.revoked_at == None)).all())  # noqa: E711


def consented_fields(session: Session, case_id: str, partner_id: str) -> set[str]:
    out: set[str] = set()
    for c in consents_for_case(session, case_id, partner_id):
        out |= {norm_field(f) for f in c.data_shared}
    return out


def can_share(session: Session, case_id: str, partner_id: str, fields: list[str]) -> bool:
    have = consented_fields(session, case_id, partner_id)
    return all(norm_field(f) in have for f in fields)


def has_consent(session: Session, case_id: str, partner_id: str) -> bool:
    return bool(consents_for_case(session, case_id, partner_id))


def framework_contract(session: Session, partner_id: str) -> Contract | None:
    return session.exec(select(Contract).where(
        Contract.type == "framework", Contract.partner_id == partner_id)).first()


def auto_approve_limit(session: Session, partner_id: str) -> float:
    """From the framework contract. No framework agreement → every job needs PM approval."""
    fw = framework_contract(session, partner_id)
    if fw is None:
        return 0.0
    return float(fw.data.get("auto_approve_limit_eur", 0))


def approval_status(session: Session, case: Case, partner_id: str) -> dict:
    """{"required": bool, "rule": str, "granted": bool}. Policy from settings.approval_policy."""
    from .config import settings
    limit = auto_approve_limit(session, partner_id)
    est = case.estimated_cost_eur or 0
    granted = bool((case.data or {}).get("approval", {}).get("granted"))
    if (settings.approval_policy or "always").lower() != "limit":
        return {"required": True, "granted": granted, "policy": "always",
                "rule": "reltix staff approve every job before the partner is contacted"}
    if limit <= 0:
        return {"required": True, "granted": granted,
                "rule": "no framework agreement: PM approval needed"}
    if est > limit:
        return {"required": True, "granted": granted,
                "rule": f"PM approval needed: €{est:.0f} > €{limit:.0f} auto-approve limit"}
    return {"required": False, "granted": granted, "rule": f"auto-approved: < €{limit:.0f}"}


def check_dispatch(session: Session, case: Case, partner_id: str) -> dict:
    """Raises RuleViolation if the job may not be sent. Returns the approval status."""
    if not has_consent(session, case.id, partner_id):
        raise RuleViolation("consent_missing", f"no consent from the tenant to share data with {partner_id}")
    approval = approval_status(session, case, partner_id)
    if approval["required"] and not approval["granted"]:
        raise RuleViolation("approval_required", approval["rule"])
    return approval


def partner_prices(session: Session, partner_id: str | None) -> dict | None:
    """{callout_fee_eur, hourly_eur, auto_approve_limit_eur, source}: the framework contract if there is one,
    else the partner's manifest pricing (so a partner onboarded via the form gets a price check too)."""
    if not partner_id:
        return None
    fw = framework_contract(session, partner_id)
    if fw:
        return {"callout_fee_eur": float(fw.data.get("callout_fee_eur", 0)),
                "hourly_eur": float(fw.data.get("hourly_eur", 0)),
                "auto_approve_limit_eur": float(fw.data.get("auto_approve_limit_eur", 0)),
                "source": "framework"}
    p = session.get(Partner, partner_id)
    pr = ((p.manifest or {}).get("pricing") or {}) if p else {}
    if pr.get("callout_fee_eur") is None and pr.get("hourly_eur") is None:
        return None
    return {"callout_fee_eur": float(pr.get("callout_fee_eur") or 0), "hourly_eur": float(pr.get("hourly_eur") or 0),
            "auto_approve_limit_eur": 0.0, "source": "manifest"}


def estimate_cost(session: Session, error_code: str | None, partner_id: str | None = None) -> float:
    """Heuristic pre-visit estimate from the error code and the partner's prices."""
    callout, hourly = 89.0, 72.0
    prices = partner_prices(session, partner_id)
    if prices:
        callout = prices["callout_fee_eur"] or callout
        hourly = prices["hourly_eur"] or hourly
    hours, parts = {
        "F.22": (1.0, 20.0),
        "F.28": (1.5, 50.0),
        "F.29": (1.5, 50.0),
    }.get((error_code or "").upper(), (2.0, 30.0))
    return round(callout + hours * hourly + parts, 2)


def approved_cap(case: Case | None) -> tuple[float | None, str]:
    """The amount staff (or the auto-approve rule) agreed to: an approved quote wins, else the
    case's cost cap / estimate (estimated_cost_eur). (None, "") without a case."""
    if case is None:
        return None, ""
    data = case.data or {}
    quote = data.get("quote") or {}
    if quote.get("amount_eur") is not None and quote.get("status") in ("accepted", "approved"):
        return float(quote["amount_eur"]), "approved quote"
    if case.estimated_cost_eur is not None:
        granted = (data.get("approval") or {}).get("granted")
        return float(case.estimated_cost_eur), "approved estimate" if granted else "cost cap"
    return None, ""


def price_check(session: Session, partner_id: str, invoice: dict, case: Case | None = None) -> dict:
    """Compare an extracted invoice against the partner's prices (framework contract, else manifest
    pricing; lines >10% above are flagged) and against the approved cap (approved quote, else the
    approved estimate): a total above it is flagged for staff."""
    prices = partner_prices(session, partner_id)
    flags: list[str] = []
    gross = float(invoice.get("gross_eur") or 0)
    cap, cap_source = approved_cap(case)
    over_cap = bool(cap) and gross > cap
    if over_cap:
        flags.append(f"total €{gross:.2f} above the {cap_source} of €{cap:.2f} (+€{gross - cap:.2f})")
    if prices is None:
        return {"result": "flagged" if flags else "no_framework",
                "flags": flags + ["no price list for this partner"],
                "cap": {"amount_eur": cap, "source": cap_source, "exceeded": over_cap},
                "needs_staff_review": over_cap}
    callout, hourly, limit = prices["callout_fee_eur"], prices["hourly_eur"], prices["auto_approve_limit_eur"]
    for li in invoice.get("line_items") or []:
        desc = (li.get("desc") or "").lower()
        price = float(li.get("unit_price") or 0)
        ref = None
        if any(k in desc for k in ("anfahrt", "callout", "pauschale")):
            ref = callout
        elif any(k in desc for k in ("arbeitszeit", "stunde", "labour", "labor", "lohn")):
            ref = hourly
        if ref and price > ref * 1.10:
            flags.append(f"{li.get('desc')}: €{price:.2f} > {'framework' if prices['source'] == 'framework' else 'listed'} €{ref:.2f} (+10%)")
    if limit and gross > limit and not over_cap:
        flags.append(f"total €{gross:.2f} above auto-approve limit €{limit:.0f}")
    return {"result": "flagged" if flags else "ok", "flags": flags,
            "framework": {"callout_fee_eur": callout, "hourly_eur": hourly,
                          "auto_approve_limit_eur": limit, "source": prices["source"]},
            "cap": {"amount_eur": cap, "source": cap_source, "exceeded": over_cap},
            "needs_staff_review": bool(flags)}
