"""Pre-checks staff see before approving a self-onboarded partner (partner review, feature 1).

precheck(manifest, documents, company) → [{id, label, status: pass|warn|fail, detail}]
documents: dicts with {doc_type, label, number, valid_until, coverage_eur, company_name, filename}
doc_type ∈ trade_licence | insurance | gas_registry | vat.
"""
from __future__ import annotations

import re
from datetime import date

from ..config import now
from .eligibility import in_service_area

DOC_TYPES = {
    "trade_licence": "Trade licence (Handwerkskarte)",
    "insurance": "Liability insurance",
    "gas_registry": "Gas installer registration",
    "vat": "VAT registration certificate",
}
MIN_INSURANCE_EUR = 1_000_000
EXPIRING_DOCS = ("insurance", "gas_registry")  # these suspend a partner when they lapse


def _trades(manifest: dict) -> list[str]:
    return list((manifest.get("capabilities") or {}).get("trades") or [])


def required_docs(manifest: dict) -> list[str]:
    req = ["trade_licence", "insurance", "vat"]
    if "heating" in _trades(manifest):
        req.insert(2, "gas_registry")
    return req


def _date(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _norm_name(n: str) -> str:
    n = (n or "").lower()
    n = re.sub(r"\b(gmbh|ug|ag|kg|ohg|e\.?k\.?|gbr|co\.?|&)\b", " ", n)
    return re.sub(r"[^a-z0-9äöüß]+", "", n)


def expired_docs(documents: list[dict], today: date | None = None) -> list[dict]:
    """Insurance / gas registration documents whose valid-until date has passed."""
    today = today or now().date()
    out = []
    for d in documents:
        if d.get("doc_type") in EXPIRING_DOCS:
            vu = _date(d.get("valid_until"))
            if vu and vu < today:
                out.append(d)
    return out


def precheck(manifest: dict, documents: list[dict], company: dict | None = None) -> list[dict]:
    company = company or {}
    today = now().date()
    by_type = {d.get("doc_type"): d for d in documents if d.get("doc_type")}
    checks: list[dict] = []

    def add(cid: str, label: str, status: str, detail: str) -> None:
        checks.append({"id": cid, "label": label, "status": status, "detail": detail})

    # 1. every document present
    missing = [DOC_TYPES[t] for t in required_docs(manifest) if t not in by_type]
    add("documents", "All documents uploaded", "fail" if missing else "pass",
        ("Missing: " + ", ".join(missing)) if missing else f"{len(by_type)} documents")

    # 2. valid-until dates in the future
    expired, soon, undated = [], [], []
    for t, d in by_type.items():
        vu = _date(d.get("valid_until"))
        if t in EXPIRING_DOCS and vu is None:
            undated.append(DOC_TYPES.get(t, t))
        elif vu and vu < today:
            expired.append(f"{DOC_TYPES.get(t, t)} ({vu.isoformat()})")
        elif vu and (vu - today).days < 60:
            soon.append(f"{DOC_TYPES.get(t, t)} ({vu.isoformat()})")
    if expired:
        add("validity", "Documents valid", "fail", "Expired: " + ", ".join(expired))
    elif undated or soon:
        add("validity", "Documents valid", "warn",
            "; ".join(([f"No valid-until date: {', '.join(undated)}"] if undated else []) +
                      ([f"Expires within 60 days: {', '.join(soon)}"] if soon else [])))
    else:
        add("validity", "Documents valid", "pass", "All dates in the future")

    # 3. insurance cover
    ins = by_type.get("insurance")
    try:
        cover = float((ins or {}).get("coverage_eur") or 0)
    except (TypeError, ValueError):
        cover = 0.0
    if not ins:
        add("insurance_cover", "Insurance cover ≥ €1,000,000", "fail", "No insurance certificate")
    elif cover >= MIN_INSURANCE_EUR:
        add("insurance_cover", "Insurance cover ≥ €1,000,000", "pass", f"€{cover:,.0f}")
    elif cover > 0:
        add("insurance_cover", "Insurance cover ≥ €1,000,000", "fail", f"Only €{cover:,.0f}")
    else:
        add("insurance_cover", "Insurance cover ≥ €1,000,000", "warn", "Cover amount not given")

    # 4. company name the same everywhere
    name = manifest.get("name") or ""
    names = {d.get("company_name") for d in documents if d.get("company_name")}
    if company.get("name"):
        names.add(company["name"])
    differ = sorted(n for n in names if _norm_name(n) != _norm_name(name))
    if differ:
        add("company_name", "Company name matches", "fail", f"{name} vs {', '.join(differ)}")
    else:
        add("company_name", "Company name matches", "pass", name)

    # 5. base postcode inside the service area
    area = manifest.get("service_area") or {}
    base = company.get("postcode") or area.get("base_postcode")
    if not base:
        add("service_area", "Base inside service area", "warn", "No business postcode given")
    elif area.get("base_postcode") and not area.get("postcodes") and str(base) == str(area["base_postcode"]):
        add("service_area", "Base inside service area", "pass",
            f"{base}, {area.get('radius_km', '?')} km radius")
    elif in_service_area(area, base):
        add("service_area", "Base inside service area", "pass", f"{base}")
    else:
        add("service_area", "Base inside service area", "warn",
            f"Business postcode {base} is outside the stated area")

    # 6. gas registry for heating
    if "heating" in _trades(manifest):
        gas = by_type.get("gas_registry")
        add("gas_registry", "Gas registration (heating trade)", "pass" if gas else "fail",
            (gas.get("number") or "given") if gas else "Heating work needs a gas installer registration")
    return checks


def summary(checks: list[dict]) -> str:
    """'pass' | 'warn' | 'fail' – the worst status."""
    st = {c["status"] for c in checks}
    return "fail" if "fail" in st else "warn" if "warn" in st else "pass"
