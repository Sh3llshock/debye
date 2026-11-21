#!/usr/bin/env python3
"""Smoke gate for the hot-water diagnosis: ~10 exact chats against the live model (LLM from .env),
each in its own process (own DB and agent state), checked by code. Run it before every report;
the 40 gold conversations (scripts/eval_diagnosis.py) are the score, this is the gate.

    python scripts/smoke_diagnosis.py            # all chats, in parallel; exit code 1 if any check fails
    python scripts/smoke_diagnosis.py luka burst # only these
    SMOKE_RUNS=3 python scripts/smoke_diagnosis.py   # each chat 3 times (the model is not deterministic)

Checks on every chat: no message sent twice in a row, at most one question per turn, at most 3
diagnostic questions, no statement of a fact the tenant never gave (radiators, display, pressure ...),
never two languages in one message. Plus per-chat checks (first question is the scope, the
contradiction is not concluded, German stays German, ...).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _s in (sys.stdout, sys.stderr):  # ✓/✗ on Windows cp1252 consoles
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
PHONE = "490000000001"  # c_202 (Luka; stored language "de" in some setups)

CHATS = {
    "luka": ["my shower is cold", "sinks too", "no", "everything", "as I was cooking just now"],
    "short_shower": ["my shower is cold"],
    "short_no_hot_water": ["no hot water"],
    "short_freezing": ["shower freezing"],
    "fuse": ["no hot water", "all taps", "no one", "the screen is dark", "I flipped the fuse, it works now"],
    "german": ["Kein warmes Wasser in der Dusche", "Überall, auch in der Küche", "Nein, niemand"],
    "burst": [["no hot water", "in the kitchen too"]],  # a list = sent together (a burst)
    "contradiction": ["the hot water just stopped", "everywhere", "no", "actually my flatmate just had a long shower"],
    "rude": ["no hot water", "this is useless, just send someone"],
    "knob": ["only the shower is cold, the sink is hot", "it stops at 38", "that worked, it's hot now"],
    "roommate": ["no hot water", "only the shower", "my roommate showered for ages just before"],
    "frustrated": ["shower cold again, this is useless just send someone"],
}

FACTS = {"radiator": "radiat", "display": "display", "pressure": "pressure", "error code": "code",
         "plumber": "plumb", "outside wall": "outside", "fuse": "fuse"}


# ------------------------------------------------------------------ one chat (worker process)
def run_chat(name: str) -> dict:
    sys.path.insert(0, str(REPO / "backend"))
    tmp = Path(tempfile.mkdtemp(prefix="debye-smoke-"))
    import atexit
    import shutil

    atexit.register(shutil.rmtree, tmp, True)  # temp DB + storage: removed at exit
    os.environ["DATABASE_URL"] = f"sqlite:///{(tmp / 'smoke.db').as_posix()}"
    os.environ["STORAGE_DIR"] = str(tmp / "storage")
    os.environ.update({"DEMO_MODE": "1", "WA_FAKE_SEND": "1", "WA_PROVIDER": "meta", "ROUTER_DEBOUNCE": "0",
                       "ELEVENLABS_API_KEY": "", "DIAGNOSIS_FOLLOWUP_SECONDS": "86400"})
    import app.channels.base  # noqa: F401  (.env)
    from fastapi.testclient import TestClient

    from app import router as msg_router
    from app.agent import diagnosis, state
    from app.channels import whatsapp
    from app.main import app
    from app.seed import seed

    turns = []
    with TestClient(app) as client:
        seed(reset=True)
        state.reset_all()
        whatsapp.clear_outbox()
        seen = 0
        for i, step in enumerate(CHATS[name]):
            msgs = step if isinstance(step, list) else [step]

            def post(text, k):
                client.post("/webhooks/whatsapp", json={"entry": [{"changes": [{"value": {"messages": [
                    {"from": PHONE, "id": f"wamid.smoke.{i}.{k}.{time.time_ns()}", "type": "text",
                     "text": {"body": text}}]}}]}]})

            if len(msgs) > 1:  # a real burst: concurrent, production-like debounce
                msg_router.DEBOUNCE_SECONDS = 1.5
                ths = [threading.Thread(target=post, args=(t, k)) for k, t in enumerate(msgs)]
                for th in ths:
                    th.start()
                    time.sleep(0.3)
                for th in ths:
                    th.join()
                msg_router.DEBOUNCE_SECONDS = 0
            else:
                post(msgs[0], 0)
            out = whatsapp.outbox(seen)
            if out:
                seen = out[-1]["seq"]
            sent = []
            for m in out:
                p = m["payload"]
                if p["type"] == "text":
                    sent.append({"text": p["text"]["body"], "ids": []})
                else:
                    it = p["interactive"]
                    ids = [b["reply"]["id"] for b in it["action"].get("buttons", [])] or \
                        [r["id"] for s in it["action"].get("sections", []) for r in s["rows"]]
                    sent.append({"text": it["body"]["text"], "ids": ids})
            turns.append({"tenant": msgs, "debye": sent})
        d = state.conversation("c_202").diagnosis or {}
        conv = state.conversation("c_202")
        from app import auth  # the staff API needs a staff session

        staff = {"Authorization": f"Bearer {auth.make_token('staff', 'c_401')}"}
        cases = client.get("/api/staff/cases", headers=staff).json()
    return {"name": name, "turns": turns, "concluded": d.get("concluded"), "asked": d.get("asked", []),
            "answers": d.get("answers", {}), "step": conv.step, "lang": conv.lang,
            "cases": [{"trade": c.get("trade"), "status": c.get("status")} for c in cases]}


# ------------------------------------------------------------------ checks
def _is_question(m):
    return any(i.startswith("diag:") for i in m["ids"]) or m["text"].rstrip().endswith("?")


def _tech(cases):  # a case for a technician (self-help records are 'hot_water' and get closed)
    return [c for c in cases if c["trade"] in ("heating", "plumbing", "electrical")]


def check(r: dict) -> list[str]:
    sys.path.insert(0, str(REPO / "backend"))
    from app.agent.diagnosis import _looks_english, _looks_german  # noqa: PLC0415

    fails = []
    flat = [m["text"] for t in r["turns"] for m in t["debye"]]
    for a, b in zip(flat, flat[1:]):
        if a == b:
            fails.append(f"same message twice in a row: {a[:70]!r}")
    for t in r["turns"]:
        qs = [m for m in t["debye"] if _is_question(m) and "share your name" not in m["text"]
              and "deinen Namen" not in m["text"]]
        if len(qs) > 1:
            fails.append(f"{len(qs)} questions in one turn after {t['tenant']}: " + " / ".join(m["text"][:50] for m in qs))
    if len(set(r["asked"])) > 3:
        fails.append(f"{len(set(r['asked']))} diagnostic questions")
    said = " ".join(x for t in r["turns"] for x in t["tenant"]).lower()
    for t in r["turns"]:
        for m in t["debye"]:
            if _is_question(m):
                continue  # asking about it is fine; stating it is not
            low = m["text"].lower()
            for word, stem in FACTS.items():
                if word in low and stem not in said:
                    fails.append(f"states '{word}' the tenant never mentioned: {m['text'][:80]!r}")
            if _looks_english(m["text"]) and _looks_german(m["text"]):
                fails.append(f"mixed languages: {m['text'][:80]!r}")
    first = r["turns"][0]["debye"]
    n = r["name"]
    if n in ("luka", "short_shower", "short_no_hot_water", "short_freezing", "fuse"):
        ids = [i for m in first for i in m["ids"]]
        if not any(i.startswith("diag:q_scope:") for i in ids):
            fails.append(f"first question is not the scope: {[m['text'][:60] for m in first]}")
    if n == "luka" and r["concluded"] in ("simultaneous_use", "hot_water_used_up") and \
            r["answers"].get("q_hot_water_use") == "no":
        fails.append("concluded hot-water use although the tenant said 'no'")
    if n == "luka" and r["concluded"] == "simultaneous_use":
        fails.append("concluded simultaneous use from 'as I was cooking' after 'no' (needs a clarification)")
    if n == "contradiction" and r["concluded"] == "hot_water_used_up" and \
            not any("just to check" in m["text"].lower() or "?" in m["text"] for m in r["turns"][-1]["debye"]):
        fails.append("contradiction concluded without a clarification")
    if n == "german":
        for m in (m for t in r["turns"] for m in t["debye"]):
            if _looks_english(m["text"]):
                fails.append(f"English message in a German chat: {m['text'][:80]!r}")
    if n == "burst":
        if len([m for m in first if _is_question(m)]) != 1:
            fails.append(f"burst: expected one reply question, got {[m['text'][:50] for m in first]}")
        if any(i.startswith("diag:q_scope:") for m in first for i in m["ids"]):
            fails.append("burst: asked the scope although 'in the kitchen too' answered it")
    if n == "fuse" and _tech(r["cases"]):
        fails.append("fuse chat: a technician case was opened although it works again")
    if n == "rude" and not [c for c in r["cases"] if c["status"] != "closed"]:
        fails.append("rude chat: no case for a technician")
    if n == "roommate":
        if r["concluded"] != "hot_water_used_up":
            fails.append(f"roommate chat: concluded {r['concluded']} instead of the used-up tip")
        if any("knob" in m["text"].lower() for m in r["turns"][-1]["debye"]):
            fails.append("roommate chat: re-asked the knob after the volunteered answer")
    if n == "frustrated":
        last = r["turns"][-1]["debye"]
        if len(last) > 2:
            fails.append(f"frustrated: {len(last)} messages (max 2): " + " / ".join(m["text"][:40] for m in last))
        if any("heating" in m["text"].lower() for m in last):
            fails.append("frustrated: assumed 'heating' although the trade is unknown")
        if not [c for c in r["cases"] if c["status"] != "closed"]:
            fails.append("frustrated: no case")
    if n == "knob" and (r["concluded"] not in (None, "shower_knob_or_limiter") or _tech(r["cases"])):
        fails.append(f"knob chat: concluded {r['concluded']} / cases {r['cases']}")
    return fails


def main(names: list[str]) -> int:
    if names[:1] == ["--worker"]:
        print(json.dumps(run_chat(names[1]), ensure_ascii=False))
        return 0
    names = names or list(CHATS)
    runs = int(os.getenv("SMOKE_RUNS", "1"))
    t0 = time.perf_counter()
    procs = [(n, k, subprocess.Popen([sys.executable, __file__, "--worker", n], stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, encoding="utf-8"))
             for n in names for k in range(runs)]
    bad = 0
    for n, k, p in procs:
        outp, _ = p.communicate()
        try:
            r = json.loads(outp.strip().splitlines()[-1])
        except (ValueError, IndexError):
            print(f"✗ {n} (run {k + 1}): worker crashed")
            bad += 1
            continue
        fails = check(r)
        bad += bool(fails)
        print(f"{'✓' if not fails else '✗'} {n} (run {k + 1}) → {r['concluded'] or r['step']}")
        for f in fails:
            print(f"    - {f}")
        if fails or os.getenv("SMOKE_VERBOSE"):
            for t in r["turns"]:
                print(f"    T: {' + '.join(t['tenant'])}")
                for m in t["debye"]:
                    print(f"    D: {m['text']}")
    print(f"\n{len(procs) - bad}/{len(procs)} smoke chats passed in {time.perf_counter() - t0:.0f} s")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
