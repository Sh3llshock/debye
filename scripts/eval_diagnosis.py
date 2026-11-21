#!/usr/bin/env python3
"""Gold-conversation eval for the 'no hot water' diagnosis.

For every conversation in data/diagnosis/gold_conversations.json:
  1. Luna (the real router + agent, LLM from .env, default gpt-6-luna) plays Debye: in-process app,
     fake WhatsApp send, fresh database and agent state per conversation.
  2. A simulated tenant (same LLM) answers ONLY from the conversation's tenant_facts, follows the
     gold tenant turns (bursts, corrections, off-topic, questions back, language switch ...) and
     reports what happens after a 'try this' tip (self_help_result).
  3. A judge (same LLM) compares the transcript with the gold conversation: invented facts,
     clarification when needed, the edge case handled, tone, must_not rules.
  Code checks the cause, the outcome and the number of diagnostic questions (max 3).

    python scripts/eval_diagnosis.py --quick               # all 40, 1 pass, 10 worker processes (~4 min)
    python scripts/eval_diagnosis.py --passes 3 --out r.json   # 3 passes → r_p1.json, r_p2.json, r_p3.json
    python scripts/eval_diagnosis.py --only g01,g28        # only these (id prefixes)
    python scripts/smoke_diagnosis.py                      # the gate: ~10 exact chats, run before every report
    EVAL_BACKEND=/path/to/other/backend EVAL_OUT=before.json python scripts/eval_diagnosis.py
        # run the same conversations against another checkout (e.g. main, for a before/after table);
        # results go to EVAL_OUT as JSON, docs are written with --report before.json after.json
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import atexit
import shutil
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
BACKEND = Path(os.getenv("EVAL_BACKEND") or REPO / "backend").resolve()
sys.path.insert(0, str(BACKEND))

_tmp = Path(tempfile.mkdtemp(prefix="debye-eval-"))
atexit.register(shutil.rmtree, _tmp, True)  # temp DB + storage: removed at exit
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_tmp / 'eval.db').as_posix()}")
os.environ.setdefault("STORAGE_DIR", str(_tmp / "storage"))
os.environ["DEMO_MODE"] = "1"
os.environ["WA_FAKE_SEND"] = "1"
os.environ["WA_PROVIDER"] = "meta"
os.environ["ROUTER_DEBOUNCE"] = "0"
os.environ["ELEVENLABS_API_KEY"] = ""  # no voice replies
os.environ["DIAGNOSIS_FOLLOWUP_SECONDS"] = "86400"  # the simulated tenant reports the result itself

GOLD = json.loads((REPO / "data" / "diagnosis" / "gold_conversations.json").read_text(encoding="utf-8"))
KB = json.loads((REPO / "data" / "diagnosis" / "no_hot_water.json").read_text(encoding="utf-8"))
PHONES = {"c_202": "490000000001", "c_203": "490000000002", "c_205": "490000000012", "c_207": "490000000014"}
PHOTO = REPO / "data" / "demo" / "boiler_display_F28.jpg"
BURST_DEBOUNCE = 1.5
MAX_TENANT_STEPS = 9


# ------------------------------------------------------------------ LLM helpers (simulated tenant, judge)
def _client():
    from openai import OpenAI

    base = (os.getenv("OPENAI_BASE_URL") or "https://eu.api.openai.com/v1").rstrip("/")
    return OpenAI(base_url=base, timeout=60, max_retries=2)


def llm_json(system: str, user: str, schema: dict, name: str) -> dict:
    extra = {}
    effort = os.getenv("OPENAI_REASONING_EFFORT", "none")
    if effort:
        extra["reasoning_effort"] = effort
    r = _client().chat.completions.create(
        model=os.getenv("EVAL_MODEL") or os.getenv("OPENAI_CHAT_MODEL") or "gpt-6-luna",
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
        **extra,
    )
    return json.loads(r.choices[0].message.content)


def facts_text(conv: dict) -> str:
    qs = {q["id"]: q for q in KB["questions"]}
    lines = []
    for qid, key in conv["tenant_facts"].items():
        q = qs.get(qid)
        if q and key in q["answers"]:
            lines.append(f"- About \"{q['text']}\": {q['answers'][key]}.")
    return "\n".join(lines) or "- (nothing beyond your first message)"


SIM_SYSTEM = """You play a tenant who texts Debye, the WhatsApp assistant of the property manager, about \
cold water. You are the tenant, never the assistant. Write like a real person on WhatsApp: short, informal.

What is true for you (answer ONLY from this; if Debye asks something not covered here, say you don't know \
or can't check, never make up a fact):
{facts}

After Debye gives you a "try this" tip: {self_help}

Reference script: the tenant messages of a gold conversation for this exact situation, in order. Follow it: \
send its next unused tenant turn when it fits what Debye just said (adapt the words if Debye asked something \
else, but keep its special behaviour: a burst of messages, a correction, an off-topic remark, a question \
back, a language switch, typos, rudeness). If several tenant turns follow each other in the script with no \
Debye turn between them, that's a burst: return them together. Messages marked [photo] are sent with a \
photo of the boiler display.
{script}

If Debye asks for consent to share your details, say yes. If Debye offers time slots, take the first. When \
Debye has closed the topic (it's fixed, or a technician / the caretaker is on it and nothing is open) and \
the script has no tenant turn left, return done=true with no messages."""

SIM_SCHEMA = {
    "type": "object",
    "properties": {
        "messages": {"type": "array", "items": {
            "type": "object", "properties": {"text": {"type": "string"}, "photo": {"type": "boolean"}},
            "required": ["text", "photo"], "additionalProperties": False}},
        "done": {"type": "boolean"},
    },
    "required": ["messages", "done"], "additionalProperties": False,
}


def simulate_tenant(conv: dict, transcript: list[tuple[str, str]]) -> dict:
    sh = {"works": "after trying it, it works again; tell Debye so.",
          "fails": "after trying it, it's still cold; tell Debye so.",
          None: "(no tip expected)"}[conv.get("self_help_result")]
    script = []
    for t in conv["turns"]:
        if t["role"] == "tenant":
            script.append(f"- {'[photo] ' if t.get('media') else ''}{t['text']}")
        else:
            script.append("  (Debye replies)")
    system = SIM_SYSTEM.format(facts=facts_text(conv), self_help=sh, script="\n".join(script))
    convo = "\n".join(f"{'You' if who == 'tenant' else 'Debye'}: {text}" for who, text in transcript)
    return llm_json(system, f"The conversation so far:\n{convo}\n\nYour next message(s)?", SIM_SCHEMA, "tenant")


JUDGE_SYSTEM = """You review a WhatsApp conversation between Debye (an AI assistant for tenants with no \
hot water) and a tenant, against a gold conversation that shows the intended behaviour. Rules Debye must \
follow: a few words of lead-in ("Let's fix it.", "Ok."), short messages, no filler empathy, no emoji spam; \
never state a fact the tenant didn't give (and that isn't building data such as a maintenance notice, a \
neighbour's report or the heater type); one short clarifying question when an answer is ambiguous; self-help \
"try this, tell me if it works" when cheap; never ask about gas proactively; handle bursts as one, \
off-topic messages naturally while keeping the open question, questions back briefly and honestly without \
promises; answer in the tenant's language. Judge only Debye's messages. The consent question and the \
system's fixed confirmations are fine. Known from building data (not invented): the tenant's name, the \
heater type, maintenance notices, a neighbour's open report, the partner company's name. The order of \
questions may differ from the gold as long as it is sensible. must_not_violations lists ONLY rules from the \
given must_not list that Debye actually broke (empty if none)."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "invented_facts": {"type": "boolean", "description": "Debye stated a fact about the tenant's flat the tenant never gave"},
        "invented_examples": {"type": "string"},
        "clarification": {"type": "string", "enum": ["ok", "missing", "not_needed"],
                          "description": "missing = an ambiguous answer was guessed instead of clarified"},
        "edge_case": {"type": "string", "enum": ["handled", "not_handled", "none"],
                      "description": "the special behaviour of this gold conversation (burst, correction, off-topic, "
                                     "question back, language switch, rude tenant, 'it works again' ...)"},
        "tone": {"type": "integer", "description": "1-5; 5 = short, natural, matter-of-fact like the gold"},
        "must_not_violations": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string", "description": "one sentence"},
    },
    "required": ["invented_facts", "invented_examples", "clarification", "edge_case", "tone",
                 "must_not_violations", "notes"],
    "additionalProperties": False,
}


def judge(conv: dict, transcript: list[tuple[str, str]], metrics: dict) -> dict:
    gold = "\n".join(f"{t['role']}: {t['text']}" for t in conv["turns"])
    got = "\n".join(f"{who}: {text}" for who, text in transcript)
    user = (f"Gold conversation '{conv['title']}' (tags {conv['tags']}):\n{gold}\n\nmust_not: {conv['must_not']}\n\n"
            f"Actual conversation:\n{got}\n\nMeasured by code: {json.dumps(metrics)}")
    return llm_json(JUDGE_SYSTEM, user, JUDGE_SCHEMA, "verdict")


# ------------------------------------------------------------------ webhook payloads
_n = [0]


def wa_text(phone: str, text: str) -> dict:
    _n[0] += 1
    return {"entry": [{"changes": [{"value": {"messages": [
        {"from": phone, "id": f"wamid.eval.{_n[0]}.{time.time_ns()}", "type": "text", "text": {"body": text}}]}}]}]}


def wa_photo(phone: str, caption: str) -> dict:
    _n[0] += 1
    return {"entry": [{"changes": [{"value": {"messages": [
        {"from": phone, "id": f"wamid.eval.{_n[0]}.{time.time_ns()}", "type": "image",
         "image": {"id": f"eval-photo-{_n[0]}", "mime_type": "image/jpeg", "caption": caption or None}}]}}]}]}


def wa_tap(phone: str, id_: str, title: str) -> dict:
    _n[0] += 1
    return {"entry": [{"changes": [{"value": {"messages": [
        {"from": phone, "id": f"wamid.eval.{_n[0]}.{time.time_ns()}", "type": "interactive",
         "interactive": {"type": "button_reply", "button_reply": {"id": id_, "title": title}}}]}}]}]}


# ------------------------------------------------------------------ one conversation
def run_one(client, conv: dict, track: dict) -> dict:
    from app import router as msg_router
    from app.agent import diagnosis, state
    from app.channels import whatsapp
    from app.seed import seed

    seed(reset=True)
    state.reset_all()
    whatsapp.clear_outbox()
    phone = PHONES[conv["contact_id"]]

    seen = [0]

    def drain_outbox(log):
        msgs = whatsapp.outbox(seen[0])
        if msgs:
            seen[0] = msgs[-1]["seq"]
        for m in msgs:
            if m["to"].lstrip("+") != phone:
                continue
            p = m["payload"]
            if p["type"] == "text":
                body = p["text"]["body"]
            elif p["type"] == "interactive":
                it = p["interactive"]
                body = it["body"]["text"]
                if it["type"] == "button":
                    body += "  [" + " | ".join(b["reply"]["title"] for b in it["action"]["buttons"]) + "]"
                elif it["type"] == "list":
                    rows = [r["title"] for s in it["action"]["sections"] for r in s["rows"]]
                    body += "  [" + " | ".join(rows) + "]"
            else:
                body = f"({p['type']})"
            log.append(("debye", body))

    if conv.get("setup") == "notice_on":
        client.post("/demo/trigger/maintenance_notice", json={"notice_id": "notice_12_maint", "active": True})
    elif conv.get("setup") == "luka_boiler_case_open":
        client.post("/webhooks/whatsapp", json=wa_text(PHONES["c_202"], "The heating is cold in the whole flat"))
    drain_outbox([])

    log: list[tuple[str, str]] = []
    times: list[float] = []

    first_reply: list[float] = []

    def send(batch: list[dict]):
        t0 = time.perf_counter()
        wall0 = time.time()
        seq0 = seen[0]
        if len(batch) == 1:
            m = batch[0]
            client.post("/webhooks/whatsapp", json=wa_photo(phone, m["text"]) if m.get("photo") else wa_text(phone, m["text"]))
        else:  # a burst: really concurrent, with the production-like debounce
            msg_router.DEBOUNCE_SECONDS = BURST_DEBOUNCE
            threads = []
            for m in batch:
                body = wa_photo(phone, m["text"]) if m.get("photo") else wa_text(phone, m["text"])
                th = threading.Thread(target=client.post, args=("/webhooks/whatsapp",), kwargs={"json": body})
                th.start()
                threads.append(th)
                time.sleep(0.4)
            for th in threads:
                th.join()
            msg_router.DEBOUNCE_SECONDS = 0
        times.append(time.perf_counter() - t0)
        if not first_reply:  # first tenant message → first Debye message (the holding message if any)
            mine = [m for m in whatsapp.outbox(seq0) if m["to"].lstrip("+") == phone]
            if mine:
                first_reply.append(max(0.0, mine[0]["ts"] - wall0))
        for m in batch:
            log.append(("tenant", ("[photo] " if m.get("photo") else "") + m["text"]))
        drain_outbox(log)

    first = []
    for t in conv["turns"]:
        if t["role"] != "tenant":
            break
        first.append({"text": t["text"], "photo": bool(t.get("media"))})
    send(first)
    after_conclusion = 0
    for _ in range(MAX_TENANT_STEPS):
        if track["concluded"]:
            last = track["concluded"][-1]
            outcome = _outcome(last)
            if outcome != "self_help" or track["resolved"]:
                break
            after_conclusion += 1
            if after_conclusion > 3:
                break
        if track["resolved"]:
            break
        nxt = simulate_tenant(conv, log)
        if nxt["done"] or not nxt["messages"]:
            break
        send(nxt["messages"])

    got = track["concluded"][-1] if track["concluded"] else ("resolved_by_tenant" if track["resolved"] else None)
    outcome = _outcome(got) if got and got != "resolved_by_tenant" else ("self_help" if track["resolved"] else None)
    exp = conv["expected_cause"]
    cause_ok = got == exp or (track["resolved"] and conv["expected_outcome"] == "self_help"
                              and (exp in track["concluded"] or not track["concluded"]))
    questions = len(dict.fromkeys(q for q in track["asked"] if q != diagnosis.SAFETY_QID))
    try:
        planner_usage = list(state.conversation(conv["contact_id"]).diagnosis.get("planner_usage") or [])
    except Exception:  # noqa: BLE001
        planner_usage = []
    metrics = {"expected_cause": exp, "got_cause": got, "concluded_sequence": track["concluded"],
               "resolved_by_tenant": track["resolved"], "expected_outcome": conv["expected_outcome"],
               "got_outcome": outcome, "diagnostic_questions": questions,
               "max_questions": conv.get("max_diagnostic_questions", 3)}
    try:
        verdict = judge(conv, log, metrics)
    except Exception as exc:  # noqa: BLE001
        verdict = {"invented_facts": False, "invented_examples": "", "clarification": "not_needed",
                   "edge_case": "none", "tone": 0, "must_not_violations": [], "notes": f"judge failed: {exc}"}
    outcome_ok = outcome == conv["expected_outcome"]
    q_ok = questions <= metrics["max_questions"]
    passed = (cause_ok and outcome_ok and q_ok and not verdict["invented_facts"]
              and verdict["clarification"] != "missing" and verdict["edge_case"] != "not_handled"
              and verdict["tone"] >= 4 and not verdict["must_not_violations"])
    if conv.get("setup") == "notice_on":
        client.post("/demo/trigger/maintenance_notice", json={"notice_id": "notice_12_maint", "active": False})
    return {"id": conv["id"], "title": conv["title"], "tags": conv["tags"], **metrics,
            "cause_ok": cause_ok, "outcome_ok": outcome_ok, "questions_ok": q_ok, "passed": passed,
            "verdict": verdict, "turn_s": [round(t, 1) for t in times], "transcript": log,
            "first_reply_s": round(first_reply[0], 2) if first_reply else None,
            "first_turn_s": round(times[0], 2) if times else None, "planner_usage": planner_usage}


def _outcome(cause_id: str | None) -> str | None:
    if cause_id == "gas_smell":
        return "emergency"
    c = {c["id"]: c for c in KB["causes"]}.get(cause_id or "")
    return c["outcome"] if c else None


# ------------------------------------------------------------------ instrumenting the app (works on old code too)
def instrument(track_ref: dict) -> None:
    from app.agent import diagnosis
    from app.channels import whatsapp

    orig_conclude, orig_ask = diagnosis.conclude, diagnosis.ask

    async def conclude(contact, conv, cause_id, *a, **kw):
        res = await orig_conclude(contact, conv, cause_id, *a, **kw)
        track_ref["t"]["concluded"].append(cause_id)
        return res

    async def ask(contact, conv, qid, *a, **kw):
        await orig_ask(contact, conv, qid, *a, **kw)
        track_ref["t"]["asked"].append(qid)

    diagnosis.conclude, diagnosis.ask = conclude, ask
    if hasattr(diagnosis, "resolved_by_tenant"):
        orig_res = diagnosis.resolved_by_tenant

        async def resolved(contact, conv, text):
            track_ref["t"]["resolved"] = True
            return await orig_res(contact, conv, text)

        diagnosis.resolved_by_tenant = resolved
    orig_fu = diagnosis.on_follow_up

    async def on_follow_up(contact, cause_id, fixed):
        if fixed:
            track_ref["t"]["resolved"] = True
        return await orig_fu(contact, cause_id, fixed)

    diagnosis.on_follow_up = on_follow_up

    async def download_media(self, media):
        import re

        cap = media.caption or ""
        other_code = re.search(r"F\s?\.?\s?\d{2}", cap) and "28" not in cap  # "it shows F.22": not the F.28 photo
        return str(REPO / "data" / "demo" / "repair_done.jpg" if other_code else PHOTO)

    whatsapp.WhatsAppChannel.download_media = download_media


def run_worker(job_file: str, out_file: str) -> int:
    """One worker process: runs its share of (pass, conversation) jobs sequentially, with its own
    database and agent state (set up at import time), and writes the rows to out_file."""
    jobs = json.loads(Path(job_file).read_text(encoding="utf-8"))
    rows = run_convs([j["id"] for j in jobs], passes=[j["pass"] for j in jobs])
    Path(out_file).write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return 0


def run_parallel(ids: list[str], passes: int, workers: int, out: str | None) -> int:
    """Splits passes × conversations over worker processes (each isolated: own temp DB, own in-memory
    agent state), merges the results, writes one JSON per pass."""
    import subprocess

    convs = [c["id"] for c in GOLD["conversations"] if not ids or any(c["id"].startswith(o) for o in ids)]
    jobs = [{"pass": p, "id": cid} for p in range(1, passes + 1) for cid in convs]
    workers = max(1, min(workers, len(jobs)))
    tmp = Path(tempfile.mkdtemp(prefix="debye-eval-jobs-"))
    atexit.register(shutil.rmtree, tmp, True)
    procs = []
    t0 = time.perf_counter()
    for w in range(workers):
        jf, of = tmp / f"jobs_{w}.json", tmp / f"rows_{w}.json"
        jf.write_text(json.dumps(jobs[w::workers]), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "STORAGE_DIR")}
        procs.append((subprocess.Popen([sys.executable, __file__, "--worker", str(jf), str(of)], env=env), of))
    rows = []
    for proc, of in procs:
        proc.wait()
        if of.exists():
            rows += json.loads(of.read_text(encoding="utf-8"))
    by_pass = [[r for r in rows if r.get("pass") == p] for p in range(1, passes + 1)]
    order = {cid: i for i, cid in enumerate(convs)}
    for run in by_pass:
        run.sort(key=lambda r: order.get(r["id"], 0))
    print(f"\n{len(rows)} conversations in {time.perf_counter() - t0:.0f} s with {workers} workers")
    for p, run in enumerate(by_pass, 1):
        print(f"pass {p}: {summary_line(run)}")
    if passes > 1:
        print(f"pooled: {summary_line(rows)}")
    if out:
        for p, run in enumerate(by_pass, 1):
            path = out if passes == 1 else out.replace(".json", f"_p{p}.json")
            Path(path).write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
            print("wrote", path)
    return 0


def main(only: list[str]) -> int:
    rows = run_convs(only)
    out = os.getenv("EVAL_OUT")
    if out:
        Path(out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print("wrote", out)
    print(summary_line(rows))
    return 0


def run_convs(only: list[str], passes: list[int] | None = None) -> list[dict]:
    import app.channels.base  # noqa: F401  (loads .env: OpenAI key, model)
    from fastapi.testclient import TestClient

    from app.main import app

    track_ref: dict = {}
    instrument(track_ref)

    rows = []
    by_id = {c["id"]: c for c in GOLD["conversations"]}
    if passes is not None:  # worker: exact ids, one per job
        convs = [by_id[i] for i in only]
    else:
        convs = [c for c in GOLD["conversations"] if not only or any(c["id"].startswith(o) for o in only)]
    with TestClient(app) as client:
        for n, conv in enumerate(convs):
            track_ref["t"] = {"asked": [], "concluded": [], "resolved": False}
            try:
                r = run_one(client, conv, track_ref["t"])
            except Exception as exc:  # noqa: BLE001
                r = {"id": conv["id"], "title": conv["title"], "tags": conv["tags"], "passed": False,
                     "error": f"{type(exc).__name__}: {exc}", "transcript": []}
            r["pass"] = passes[n] if passes else 1
            rows.append(r)
            v = r.get("verdict") or {}
            print(f"{'✓' if r['passed'] else '✗'} {conv['id']:36s} got {str(r.get('got_cause')):30s} "
                  f"q={r.get('diagnostic_questions')} tone={v.get('tone')} inv={v.get('invented_facts')} "
                  f"edge={v.get('edge_case')} {r.get('error') or v.get('notes', '')[:90]}", flush=True)
    return rows


# ------------------------------------------------------------------ summary + report
SAME_OUTCOME = {frozenset({"diverter_valve_stuck", "tank_thermostat_or_scale"})}  # no natural question separates
# them for a tenant; both are a heating technician on the hot-water side, so the case is the same


def cause_equiv(r: dict) -> bool:
    return bool(r.get("cause_ok")) or frozenset({r.get("expected_cause"), r.get("got_cause")}) in SAME_OUTCOME


def summary(rows: list[dict]) -> dict:
    n = max(len(rows), 1)
    ok = [r for r in rows if "verdict" in r]
    tones = [r["verdict"]["tone"] for r in ok if r["verdict"]["tone"]]
    return {
        "n": len(rows),
        "passed": sum(r["passed"] for r in rows),
        "cause": sum(r.get("cause_ok", False) for r in rows),
        "cause_equiv": sum(cause_equiv(r) for r in rows),
        "cause_pct": round(100 * sum(r.get("cause_ok", False) for r in rows) / n),
        "cause_equiv_pct": round(100 * sum(cause_equiv(r) for r in rows) / n),
        "outcome": sum(r.get("outcome_ok", False) for r in rows),
        "questions_ok": sum(r.get("questions_ok", False) for r in rows),
        "avg_questions": round(sum(r.get("diagnostic_questions") or 0 for r in ok) / max(len(ok), 1), 2),
        "no_invented": sum(not r["verdict"]["invented_facts"] for r in ok),
        "clarify_ok": sum(r["verdict"]["clarification"] != "missing" for r in ok),
        "edge_ok": sum(r["verdict"]["edge_case"] != "not_handled" for r in ok),
        "edge_n": sum(r["verdict"]["edge_case"] != "none" for r in ok),
        "tone": round(sum(tones) / max(len(tones), 1), 2),
        "must_not_clean": sum(not r["verdict"]["must_not_violations"] for r in ok),
        "avg_turn_s": round(sum(t for r in ok for t in r["turn_s"]) / max(sum(len(r["turn_s"]) for r in ok), 1), 1),
        "pct": round(100 * sum(r["passed"] for r in rows) / n),
        "first_reply_s": _avg([r.get("first_reply_s") for r in ok]),
        "first_turn_s": _avg([r.get("first_turn_s") for r in ok]),
        "planner_calls": round(sum(len(r.get("planner_usage") or []) for r in ok) / max(len(ok), 1), 2),
        "planner_prompt_tokens": round(sum(u["prompt_tokens"] for r in ok for u in r.get("planner_usage") or [])
                                       / max(len(ok), 1)),
        "planner_completion_tokens": round(sum(u["completion_tokens"] for r in ok for u in r.get("planner_usage") or [])
                                           / max(len(ok), 1)),
        "planner_s": _avg([u["seconds"] for r in ok for u in r.get("planner_usage") or []]),
        "planner_errors": sum(1 for r in ok for u in r.get("planner_usage") or [] if u.get("error")),
    }


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def summary_line(rows) -> str:
    s = summary(rows)
    return (f"passed {s['passed']}/{s['n']} ({s['pct']}%), cause {s['cause']}/{s['n']}, outcome {s['outcome']}/{s['n']}, "
            f"≤3 questions {s['questions_ok']}/{s['n']} (avg {s['avg_questions']}), no invented facts "
            f"{s['no_invented']}/{s['n']}, tone {s['tone']}/5, avg turn {s['avg_turn_s']} s")


def write_report(before_runs: list[list[dict]], after_runs: list[list[dict]]) -> None:
    before = [r for run in before_runs for r in run]
    after = [r for run in after_runs for r in run]
    sb, sa = summary(before), summary(after)
    model = os.getenv("OPENAI_CHAT_MODEL") or "gpt-6-luna"
    rows = [
        ("Passed (all checks)", f"{sb['passed']}/{sb['n']} ({sb['pct']}%)", f"{sa['passed']}/{sa['n']} ({sa['pct']}%)"),
        ("Right cause", f"{sb['cause']}/{sb['n']} ({sb['cause_pct']}%)", f"{sa['cause']}/{sa['n']} ({sa['cause_pct']}%)"),
        ("Right cause, diverter ≈ tank", f"{sb['cause_equiv']}/{sb['n']} ({sb['cause_equiv_pct']}%)",
         f"{sa['cause_equiv']}/{sa['n']} ({sa['cause_equiv_pct']}%)"),
        ("Right outcome", f"{sb['outcome']}/{sb['n']}", f"{sa['outcome']}/{sa['n']}"),
        ("≤ 3 diagnostic questions", f"{sb['questions_ok']}/{sb['n']}", f"{sa['questions_ok']}/{sa['n']}"),
        ("Average diagnostic questions", sb["avg_questions"], sa["avg_questions"]),
        ("No invented facts", f"{sb['no_invented']}/{sb['n']}", f"{sa['no_invented']}/{sa['n']}"),
        ("Clarified when needed", f"{sb['clarify_ok']}/{sb['n']}", f"{sa['clarify_ok']}/{sa['n']}"),
        ("Edge case handled", f"{sb['edge_ok'] - (sb['n'] - sb['edge_n'])}/{sb['edge_n']}",
         f"{sa['edge_ok'] - (sa['n'] - sa['edge_n'])}/{sa['edge_n']}"),
        ("must_not rules kept", f"{sb['must_not_clean']}/{sb['n']}", f"{sa['must_not_clean']}/{sa['n']}"),
        ("Tone (judge, 1-5)", sb["tone"], sa["tone"]),
        ("Average turn time", f"{sb['avg_turn_s']} s", f"{sa['avg_turn_s']} s"),
    ]
    by_id = {r["id"]: r for r in before_runs[0]}
    hits = {}
    for run in after_runs:
        for r in run:
            hits.setdefault(r["id"], []).append(r.get("cause_ok", False))
    after = after_runs[0]
    lines = [
        "# Diagnosis eval: 40 gold conversations",
        "",
        "`scripts/eval_diagnosis.py`. For each conversation in `data/diagnosis/gold_conversations.json`, Luna "
        f"({model}) plays Debye through the real router and agent (fake WhatsApp send, fresh state). A simulated "
        "tenant (same model) answers only from the conversation's `tenant_facts` and follows the gold tenant turns "
        "(bursts are sent concurrently with the 2.5 s-style debounce, photos as real image messages). A judge (same "
        "model) checks invented facts, clarification, the edge case, tone and the `must_not` rules; code checks the "
        "cause, the outcome and the number of diagnostic questions. A conversation passes only if every check passes.",
        "",
        f"**Before** = `main` before this PR (KB v1, old prompt), {len(before_runs)} passes. **After** = this PR, "
        f"{len(after_runs)} passes. Numbers are pooled over all passes (40 conversations per pass).",
        "",
        "Per pass, right cause (after): " + ", ".join(f"{summary(run)['cause']}/{len(run)}" for run in after_runs)
        + "; before: " + ", ".join(f"{summary(run)['cause']}/{len(run)}" for run in before_runs) + ".",
        "",
        "| | Before | After |",
        "|---|---|---|",
    ] + [f"| {a} | {b} | {c} |" for a, b, c in rows] + [
        "",
        "## Per conversation",
        "",
        "Before/After columns show pass 1; 'Cause hits' counts the right cause over all after passes.",
        "",
        "| Conversation | Expected | Before | After | Cause hits | Q (after) | Tone (after) | Judge note (after) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in after:
        b = by_id.get(r["id"], {})
        v = r.get("verdict") or {}
        lines.append(f"| {r['id']} | {r.get('expected_cause', '')} | {'✓' if b.get('passed') else '✗'} "
                     f"{b.get('got_cause') or '—'} | {'✓' if r['passed'] else '✗'} {r.get('got_cause') or '—'} | "
                     f"{sum(hits.get(r['id'], []))}/{len(hits.get(r['id'], []))} | "
                     f"{r.get('diagnostic_questions', '')} | {v.get('tone', '')} | "
                     f"{(r.get('error') or v.get('notes') or '').replace('|', '/')} |")
    lines += ["", "## Transcripts (after)", ""]
    for r in after:
        lines.append(f"<details><summary>{'✓' if r['passed'] else '✗'} {r['id']}: {r['title']}</summary>\n")
        for who, text in r.get("transcript", []):
            lines.append(f"- **{who}**: {text}")
        v = r.get("verdict") or {}
        if v.get("must_not_violations") or v.get("invented_examples"):
            lines.append(f"\n_judge: {v.get('invented_examples', '')} {v.get('must_not_violations', '')}_")
        lines.append("\n</details>\n")
    (REPO / "docs" / "diagnosis-eval.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote docs/diagnosis-eval.md")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--report"]:
        load = lambda arg: [json.loads(Path(f).read_text(encoding="utf-8")) for f in arg.split(",")]  # noqa: E731
        write_report(load(sys.argv[2]), load(sys.argv[3]))
        sys.exit(0)
    if sys.argv[1:2] == ["--worker"]:
        sys.exit(run_worker(sys.argv[2], sys.argv[3]))
    import argparse

    ap = argparse.ArgumentParser(description="Gold-conversation eval (parallel worker processes)")
    ap.add_argument("ids", nargs="*", help="conversation id prefixes (default: all 40)")
    ap.add_argument("--only", default="", help="comma-separated id prefixes, e.g. g01,g28")
    ap.add_argument("--passes", type=int, default=1)
    ap.add_argument("--workers", type=int, default=int(os.getenv("EVAL_WORKERS", "8")))
    ap.add_argument("--quick", action="store_true", help="1 pass, 10 workers (≈ 3–5 min for all 40)")
    ap.add_argument("--sequential", action="store_true", help="old behaviour: one process, in order")
    ap.add_argument("--out", default=os.getenv("EVAL_OUT"), help="results JSON (per pass: _p1, _p2 ...)")
    a = ap.parse_args()
    ids = a.ids + [s for s in a.only.split(",") if s]
    if a.sequential:
        sys.exit(main(ids))
    sys.exit(run_parallel(ids, 1 if a.quick else a.passes, 10 if a.quick else a.workers, a.out))
