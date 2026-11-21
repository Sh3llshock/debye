"""Scores eligible partners (technical-plan §8.2). Weights are shown as "why this partner"."""
from __future__ import annotations

from datetime import timedelta

from ..config import now
from .eligibility import evaluate, flatten
from .manifest import Manifest

WEIGHTS = {
    "brand_certified": 0.30,
    "availability": 0.25,
    "framework": 0.20,
    "rating": 0.15,
    "history": 0.10,
}

# Availability comes from data, not from partner ids: the earliest free slot in the partner's
# technician calendars (partners.technicians.free_slots, next 3 days), else the manifest's
# availability block ({"next_free_days": n} or {"mode": ...}). See availability_for().
DEFAULT_AVAILABILITY = {"days": 3, "label": "availability asked on dispatch"}
EN_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def availability_for(manifest: Manifest, tech_busy: list[list[dict]] | None) -> dict:
    """{"days": int, "label": str} for one partner.
    tech_busy: each technician's busy list (None/[] = the partner has no technicians in Debye)."""
    from datetime import datetime

    from ..config import TZ
    from .technicians import DAYS_AHEAD, free_slots
    if tech_busy:
        slots = sorted({sl["start"]: sl for b in tech_busy for sl in free_slots(b)}.values(),
                       key=lambda sl: sl["start"])
        if not slots:
            return {"days": DAYS_AHEAD + 3, "label": f"fully booked for the next {DAYS_AHEAD} days"}
        st = datetime.fromisoformat(slots[0]["start"]).astimezone(TZ)
        en = datetime.fromisoformat(slots[0]["end"]).astimezone(TZ)
        days = (st.date() - now().date()).days
        day = "today" if days == 0 else "tomorrow" if days == 1 else EN_DAYS[st.weekday()]
        return {"days": days, "label": f"free {day} {st.hour}–{en.hour}"}
    av = manifest.availability or {}
    if isinstance(av.get("next_free_days"), (int, float)):
        d = int(av["next_free_days"])
        return {"days": d, "label": f"next free slot in {d} days"}
    mode = av.get("mode")
    if mode == "api":
        return {"days": 2, "label": "availability from the partner's API"}
    return dict(DEFAULT_AVAILABILITY)


# Partners that worked on a property before (from centrix maintenance history).
PROPERTY_HISTORY = {
    "prop_12": {"heizung-schmidt": "serviced the boiler on 2025-10-08"},
}


def _availability_score(days: int) -> float:
    # tomorrow → 0.8 (today would be 1.0), a week out → ~0
    return max(0.0, min(1.0, 1.0 - 0.2 * days))


def rank(case_type: str, ctx: dict, manifests: list[Manifest],
         framework_partner_ids: set[str], property_id: str | None,
         trade: str | None = None, availability: dict[str, dict] | None = None) -> list[dict]:
    """ctx: nested dict with property/unit/asset/tenant keys. Returns all candidates, sorted;
    each {partner_id, name, score, reasons, eligible, breakdown, next_free}.
    With a trade (from the diagnosis), partners are filtered by capabilities.trades instead of the
    category, and the brand bonus applies only to heating (a plumber doesn't need Vaillant)."""
    flat = flatten(ctx)
    make = (ctx.get("asset") or {}).get("make")
    brand_matters = trade in (None, "heating")
    out = []
    for m in manifests:
        if m.kind != "deliver":
            continue
        if trade:
            if trade not in (m.capabilities.get("trades") or []):
                continue
        elif m.category != case_type:
            continue
        eligible, why_not = evaluate(m, flat)
        if not eligible:
            out.append({"partner_id": m.partner_id, "name": m.name, "score": 0.0,
                        "reasons": why_not, "eligible": False, "breakdown": {}})
            continue
        reasons: list[str] = []
        breakdown: dict[str, float] = {}

        if brand_matters:
            certified = bool(make) and make in m.brands_certified
            breakdown["brand_certified"] = WEIGHTS["brand_certified"] * (1.0 if certified else 0.0)
            reasons.append(f"{make}-certified" if certified else f"not {make}-certified")
        else:  # the weight goes to the trade match instead (every candidate here has the trade)
            breakdown["brand_certified"] = WEIGHTS["brand_certified"]
            reasons.append(f"{trade} trade")

        av = (availability or {}).get(m.partner_id) or availability_for(m, None)
        breakdown["availability"] = WEIGHTS["availability"] * _availability_score(av["days"])
        reasons.append(av["label"])

        fw = m.partner_id in framework_partner_ids
        breakdown["framework"] = WEIGHTS["framework"] * (1.0 if fw else 0.0)
        reasons.append("framework agreement with reltix" if fw else "no framework agreement")
        pr = m.pricing or {}
        if pr.get("callout_fee_eur") is not None and pr.get("hourly_eur") is not None:
            reasons.append(f"€{float(pr['callout_fee_eur']):.0f} callout, €{float(pr['hourly_eur']):.0f}/h")
        elif pr.get("model") == "quote":
            reasons.append("prices by quote")

        rating = float(m.rating or 0)
        breakdown["rating"] = WEIGHTS["rating"] * (rating / 5.0)
        reasons.append(f"rating {rating:.1f}")

        hist = PROPERTY_HISTORY.get(property_id or "", {}).get(m.partner_id)
        breakdown["history"] = WEIGHTS["history"] * (1.0 if hist else 0.0)
        if hist:
            reasons.append(hist)

        score = round(sum(breakdown.values()), 2)
        next_free = (now() + timedelta(days=av["days"])).date().isoformat()
        out.append({"partner_id": m.partner_id, "name": m.name, "score": score,
                    "reasons": reasons, "eligible": True,
                    "breakdown": {k: round(v, 3) for k, v in breakdown.items()},
                    "next_free": next_free})
    out.sort(key=lambda r: (r["eligible"], r["score"]), reverse=True)
    return out
