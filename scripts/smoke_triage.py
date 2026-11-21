#!/usr/bin/env python3
"""Smoke gate for triage: short real-world first messages against the live model (LLM from .env),
checked by code. The 66 gold conversations (scripts/eval_triage.py) are the score, this is the gate.

    python scripts/smoke_triage.py               # all openers; exit code 1 if any check fails
    python scripts/smoke_triage.py gas german    # only these
    PLANNER_ENABLED=1 python scripts/smoke_triage.py

Checks on every opener: the routed area (or the emergency, or the area list for a vague message), the
first reply within FIRST_REPLY_MAX_S, at most one question in it, no hot-water talk outside hot water,
German answered in German.
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_triage as et  # noqa: E402  (temp DB, env, backend on sys.path)

FIRST_REPLY_MAX_S = float(os.getenv("FIRST_REPLY_MAX_S", "10"))
PHONE = "490000000001"

# name: (message, expected area | "emergency:<cause>" | "list")
OPENERS = {
    "ceiling": ("water dripping from ceiling", "roof_ceiling_leak"),
    "toilet": ("toilet blocked", "blocked_drain"),
    "kitchen_power": ("no power in kitchen", "electrics"),
    "front_door": ("front door lock broken", "windows_doors"),
    "mold": ("mold in bathroom", "mold_damp"),
    "mice": ("mice in kitchen", "pests"),
    "intercom": ("intercom dead", "intercom"),
    "window": ("window won't close", "windows_doors"),
    "noise": ("neighbour too loud", "management"),
    "gas": ("I smell gas in the kitchen", "emergency:gas_smell"),
    "german": ("Der Wasserhahn in der Küche tropft", "water_leak"),
    "vague": ("hi, something in my flat isn't working", "list"),
}
HOT_WATER_TALK = re.compile(r"\b(hot water|shower is cold|warm water|boiler)\b", re.I)
GERMAN = re.compile(r"\b(der|die|das|ist|nicht|bitte|kannst|du|dein|wo|welche|Wasser|Hahn)\b")


def run(names: list[str]) -> int:
    import app.channels.base  # noqa: F401  (loads .env)
    from fastapi.testclient import TestClient

    from app.agent import state
    from app.channels import whatsapp
    from app.main import app
    from app.seed import seed

    track_ref: dict = {}
    et.instrument(track_ref)
    fails = 0
    with TestClient(app) as client:
        # warm-up (not timed): the first request of a fresh process pays imports, connections and TLS once;
        # a running server is warm, so first-reply times are measured from the second request on
        seed(reset=True)
        state.reset_all()
        client.post("/webhooks/whatsapp", json=et.ev.wa_text(PHONE, "my tap is dripping"))
        for name in names:
            text, expect = OPENERS[name]
            seed(reset=True)
            state.reset_all()
            whatsapp.clear_outbox()
            track_ref["t"] = {"events": []}
            t0 = time.perf_counter()
            client.post("/webhooks/whatsapp", json=et.ev.wa_text(PHONE, text))
            took = time.perf_counter() - t0
            msgs = [m["payload"] for m in whatsapp.outbox(0) if m["to"].lstrip("+") == PHONE]
            bodies = [p["text"]["body"] if p["type"] == "text" else p["interactive"]["body"]["text"] for p in msgs]
            ids = [r["id"] for p in msgs if p["type"] == "interactive" for r in (
                [b["reply"] for b in p["interactive"]["action"].get("buttons", [])]
                + [r for s in p["interactive"]["action"].get("sections", []) for r in s["rows"]])]
            events = track_ref["t"]["events"]
            area = next((a for kind, a, _ in events if kind in ("asked", "concluded")), None)                 or (state.conversation("c_202").diagnosis or {}).get("area")
            concluded = [c for kind, _, c in events if kind == "concluded"]
            problems = []
            if expect == "list":
                if not any(i.startswith("triage:") for i in ids):
                    problems.append("no area list")
            elif expect.startswith("emergency:"):
                if expect.split(":")[1] not in concluded:
                    problems.append(f"no emergency (concluded {concluded})")
            elif area != expect:
                problems.append(f"area {area} != {expect}")
            if not bodies:
                problems.append("no reply")
            if took > FIRST_REPLY_MAX_S:
                problems.append(f"first reply took {took:.1f} s")
            if sum(b.count("?") for b in bodies if not b.startswith("Let me look")) > 1:
                problems.append("more than one question")
            if expect not in ("emergency:gas_smell",) and any(HOT_WATER_TALK.search(b) for b in bodies):
                problems.append("hot-water talk")
            if name == "german" and bodies and not all(GERMAN.search(b) for b in bodies):
                problems.append("not German")
            ok = not problems
            fails += not ok
            print(f"{'✓' if ok else '✗'} {name:14s} {took:4.1f} s area={area} | {' / '.join(bodies)[:140]}"
                  + ("" if ok else f"  <- {'; '.join(problems)}"), flush=True)
    print(f"\n{len(names) - fails}/{len(names)} triage smoke openers passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sel = [a for a in sys.argv[1:] if a in OPENERS] or list(OPENERS)
    sys.exit(run(sel))
