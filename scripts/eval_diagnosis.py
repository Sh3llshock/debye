#!/usr/bin/env python3
"""Does the 'no hot water' diagnosis find all 17 KB causes?

One scripted tenant persona per cause (first message + free-text answers that match the cause's
signals; neutral answers for everything else). Each persona runs through the real app in-process:
real router, real agent (LLM from .env, default gpt-6-luna), fake WhatsApp send, a fresh database
and agent state per persona. Prints a table (expected vs. got) and writes docs/diagnosis-eval.md.

    python scripts/eval_diagnosis.py                 # all 17
    python scripts/eval_diagnosis.py hot_water_used_up boiler_fault
Cost: one pass ≈ 17 × 3–4 turns × 1–3 model calls.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

_tmp = Path(tempfile.mkdtemp(prefix="debye-eval-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_tmp / 'eval.db').as_posix()}")
os.environ.setdefault("STORAGE_DIR", str(_tmp / "storage"))
os.environ["DEMO_MODE"] = "1"
os.environ["WA_FAKE_SEND"] = "1"
os.environ["ROUTER_DEBOUNCE"] = "0"
os.environ["ELEVENLABS_API_KEY"] = ""  # no voice replies
os.environ["DIAGNOSIS_FOLLOWUP_SECONDS"] = "86400"  # no follow-up during the eval

PHONES = {"c_202": "490000000001", "c_205": "490000000012", "c_207": "490000000014"}

# Neutral free-text answers: consistent with "nothing special" for every question.
NEUTRAL = {
    "q_scope": "it's cold at the sinks too",
    "q_radiators": "no, the radiators are warm",
    "q_recent_use": "no, nobody used hot water before me",
    "q_waited": "yes, I let it run for a couple of minutes",
    "q_display": "the display looks normal, no code",
    "q_power": "yes, the lights and everything else work",
    "q_gas_stove": "yes, the gas stove lights normally",
    "q_knob": "the knob is turned fully to hot, that's fine",
    "q_pressure": "the needle is above 1 bar",
    "q_timing": "it stays cold even if I wait",
    "q_weather_pipe": "no, it's not just one tap",
    "q_other_tap": "no, nothing else was running",
    "q_recent_work": "no, no work was done recently",
    "q_handle_feel": "the handle feels normal",
    "q_heater_type": "no, there's no heater box",
}

# (cause_id, contact, first message, answers that differ from NEUTRAL, setup)
PERSONAS = [
    ("hot_water_used_up", "c_202", "My shower went cold halfway through this morning.",
     {"q_recent_use": "yes, my roommate showered for ages right before me"}, None),
    ("simultaneous_use", "c_202", "Every time I shower the water suddenly turns cold for a while.",
     {"q_other_tap": "yes, the dishwasher and the washing machine were running at the same time",
      "q_scope": "it's everywhere I think"}, None),
    ("not_run_long_enough", "c_202", "I just turned on the shower and there's no hot water.",
     {"q_waited": "no, only a few seconds", "q_scope": "the kitchen tap was cold too when I tried it quickly"}, None),
    ("shower_knob_or_limiter", "c_202", "Only my shower is cold, the kitchen tap is hot.",
     {"q_scope": "only the shower", "q_knob": "oh, the knob was turned to the cold side, sorry",
      "q_handle_feel": "it stops quite early when I turn it"}, None),
    ("shower_mixer_faulty", "c_202", "Only my shower is cold, the sinks are hot.",
     {"q_scope": "only the shower", "q_knob": "the knob is fully on hot",
      "q_waited": "yes, I let it run for two minutes", "q_handle_feel": "the handle feels normal"}, None),
    ("boiler_fault", "c_202", "No hot water and the radiators are cold too. The boiler display shows F.28.",
     {"q_radiators": "yes, all the radiators are cold", "q_display": "it shows F.28"}, None),
    ("low_system_pressure", "c_202", "No hot water and the heating is off, the boiler shows F.22.",
     {"q_radiators": "yes, the radiators are cold too", "q_display": "it shows F.22",
      "q_pressure": "the needle is below 1 bar"}, None),
    ("boiler_schedule_or_settings", "c_202",
     "The hot water is only lukewarm everywhere in the mornings, in the evening it's fine.",
     {"q_timing": "it gets warm later in the day, mornings are lukewarm",
      "q_display": "the display looks normal"}, None),
    ("diverter_valve_stuck", "c_202", "The radiators are nice and warm, but no tap gives hot water.",
     {"q_radiators": "no, the radiators are warm", "q_scope": "every tap, sinks and shower"}, None),
    ("tank_thermostat_or_scale", "c_202", "The hot water stays cold everywhere, no matter how long I wait.",
     {"q_timing": "it stays cold even after 10 minutes", "q_display": "display looks normal"}, None),
    ("circulation_pump_faulty", "c_202",
     "Hot water takes ages to arrive at every tap and then it's only lukewarm.",
     {"q_timing": "it gets warm slowly after a long time", "q_radiators": "the radiators are warm"}, None),
    ("no_power_to_boiler", "c_202", "No hot water, and the boiler display is completely dark.",
     {"q_display": "the display is completely dark", "q_power": "no, the power is out in the whole flat"}, None),
    ("electric_instant_heater", "c_205", "There's no hot water in my bathroom since this morning.",
     {"q_power": "yes, the lights work"}, None),
    ("supply_valve_closed_after_work", "c_202",
     "Since the plumber was here yesterday, my shower has no hot water. The kitchen is fine.",
     {"q_scope": "only the shower", "q_recent_work": "yes, a plumber worked in the bathroom yesterday"}, None),
    ("planned_maintenance", "c_202", "There's no hot water this morning.", {}, "notice_on"),
    ("gas_supply_interrupted", "c_202", "No hot water, and my gas stove won't light either.",
     {"q_gas_stove": "no, the stove doesn't light either", "q_display": "it shows an error code"}, None),
    ("frozen_or_damaged_pipe", "c_202",
     "Only my shower has almost no water coming out and it's cold. It's on the outside wall and it was freezing last night.",
     {"q_scope": "only the shower", "q_weather_pipe": "yes, just that one, very weak flow, outside wall"}, None),
]


def wa(phone: str, text: str, n: int) -> dict:
    return {"entry": [{"changes": [{"value": {"messages": [
        {"from": phone, "id": f"wamid.eval.{n}.{time.time_ns()}", "type": "text", "text": {"body": text}}]}}]}]}


def main(only: list[str]) -> int:
    import app.channels.base  # noqa: F401  (loads .env: OpenAI key, model)
    from fastapi.testclient import TestClient

    from app.agent import diagnosis, state
    from app.channels import whatsapp
    from app.main import app
    from app.seed import seed

    causes = diagnosis.causes()
    rows, transcripts = [], []
    with TestClient(app) as client:
        for cause_id, contact_id, first, overrides, setup in PERSONAS:
            if only and cause_id not in only:
                continue
            seed(reset=True)
            state.reset_all()
            whatsapp.clear_outbox()
            if setup == "notice_on":
                client.post("/demo/trigger/maintenance_notice", json={"notice_id": "notice_12_maint", "active": True})
            phone = PHONES[contact_id]
            answers = {**NEUTRAL, **overrides}
            log, times = [("tenant", first)], []
            n = 0
            seen_seq = 0

            def send(text):
                nonlocal n, seen_seq
                n += 1
                t0 = time.perf_counter()
                client.post("/webhooks/whatsapp", json=wa(phone, text, n))
                times.append(time.perf_counter() - t0)
                msgs = whatsapp.outbox(seen_seq)
                if msgs:
                    seen_seq = msgs[-1]["seq"]
                for m in msgs:
                    p = m["payload"]
                    body = p["text"]["body"] if p["type"] == "text" else p["interactive"]["body"]["text"]
                    log.append(("debye", body))
                return msgs

            msgs = send(first)
            conv = state.conversation(contact_id)
            for _ in range(6):
                d = conv.diagnosis or {}
                if d.get("concluded") or not msgs:
                    break
                diag = []
                for m in reversed(msgs):  # the open question may be followed by another message
                    ids = [b["reply"]["id"] for b in
                           m["payload"].get("interactive", {}).get("action", {}).get("buttons", [])]
                    diag = [i for i in ids if i.startswith("diag:")]
                    if diag:
                        break
                if not diag:
                    break  # no open question (consent etc.): the diagnosis is over
                qid = diag[0].split(":")[1]
                reply = answers.get(qid, "I'm not sure")
                log.append(("tenant", reply))
                msgs = send(reply)
            d = conv.diagnosis or {}
            got = d.get("concluded")
            outcome = causes.get(got, {}).get("outcome") if got else None
            ok = got == cause_id
            rows.append({"expected": cause_id, "got": got or "—", "ok": ok,
                         "outcome": outcome or "—", "expected_outcome": causes[cause_id]["outcome"],
                         "questions": len(d.get("asked", [])),
                         "turn_s": [round(t, 1) for t in times]})
            transcripts.append((cause_id, ok, log))
            print(f"{'✓' if ok else '✗'} {cause_id:32s} got {str(got):32s} q={len(d.get('asked', []))} "
                  f"turns={[round(t, 1) for t in times]}", flush=True)
            if setup == "notice_on":
                client.post("/demo/trigger/maintenance_notice", json={"notice_id": "notice_12_maint", "active": False})

    hits = sum(r["ok"] for r in rows)
    outcome_hits = sum(r["outcome"] == r["expected_outcome"] for r in rows)
    all_turns = [t for r in rows for t in r["turn_s"]]
    print(f"\naccuracy: {hits}/{len(rows)} causes ({100 * hits / max(len(rows), 1):.0f}%), "
          f"outcome right: {outcome_hits}/{len(rows)}, "
          f"avg questions {sum(r['questions'] for r in rows) / max(len(rows), 1):.1f}, "
          f"avg turn {sum(all_turns) / max(len(all_turns), 1):.1f}s")
    write_report(rows, transcripts, hits, outcome_hits, all_turns)
    return 0


def write_report(rows, transcripts, hits, outcome_hits, all_turns) -> None:
    model = os.getenv("OPENAI_CHAT_MODEL") or "gpt-6-luna"
    n = len(rows)
    lines = [
        "# Diagnosis eval: 17 causes",
        "",
        f"`scripts/eval_diagnosis.py`, one scripted tenant per KB cause (free-text answers that match the cause's "
        f"signals), real router + agent ({model}), fake WhatsApp send, fresh state per persona, one pass.",
        "",
        f"**Accuracy: {hits}/{n} causes ({100 * hits / max(n, 1):.0f}%)**, right outcome (self-help / caretaker / "
        f"technician / utility) {outcome_hits}/{n}, average {sum(r['questions'] for r in rows) / max(n, 1):.1f} "
        f"questions, average turn {sum(all_turns) / max(len(all_turns), 1):.1f} s.",
        "",
        "| | Expected cause | Got | Outcome (expected → got) | Questions | Turn times (s) |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {'✓' if r['ok'] else '✗'} | {r['expected']} | {r['got']} | {r['expected_outcome']} → "
                     f"{r['outcome']} | {r['questions']} | {', '.join(str(t) for t in r['turn_s'])} |")
    lines += ["", "## Transcripts", ""]
    for cause_id, ok, log in transcripts:
        lines.append(f"<details><summary>{'✓' if ok else '✗'} {cause_id}</summary>\n")
        for who, text in log:
            lines.append(f"- **{who}**: {text}")
        lines.append("\n</details>\n")
    (REPO / "docs" / "diagnosis-eval.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote docs/diagnosis-eval.md")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
