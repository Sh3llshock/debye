"""Technician calendars (technician flow, interfaces §Technician flow).

Free slots = the next 3 days (tomorrow … +3), windows 08–10 / 10–12 / 14–16, minus busy entries.
Busy entries are absolute ISO intervals: seeded from relative demo windows, plus confirmed jobs.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from ..config import TZ, now

WINDOWS = [("08-10", 8, 10), ("10-12", 10, 12), ("14-16", 14, 16)]
DAYS_AHEAD = 3


def _interval(day: date, start_h: int, end_h: int) -> dict:
    s = datetime.combine(day, time(start_h), tzinfo=TZ)
    e = datetime.combine(day, time(end_h), tzinfo=TZ)
    return {"start": s.isoformat(timespec="seconds"), "end": e.isoformat(timespec="seconds")}


def seed_busy(rel: list[dict]) -> list[dict]:
    """[{day: 1, window: "08-10" | "all"}] → absolute intervals relative to the demo day."""
    today = now().date()
    out = []
    for b in rel:
        day = today + timedelta(days=int(b.get("day", 1)))
        w = b.get("window", "all")
        if w == "all":
            out.append({**_interval(day, 0, 23), "reason": "fully booked"})
            continue
        for name, sh, eh in WINDOWS:
            if name == w:
                out.append({**_interval(day, sh, eh), "reason": "other job"})
    return out


def _overlaps(a: dict, b: dict) -> bool:
    a0, a1 = datetime.fromisoformat(a["start"]), datetime.fromisoformat(a["end"])
    b0, b1 = datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"])
    return a0 < b1 and b0 < a1


def is_free(busy: list[dict], slot: dict) -> bool:
    return not any(_overlaps(slot, b) for b in busy)


def free_slots(busy: list[dict]) -> list[dict]:
    today = now().date()
    out = []
    for d in range(1, DAYS_AHEAD + 1):
        day = today + timedelta(days=d)
        for _, sh, eh in WINDOWS:
            slot = _interval(day, sh, eh)
            if is_free(busy, slot):
                out.append(slot)
    return out
