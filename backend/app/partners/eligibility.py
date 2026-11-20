"""Evaluates manifest eligibility rules against a flat centrix context (technical-plan §8.1)."""
from __future__ import annotations

from typing import Any

from .manifest import Manifest


def flatten(ctx: dict, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in ctx.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        else:
            out[key] = v
    return out


def in_service_area(area: dict, postcode: Any) -> bool:
    """postcodes[] wins; else radius_km around base_postcode. Without geodata the radius is
    approximated by German postcode prefixes (see below)."""
    pc = str(postcode or "")
    codes = [str(p) for p in area.get("postcodes") or []]
    if codes:
        return pc in codes
    base, radius = str(area.get("base_postcode") or ""), area.get("radius_km")
    if not (base and radius and pc):
        return False
    # Demo approximation (no geocoder offline): <=10 km → same first 4 digits,
    # <=30 km → same first 3 digits, larger → same leading region digits.
    digits = 4 if radius <= 10 else 3 if radius <= 30 else 2
    return pc[:digits] == base[:digits]


def evaluate(manifest: Manifest, flat: dict[str, Any]) -> tuple[bool, list[str]]:
    """Returns (eligible, reasons). Reasons explain failures (or passes when eligible)."""
    reasons: list[str] = []
    ok = True
    for rule in manifest.eligibility:
        actual = flat.get(rule.field)
        if rule.op == "eq":
            passed = actual == rule.value
        elif rule.op == "in":
            passed = actual in (rule.value or [])
        elif rule.op == "in_service_area":
            passed = in_service_area(manifest.service_area, actual)
        elif rule.op == "gte":
            passed = actual is not None and actual >= rule.value
        elif rule.op == "lte":
            passed = actual is not None and actual <= rule.value
        else:
            passed = False
        if not passed:
            ok = False
            reasons.append(f"{rule.field} {rule.op} {rule.value!r} failed (got {actual!r})")
    return ok, reasons
