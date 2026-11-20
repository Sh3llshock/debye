"""Case priority rules, enforced in code before services.open_case (the model only suggests).

- "emergency" from the model is kept (gas smell, flooding, ...).
- A heating case during the heating season (November–March) is at least "urgent".
- Any "no heating" / "no hot water" report is at least "urgent", whatever the month.
"""
from __future__ import annotations

import re
from datetime import datetime

HEATING_SEASON_MONTHS = {11, 12, 1, 2, 3}
_RANK = {"normal": 0, "urgent": 1, "emergency": 2}

_NO_HEAT_RE = re.compile(
    r"(kein(e|en)?\s+(heizung|warm\w*|heiß\w*|heiss\w*)"
    r"|heizung\s+(ist\s+)?(aus|kalt|ausgefallen|geht\s+nicht|funktioniert\s+nicht|springt\s+nicht\s+an)"
    r"|(komplett|alles|überall|ueberall|alle\s+heizkörper)\s+kalt"
    r"|kalt(es)?\s+wasser|wasser\s+(ist\s+|bleibt\s+)?kalt"
    r"|no\s+(heating|hot\s+water)|heating\s+(is\s+)?(off|out|broken))",
    re.IGNORECASE,
)


def _now() -> datetime:
    try:
        from app.config import now  # demo clock (skip-to-tomorrow aware)

        return now()
    except Exception:
        return datetime.now()


def reports_no_heat(*texts: str | None) -> bool:
    return any(_NO_HEAT_RE.search(t or "") for t in texts)


def enforce_priority(model_priority: str | None, case_type: str, *texts: str | None,
                     when: datetime | None = None) -> tuple[str, str | None]:
    """Returns (priority, reason-if-raised). Never lowers what the model said."""
    p = (model_priority or "normal").strip().lower()
    if p not in _RANK:
        p = "normal"
    floor, reason = "normal", None
    month = (when or _now()).month
    if case_type.startswith("repair.heating") and month in HEATING_SEASON_MONTHS:
        floor, reason = "urgent", "heating fault during the heating season (Nov–Mar)"
    elif reports_no_heat(*texts):
        floor, reason = "urgent", "no heating / no hot water reported"
    if _RANK[p] >= _RANK[floor]:
        return p, None
    return floor, reason
