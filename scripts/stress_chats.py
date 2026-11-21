#!/usr/bin/env python3
"""Stress test for triage: difficult tenants on purpose, against the live model (LLM from .env), in parallel.

A simulated tenant (same model) plays a hard persona per chat: typos ("ceeling", "radiater", "toylet"),
one-word answers, "I already said that", answers outside the options, corrections, bursts, German. Plus
Luka's real looping chat replayed word for word (3 times). Checks by code on every chat:
  - no question asked twice (fuzzy match of Debye's questions; the consent question excepted)
  - never 3 tenant turns in a row without new information (answers, questions, area or conclusion)
  - a conclusion within 5 tenant turns
  - the right area and an allowed outcome

    python scripts/stress_chats.py                 # all chats, 8 workers; exit 1 if below 90 % or Luka fails
    python scripts/stress_chats.py ceiling_typo luka --workers 2
"""
from __future__ import annotations

import atexit
import difflib
import re
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_triage as et  # noqa: E402  (temp DB, env, backend on sys.path)

PHONE = "490000000001"
MAX_TURNS = 6
LUKA = ["Water is dripping from my ceeling", "I said the ceeling", "Yes", "Yesss"]
# scripted chats from live bugs: name prefix -> (messages, expected area, allowed outcomes)
SCRIPTS = {
    "luka": (LUKA, "roof_ceiling_leak", ("technician", "caretaker")),
    "sparks": (["socket in bedroom sparks", "only that one", "ok thanks"], "electrics", ("emergency",)),
}
HEATING_FIRM_OK = ("water_leak", "no_hot_water", "heating")  # heizung-schmidt also does plumbing
HW_LEAK_RE = re.compile(r"(hot water|radiator|room is cold|tap has no|warm water|shower)", re.I)
ACK_RE = re.compile(r"(sorry|got it|understood|right|ceiling|i see|thanks for|okay, the|ok, the)", re.I)

# name: (opener, what is true for the tenant, persona, expected area, allowed outcomes)
CHATS: dict[str, tuple[str, str, str, str, tuple[str, ...]]] = {
    "ceiling_typo": ("water dripping from my ceeling", "Only when it rains. You live on the top floor.",
                     "typos, one-word answers", "roof_ceiling_leak", ("technician", "caretaker")),
    "ceiling_upstairs": ("theres water coming thru the cieling", "It drips also when dry; the flat above has a "
                         "bathroom right there. Not top floor.", "say 'I already said that' once",
                         "roof_ceiling_leak", ("caretaker", "technician")),
    "radiater_leak": ("my radiater is leaking", "A small drip at the valve at the bottom of the radiator.",
                      "typos", "water_leak", ("technician", "caretaker", "self_help")),
    "toylet_blocked": ("toylet blokked", "Plunger didn't help. Only the toilet. Nothing comes up elsewhere.",
                       "one-word answers, typos", "blocked_drain", ("technician",)),
    "toilet_running": ("toilet keeps running", "Water runs into the bowl all the time, nothing on the floor.",
                       "answer outside the options first ('it's like hissing')", "water_leak",
                       ("technician", "caretaker", "self_help")),
    "tap_drip_de": ("Der Wasserhahn in der Küche tropft", "Es tropft auch fest zugedreht weiter.",
                    "German only, short", "water_leak", ("technician", "caretaker", "self_help")),
    "sink_slow": ("sink drains super slow", "Bathroom sink. You tried a plunger, no help. Shower is fine.",
                  "one-word answers", "blocked_drain", ("technician", "self_help")),
    "shower_drain_hair": ("shower water stays in the tray", "Haven't tried anything. Hair in the drain likely.",
                          "short, then 'idk'", "blocked_drain", ("self_help", "technician")),
    "kitchen_power": ("no power in kitchen", "Only the kitchen sockets. A fuse switch is down; you flip it, it works.",
                      "one-word answers", "electrics", ("self_help", "technician")),
    "fuse_trips": ("fuse keeps tripping", "It trips again right after you switch it back on.",
                   "frustrated: 'I already said that'", "electrics", ("technician", "caretaker")),
    "socket_dead_de": ("Steckdose im Schlafzimmer geht nicht", "Nur diese eine Steckdose, Sicherung ist okay.",
                       "German only", "electrics", ("technician", "caretaker")),
    "bulb_or_fitting": ("light in hallway dead", "Only that light. You changed the bulb, still dark.",
                        "corrects itself once ('no wait, the bathroom light')", "electrics",
                        ("technician", "caretaker", "self_help")),
    "front_door_lock": ("front door lock broken", "Your flat door; the key turns but the lock won't open.",
                        "one-word answers", "windows_doors", ("technician",)),
    "window_wont_close": ("window won't close", "Bedroom window, it's stuck in tilt position.",
                          "answer outside the options ('it's kind of hanging')", "windows_doors",
                          ("technician", "self_help", "caretaker")),
    "entrance_door": ("the main door downstairs doesnt lock anymore", "Building entrance door, it swings open.",
                      "typos", "windows_doors", ("caretaker", "technician")),
    "broken_glass": ("window pane cracked", "Living room, crack across the glass, no pieces fell.",
                     "short", "windows_doors", ("technician",)),
    "fridge_dead": ("fridge not cold", "It came with the flat. The light inside is on.", "one-word answers",
                    "appliances", ("technician", "self_help")),
    "washing_machine_own": ("washing machine broke", "It's your own machine.", "short", "appliances",
                            ("management", "technician")),
    "oven_de": ("Backofen wird nicht warm", "Gehört zur Wohnung. Licht geht an.", "German only", "appliances",
                ("technician",)),
    "mould_bathroom": ("mold in bathroom", "Black spots near the shower, the wall is dry, small patch.",
                       "one-word answers", "mold_damp", ("self_help", "technician")),
    "damp_wall": ("wet patch on the wall", "Outside wall, appears when it rains.",
                  "answer outside the options first", ("roof_ceiling_leak", "mold_damp"), ("technician",)),
    "mice": ("mice in kitchen", "You saw droppings and one mouse.", "short", "pests", ("technician",)),
    "wasps": ("wasps nest on balcony", "A nest under the balcony roof, many wasps.", "short", "pests",
              ("technician",)),
    "cockroach_de": ("Kakerlaken in der Küche", "Mehrere, auch tagsüber.", "German only", "pests", ("technician",)),
    "intercom_dead": ("intercom dead", "Your bell doesn't ring; neighbours' work. No mute switch.",
                      "say 'I already said that' once", "intercom", ("technician", "caretaker")),
    "buzzer": ("buzzer doesnt open the door downstairs", "Others have the same problem.", "typos", "intercom",
               ("caretaker", "technician")),
    "lift_stuck": ("lift not working", "It doesn't come, no sign, nobody inside.", "one-word answers", "lift",
                   ("technician",)),
    "noise": ("neighbour too loud", "Music every night after midnight.", "short", "management", ("management",)),
    "rent": ("question about my rent", "You want to know when the rent increase applies.", "short",
             "management", ("management",)),
    "stairwell_light": ("stairwell light broken", "Light on the 2nd floor landing is dark.", "short", "other",
                        ("caretaker",)),
    "vague": ("something isnt working", "It's the bathroom sink, it drains slowly, plunger didn't help.",
              "vague first, then answer", "blocked_drain", ("technician", "self_help")),
    "none_of_these": ("water on my floor", "It comes from under the fridge.", "reject the first options "
                      "('none of these')", "appliances", ("technician", "self_help", "management")),
}

SIM = """You play a tenant texting Debye, the WhatsApp assistant of the property manager. You are difficult on
purpose: {persona}. Write like a real person on WhatsApp: very short, informal, typos are fine.
What is true (answer only from this; if asked something else, say you don't know):
{facts}
If Debye asks for consent to share your details, say yes. When Debye has clearly arranged help or given a tip
that works, return done=true. Your first message was already sent."""


def run_chat(client, name: str, track: dict) -> dict:
    from app.agent import state
    from app.channels import whatsapp
    from app.seed import seed

    seed(reset=True)
    state.reset_all()
    whatsapp.clear_outbox()
    seen = [0]
    log: list[tuple[str, str]] = []

    def drain():
        msgs = whatsapp.outbox(seen[0])
        if msgs:
            seen[0] = msgs[-1]["seq"]
        for m in msgs:
            if m["to"].lstrip("+") != PHONE:
                continue
            p = m["payload"]
            body = p["text"]["body"] if p["type"] == "text" else p["interactive"]["body"]["text"]
            log.append(("debye", body))

    def send(text: str):
        client.post("/webhooks/whatsapp", json=et.ev.wa_text(PHONE, text))
        log.append(("tenant", text))
        drain()

    def signature():
        conv = state.conversation("c_202")
        d = conv.diagnosis or {}
        return (len(track["events"]), json.dumps(d.get("answers", {}), sort_keys=True), d.get("area"),
                tuple(d.get("dont_know", [])), conv.step, bool((conv.triage or {}).get("asked")),
                tuple(d.get("free_q", [])))

    stalls, max_stalls, turns, concluded_at = 0, 0, 0, None
    key = name.split("_")[0]
    if key in SCRIPTS:
        msgs, expect_area, allowed = SCRIPTS[key]
        script = list(msgs)
        opener, sim = script.pop(0), None
    else:
        opener, facts, persona, expect_area, allowed = CHATS[name]
        sim = SIM.format(persona=persona, facts=facts)
        script = []
    sig = signature()
    send(opener)
    turns = 1
    for _ in range(MAX_TURNS):
        new = signature()
        stalls = 0 if new != sig else stalls + 1
        max_stalls = max(max_stalls, stalls)
        sig = new
        if concluded_at is None and any(e[0] == "concluded" for e in track["events"]):
            concluded_at = turns
        last = next((e for e in reversed(track["events"]) if e[0] == "concluded"), None)
        if last and et.outcome_of(last[1], last[2]) != "self_help" and not log[-1][1].count("Is it okay if I share") \
                and not script:
            break
        if script:
            msg = script.pop(0)
        elif sim is None:
            break
        else:
            convo = "\n".join(f"{'You' if w == 'tenant' else 'Debye'}: {t}" for w, t in log)
            nxt = et.ev.llm_json(sim, f"The conversation so far:\n{convo}\n\nYour next message?", et.ev.SIM_SCHEMA,
                                 "tenant")
            if nxt["done"] or not nxt["messages"]:
                break
            msg = " ".join(m["text"] for m in nxt["messages"])
        send(msg)
        turns += 1
    if concluded_at is None and any(e[0] == "concluded" for e in track["events"]):
        concluded_at = turns
    questions = [t for w, t in log if w == "debye" and "?" in t and "Is it okay if I share" not in t
                 and "Ist es okay, wenn ich" not in t]
    repeats = [(a, b) for i, a in enumerate(questions) for b in questions[i + 1:]
               if difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() > 0.8]
    concl = [e for e in track["events"] if e[0] == "concluded"]
    got_area = concl[-1][1] if concl else next((a for k, a, _ in track["events"] if k == "asked"),
                                                 (state.conversation("c_202").diagnosis or {}).get("area"))
    got_outcome = et.outcome_of(concl[-1][1], concl[-1][2]) if concl else None
    resolved = any(e[0] == "resolved" for e in track["events"])
    problems = []
    exp_areas = expect_area if isinstance(expect_area, tuple) else (expect_area,)
    if not any(a in HEATING_FIRM_OK for a in exp_areas) and any("Heizung" in t for w, t in log if w == "debye"):
        problems.append("wrong partner: a heating firm for another trade")
    if concl:
        first_concl = next(i for i, (w, t) in enumerate(log) if w == "debye" and i > 0) if log else 0
        after = [t for w, t in log[first_concl + 1:] if w == "debye"]
        if got_outcome == "emergency" and any(HW_LEAK_RE.search(t) for t in after):
            problems.append("state leak: hot-water/heating talk after the emergency")
    if key == "luka":
        i = next((n for n, (w, t) in enumerate(log) if w == "tenant" and t.startswith("I said")), None)
        reply = next((t for w, t in log[i + 1:] if w == "debye"), "") if i is not None else ""
        if not ACK_RE.search(reply):
            problems.append(f"correction not acknowledged: {reply[:60]!r}")
    if repeats:
        problems.append(f"question repeated: {repeats[0][1][:60]!r}")
    if max_stalls >= 3:
        problems.append("3 turns without new information")
    if concluded_at is None and not resolved:
        problems.append("no conclusion")
    elif concluded_at is not None and concluded_at > 5:
        problems.append(f"concluded only after {concluded_at} turns")
    if got_area not in (expect_area if isinstance(expect_area, tuple) else (expect_area,)):
        problems.append(f"area {got_area} != {expect_area}")
    if concl and got_outcome not in allowed and not (resolved and "self_help" in allowed):
        problems.append(f"outcome {got_outcome} not in {allowed}")
    return {"name": name, "passed": not problems, "problems": problems, "area": got_area, "outcome": got_outcome,
            "turns": turns, "transcript": log}


def worker(names: list[str], out: str) -> int:
    import app.channels.base  # noqa: F401  (loads .env)
    from fastapi.testclient import TestClient

    from app.main import app

    track_ref: dict = {}
    et.instrument(track_ref)
    rows = []
    with TestClient(app) as client:
        for n in names:
            track_ref["t"] = {"events": []}
            try:
                r = run_chat(client, n, track_ref["t"])
            except Exception as exc:  # noqa: BLE001
                r = {"name": n, "passed": False, "problems": [f"{type(exc).__name__}: {exc}"], "transcript": []}
            rows.append(r)
            print(f"{'✓' if r['passed'] else '✗'} {n:20s} area={r.get('area')} outcome={r.get('outcome')} "
                  f"turns={r.get('turns')} {'; '.join(r['problems'])}", flush=True)
    Path(out).write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return 0


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=os.getenv("STRESS_OUT"))
    a = ap.parse_args()
    names = a.names or [*CHATS, "luka_1", "luka_2", "luka_3", "sparks_1"]
    names = [n if n != "luka" else "luka_1" for n in names]
    tmp = Path(tempfile.mkdtemp(prefix="debye-stress-"))
    atexit.register(shutil.rmtree, tmp, True)
    t0 = time.perf_counter()
    w = max(1, min(a.workers, len(names)))
    procs = []
    for i in range(w):
        of = tmp / f"rows_{i}.json"
        env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "STORAGE_DIR")}
        procs.append((subprocess.Popen([sys.executable, __file__, "--worker", json.dumps(names[i::w]), str(of)],
                                       env=env), of))
    rows = []
    for p, of in procs:
        p.wait()
        if of.exists():
            rows += json.loads(of.read_text(encoding="utf-8"))
    luka = [r for r in rows if r["name"].startswith("luka")]
    other = [r for r in rows if not r["name"].startswith("luka")]  # (sparks counts with the others)
    ok = sum(r["passed"] for r in other)
    pct = round(100 * ok / max(len(other), 1))
    print(f"\nstress: {ok}/{len(other)} chats passed ({pct}%), Luka's chat clean {sum(r['passed'] for r in luka)}/"
          f"{len(luka)}, {time.perf_counter() - t0:.0f} s")
    if a.out:
        Path(a.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if pct >= 90 and all(r["passed"] for r in luka) else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["--worker"]:
        sys.exit(worker(json.loads(sys.argv[2]), sys.argv[3]))
    sys.exit(main())
