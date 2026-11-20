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
            passed = str(actual) in [str(p) for p in manifest.service_area.get("postcodes", [])]
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
