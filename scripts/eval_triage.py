"""Triage eval: the 66 gold conversations in data/diagnosis/triage_gold_{a,b}.json, end to end.

Same method as scripts/eval_diagnosis.py (whose helpers it reuses): the real app on a temp DB, Luna as
Debye, a simulated tenant (same model) that answers only from the conversation's tenant_facts and follows
the gold tenant turns, and a judge. Differences: every area's KB (facts, outcomes), the routed area is
checked, and a two-problem conversation runs until both problems are settled (each problem scored on its
own: cause, outcome, at most max_diagnostic_questions questions).

  python scripts/eval_triage.py                     # all 66, 8 worker processes
  python scripts/eval_triage.py --smoke             # the 12 smoke ids (triage_smoke_{a,b}.json)
  python scripts/eval_triage.py ta01 tb3 --workers 4
  python scripts/eval_triage.py --report out_p1.json[,out_p2.json]   # docs/triage-eval.md
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_diagnosis as ev  # noqa: E402  (sets up the temp DB, env and sys.path for the backend)

REPO = ev.REPO
DATA = REPO / "data" / "diagnosis"
GOLD = [c for f in ("triage_gold_a.json", "triage_gold_b.json")
        for c in json.loads((DATA / f).read_text(encoding="utf-8"))["conversations"]]
SMOKE = [i for f in ("triage_smoke_a.json", "triage_smoke_b.json") if (DATA / f).exists()
         for i in (lambda d: d.get("ids", d) if isinstance(d, dict) else d)(json.loads((DATA / f).read_text("utf-8")))]
PHONES = {"c_202": "490000000001", "c_203": "490000000002", "c_204": "490000000011", "c_205": "490000000012",
          "c_206": "490000000013", "c_207": "490000000014"}
MAX_TENANT_STEPS = 12


def _kbs() -> dict[str, dict]:
    out = {}
    for f in DATA.glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(d, dict) and d.get("questions") and d.get("causes"):
            out[f.stem] = d
    return out


KBS = _kbs()
QUESTIONS = {q["id"]: q for kb in KBS.values() for q in kb["questions"]}


def outcome_of(area: str | None, cause_id: str | None) -> str | None:
    if cause_id == "gas_smell":
        return "emergency"
    kb = KBS.get(area or "no_hot_water") or {}
    c = {c["id"]: c for c in kb.get("causes", [])}.get(cause_id or "")
    if c:
        return c["outcome"]
    for kb in KBS.values():  # area unknown: the first KB that has the cause
        for c in kb["causes"]:
            if c["id"] == cause_id:
                return c["outcome"]
    return None


# ------------------------------------------------------------------ simulated tenant + judge, all areas
def facts_text(conv: dict) -> str:
    lines = []
    for facts in (conv.get("tenant_facts") or {}, conv.get("second_tenant_facts") or {}):
        for qid, key in facts.items():
            q = QUESTIONS.get(qid)
            if q and key in q["answers"]:
                lines.append(f"- About \"{q['text']}\": {q['answers'][key]}.")
    return "\n".join(lines) or "- (nothing beyond your first message)"


SIM_SYSTEM = ev.SIM_SYSTEM.replace("about \\\ncold water", "about a problem").replace(
    "about cold water", "about a problem in their flat").replace(
    "photo of the boiler display", "photo of the problem")
JUDGE_SYSTEM = ev.JUDGE_SYSTEM.replace(
    "an AI assistant for tenants with no \\\nhot water", "an AI assistant for tenants' household problems").replace(
    "for tenants with no hot water", "for tenants' household problems").replace(
    "never ask about gas proactively;", "never ask about gas proactively; in an emergency (flooding, a burning "
    "smell, fire or smoke, a CO alarm, a break-in, someone stuck in the lift, the whole building dark) the "
    "safety steps come first with no question before them; a vague report gets one 'what is it about' "
    "question; with two problems, the first is settled before Debye turns to the second;")


def simulate_tenant(conv: dict, transcript: list[tuple[str, str]]) -> dict:
    sh = {"works": "after trying it, the problem is solved; tell Debye so.",
          "fails": "after trying it, it's still not fixed; tell Debye so.",
          None: "(no tip expected)"}[conv.get("self_help_result")]
    script = [f"- {'[photo] ' if t.get('media') else ''}{t['text']}" if t["role"] == "tenant" else "  (Debye replies)"
              for t in conv["turns"]]
    system = SIM_SYSTEM.format(facts=facts_text(conv), self_help=sh, script="\n".join(script))
    convo = "\n".join(f"{'You' if who == 'tenant' else 'Debye'}: {text}" for who, text in transcript)
    return ev.llm_json(system, f"The conversation so far:\n{convo}\n\nYour next message(s)?", ev.SIM_SCHEMA, "tenant")


def judge(conv: dict, transcript: list[tuple[str, str]], metrics: dict) -> dict:
    gold = "\n".join(f"{t['role']}: {t['text']}" for t in conv["turns"])
    got = "\n".join(f"{who}: {text}" for who, text in transcript)
    user = (f"Gold conversation '{conv['title']}' (tags {conv['tags']}):\n{gold}\n\nmust_not: {conv['must_not']}\n\n"
            f"Actual conversation:\n{got}\n\nMeasured by code: {json.dumps(metrics)}")
    return ev.llm_json(JUDGE_SYSTEM, user, ev.JUDGE_SCHEMA, "verdict")


# ------------------------------------------------------------------ instrumentation: per-area events
def instrument(track_ref: dict) -> None:
    from app.agent import diagnosis

    orig_conclude, orig_ask, orig_fu = diagnosis.conclude, diagnosis.ask, diagnosis.on_follow_up
    orig_res = diagnosis.resolved_by_tenant

    async def conclude(contact, conv, cause_id, *a, **kw):
        area = diagnosis.area_of(conv) if conv.diagnosis else "no_hot_water"
        events = track_ref["t"]["events"]
        at = len(events)  # a conclusion may start the queued second problem inside the call: keep the order
        res = await orig_conclude(contact, conv, cause_id, *a, **kw)
        if not (isinstance(res, dict) and res.get("note") == "already concluded"):
            events.insert(at, ("concluded", area, cause_id))
        return res

    async def ask(contact, conv, qid, *a, **kw):
        await orig_ask(contact, conv, qid, *a, **kw)
        track_ref["t"]["events"].append(("asked", diagnosis.area_of(conv), qid))

    async def on_follow_up(contact, cause_id, fixed):
        from app.agent import state
        from app.agent import _backend as be

        area = diagnosis.area_of(state.conversation(be.attr(contact, "id")))
        if fixed:
            track_ref["t"]["events"].append(("resolved", area, cause_id))
        return await orig_fu(contact, cause_id, fixed)

    async def resolved(contact, conv, text):
        track_ref["t"]["events"].append(("resolved", diagnosis.area_of(conv), None))
        return await orig_res(contact, conv, text)

    diagnosis.conclude, diagnosis.ask, diagnosis.on_follow_up = conclude, ask, on_follow_up
    diagnosis.resolved_by_tenant = resolved
    ev.instrument({"t": {"asked": [], "concluded": [], "resolved": False}})  # media download stub only
    diagnosis.conclude, diagnosis.ask, diagnosis.on_follow_up = conclude, ask, on_follow_up
    diagnosis.resolved_by_tenant = resolved


def problem_view(events: list, area: str) -> dict:
    """What happened for one area: conclusions in order, resolved, questions asked."""
    concl = [c for kind, a, c in events if kind == "concluded" and a == area]
    resolved = any(kind == "resolved" and a == area for kind, a, _ in events)
    asked = list(dict.fromkeys(q for kind, a, q in events if kind == "asked" and a == area and q != "q_safety"))
    return {"concluded": concl, "resolved": resolved, "questions": len(asked)}


def settled(events: list, area: str) -> bool:
    v = problem_view(events, area)
    if v["resolved"]:
        return True
    return bool(v["concluded"]) and outcome_of(area, v["concluded"][-1]) != "self_help"


def score_problem(events, area, exp_cause, exp_outcome, max_q) -> dict:
    v = problem_view(events, area)
    got = v["concluded"][-1] if v["concluded"] else ("resolved_by_tenant" if v["resolved"] else None)
    outcome = outcome_of(area, got) if got and got != "resolved_by_tenant" else ("self_help" if v["resolved"] else None)
    if v["resolved"] and v["concluded"] and outcome_of(area, v["concluded"][-1]) == "self_help":
        outcome = "self_help"
    cause_ok = got == exp_cause or (v["resolved"] and exp_outcome == "self_help"
                                    and (exp_cause in v["concluded"] or not v["concluded"]))
    return {"area": area, "expected_cause": exp_cause, "got_cause": got, "concluded_sequence": v["concluded"],
            "expected_outcome": exp_outcome, "got_outcome": outcome, "cause_ok": cause_ok,
            "outcome_ok": outcome == exp_outcome, "diagnostic_questions": v["questions"], "max_questions": max_q,
            "questions_ok": v["questions"] <= max_q}


def run_one(client, conv: dict, track: dict) -> dict:
    from app import router as msg_router
    from app.agent import state
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
                    body += "  [" + " | ".join(r["title"] for s in it["action"]["sections"] for r in s["rows"]) + "]"
            else:
                body = f"({p['type']})"
            log.append(("debye", body))

    drain_outbox([])
    log: list[tuple[str, str]] = []
    times: list[float] = []

    def send(batch: list[dict]):
        import threading

        t0 = time.perf_counter()
        if len(batch) == 1:
            m = batch[0]
            client.post("/webhooks/whatsapp",
                        json=ev.wa_photo(phone, m["text"]) if m.get("photo") else ev.wa_text(phone, m["text"]))
        else:  # a burst: concurrent, with the production-like debounce
            msg_router.DEBOUNCE_SECONDS = ev.BURST_DEBOUNCE
            threads = []
            for m in batch:
                body = ev.wa_photo(phone, m["text"]) if m.get("photo") else ev.wa_text(phone, m["text"])
                th = threading.Thread(target=client.post, args=("/webhooks/whatsapp",), kwargs={"json": body})
                th.start()
                threads.append(th)
                time.sleep(0.4)
            for th in threads:
                th.join()
            msg_router.DEBOUNCE_SECONDS = 0
        times.append(time.perf_counter() - t0)
        for m in batch:
            log.append(("tenant", ("[photo] " if m.get("photo") else "") + m["text"]))
        drain_outbox(log)

    areas = [conv["expected_area"]] + ([conv["second_area"]] if conv.get("second_area") else [])
    first = []
    for t in conv["turns"]:
        if t["role"] != "tenant":
            break
        first.append({"text": t["text"], "photo": bool(t.get("media"))})
    send(first)
    idle_after_settled = 0
    consent_answered = False
    for _ in range(MAX_TENANT_STEPS):
        ev_ = track["events"]
        if all(settled(ev_, a) for a in areas):
            asking_consent = bool(log) and log[-1][0] == "debye" and "Is it okay if I share" in log[-1][1] \
                or "Ist es okay, wenn ich" in (log[-1][1] if log else "")
            if not asking_consent or consent_answered:
                break
            consent_answered = True  # one more tenant turn: the answer to the consent question
        last = next((e for e in reversed(ev_) if e[0] == "concluded"), None)
        if last and outcome_of(last[1], last[2]) == "self_help":
            idle_after_settled += 1
            if idle_after_settled > 4:
                break
        nxt = simulate_tenant(conv, log)
        if nxt["done"] or not nxt["messages"]:
            break
        send(nxt["messages"])

    events = track["events"]
    p1 = score_problem(events, conv["expected_area"], conv["expected_cause"], conv["expected_outcome"],
                       conv.get("max_diagnostic_questions", 3))
    routed = next((a for kind, a, _ in events if kind in ("asked", "concluded")), None)
    p2 = None
    if conv.get("second_area"):
        sa = conv["second_area"]
        p2 = score_problem(events, sa, conv["second_cause"], outcome_of(sa, conv["second_cause"]),
                           1 if sa == "management" else 3)
    metrics = {**p1, "routed_area": routed, "second": p2}
    try:
        verdict = judge(conv, log, metrics)
    except Exception as exc:  # noqa: BLE001
        verdict = {"invented_facts": False, "invented_examples": "", "clarification": "not_needed",
                   "edge_case": "none", "tone": 0, "must_not_violations": [], "notes": f"judge failed: {exc}"}
    area_ok = routed == conv["expected_area"]
    probs_ok = all(p["cause_ok"] and p["outcome_ok"] and p["questions_ok"] for p in (p1, p2) if p)
    passed = (area_ok and probs_ok and not verdict["invented_facts"] and verdict["clarification"] != "missing"
              and verdict["edge_case"] != "not_handled" and verdict["tone"] >= 4 and not verdict["must_not_violations"])
    return {"id": conv["id"], "title": conv["title"], "tags": conv["tags"], **metrics, "area_ok": area_ok,
            "cause_ok": p1["cause_ok"] and (p2 is None or p2["cause_ok"]),
            "outcome_ok": p1["outcome_ok"] and (p2 is None or p2["outcome_ok"]),
            "questions_ok": p1["questions_ok"] and (p2 is None or p2["questions_ok"]),
            "passed": passed, "verdict": verdict, "turn_s": [round(t, 1) for t in times], "transcript": log}


def run_convs(ids: list[str], passes: list[int] | None = None) -> list[dict]:
    import app.channels.base  # noqa: F401  (loads .env: OpenAI key, model)
    from fastapi.testclient import TestClient

    from app.main import app

    track_ref: dict = {}
    instrument(track_ref)
    by_id = {c["id"]: c for c in GOLD}
    rows = []
    with TestClient(app) as client:
        for n, cid in enumerate(ids):
            conv = by_id[cid]
            track_ref["t"] = {"events": []}
            try:
                r = run_one(client, conv, track_ref["t"])
            except Exception as exc:  # noqa: BLE001
                r = {"id": cid, "title": conv["title"], "tags": conv["tags"], "passed": False,
                     "error": f"{type(exc).__name__}: {exc}", "transcript": []}
            r["pass"] = passes[n] if passes else 1
            rows.append(r)
            v = r.get("verdict") or {}
            print(f"{'✓' if r['passed'] else '✗'} {cid:40s} area={r.get('routed_area')} got={r.get('got_cause')} "
                  f"q={r.get('diagnostic_questions')} tone={v.get('tone')} "
                  f"{r.get('error') or v.get('notes', '')[:90]}", flush=True)
    return rows


def run_parallel(ids: list[str], passes: int, workers: int, out: str | None) -> int:
    import subprocess

    convs = [c["id"] for c in GOLD if not ids or any(c["id"].startswith(o) for o in ids)]
    jobs = [{"pass": p, "id": cid} for p in range(1, passes + 1) for cid in convs]
    workers = max(1, min(workers, len(jobs)))
    tmp = Path(tempfile.mkdtemp(prefix="debye-triage-jobs-"))
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
    order = {cid: i for i, cid in enumerate(convs)}
    by_pass = [sorted((r for r in rows if r.get("pass") == p), key=lambda r: order.get(r["id"], 0))
               for p in range(1, passes + 1)]
    print(f"\n{len(rows)} conversations in {time.perf_counter() - t0:.0f} s with {workers} workers")
    for p, run in enumerate(by_pass, 1):
        print(f"pass {p}: {summary_line(run)}")
    if out:
        for p, run in enumerate(by_pass, 1):
            path = out if passes == 1 else out.replace(".json", f"_p{p}.json")
            Path(path).write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
            print("wrote", path)
    return 0


def summary_line(rows) -> str:
    s = ev.summary(rows)
    area = sum(r.get("area_ok", False) for r in rows)
    return f"area {area}/{s['n']}, " + ev.summary_line(rows)


# ------------------------------------------------------------------ report
def write_report(runs: list[list[dict]], path: Path = REPO / "docs" / "triage-eval.md") -> None:
    rows = [r for run in runs for r in run]
    s = ev.summary(rows)
    n = max(s["n"], 1)
    area_n = sum(r.get("area_ok", False) for r in rows)
    lines = [
        f"# Triage eval: {len(runs[0]) if runs else 0} gold conversations, {len(runs)} pass(es)",
        "",
        "`scripts/eval_triage.py` runs every conversation in `data/diagnosis/triage_gold_a.json` and "
        "`triage_gold_b.json` end to end: the real app on a temp database, Luna as Debye, a simulated tenant (same "
        "model) that answers only from the conversation's `tenant_facts` and follows the gold tenant turns, and a "
        "judge (same model). A conversation passes when the routed area, the cause, the outcome and the question "
        "limit match (for two problems: both), and the judge finds no invented fact, no missed clarification, the "
        "edge case handled, tone at least 4/5 and no `must_not` broken.",
        "",
        "| | result |",
        "|---|---|",
        f"| passed | **{s['passed']}/{s['n']} ({s['pct']}%)** |",
        f"| area routed right | {area_n}/{s['n']} ({round(100 * area_n / n)}%) |",
        f"| cause | {s['cause']}/{s['n']} ({s['cause_pct']}%) |",
        f"| outcome | {s['outcome']}/{s['n']} |",
        f"| within the question limit | {s['questions_ok']}/{s['n']} (avg {s['avg_questions']}) |",
        f"| no invented facts | {s['no_invented']}/{s['n']} |",
        f"| tone | {s['tone']}/5 |",
        f"| must_not clean | {s['must_not_clean']}/{s['n']} |",
        f"| avg turn | {s['avg_turn_s']} s |",
        "",
        "## By area",
        "",
        "| area | passed | cause |",
        "|---|---|---|",
    ]
    by_area: dict[str, list] = {}
    for r in rows:
        exp = next((c["expected_area"] for c in GOLD if c["id"] == r["id"]), "?")
        by_area.setdefault(exp, []).append(r)
    for a, rs in sorted(by_area.items()):
        lines.append(f"| {a} | {sum(x['passed'] for x in rs)}/{len(rs)} | {sum(x.get('cause_ok', False) for x in rs)}/{len(rs)} |")
    tags = Counter(t for r in rows for t in r.get("tags", []))
    tag_pass = Counter(t for r in rows if r["passed"] for t in r.get("tags", []))
    lines += ["", "## By tag", "", "| tag | passed |", "|---|---|"]
    lines += [f"| {t} | {tag_pass[t]}/{k} |" for t, k in tags.most_common()]
    lines += ["", "## Conversations", "",
              "| id | area (expected → routed) | expected cause | got | q | tone | notes |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        v = r.get("verdict") or {}
        exp_area = next((c["expected_area"] for c in GOLD if c["id"] == r["id"]), "?")
        second = r.get("second") or {}
        got = f"{r.get('got_cause') or '—'}" + (f" + {second.get('got_cause') or '—'}" if second else "")
        lines.append(f"| {'✓' if r['passed'] else '✗'} {r['id']} | {exp_area} → {r.get('routed_area') or '—'} | "
                     f"{r.get('expected_cause', '')} | {got} | {r.get('diagnostic_questions', '')} | "
                     f"{v.get('tone', '')} | {(r.get('error') or v.get('notes') or '').replace('|', '/')} |")
    lines += ["", "## Transcripts of the failed conversations", ""]
    for r in rows:
        if r["passed"]:
            continue
        lines.append(f"<details><summary>✗ {r['id']}: {r['title']}</summary>\n")
        for who, text in r.get("transcript", []):
            lines.append(f"- **{who}**: {text}")
        v = r.get("verdict") or {}
        if v.get("must_not_violations") or v.get("invented_examples"):
            lines.append(f"\n_judge: {v.get('invented_examples', '')} {v.get('must_not_violations', '')}_")
        lines.append("\n</details>\n")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", path)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--worker"]:
        jobs = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        rows = run_convs([j["id"] for j in jobs], passes=[j["pass"] for j in jobs])
        Path(sys.argv[3]).write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        sys.exit(0)
    if sys.argv[1:2] == ["--report"]:
        write_report([json.loads(Path(f).read_text(encoding="utf-8")) for f in sys.argv[2].split(",")])
        sys.exit(0)
    import argparse

    ap = argparse.ArgumentParser(description="Triage gold-conversation eval (parallel worker processes)")
    ap.add_argument("ids", nargs="*", help="conversation id prefixes (default: all 66)")
    ap.add_argument("--smoke", action="store_true", help="only the smoke ids")
    ap.add_argument("--passes", type=int, default=1)
    ap.add_argument("--workers", type=int, default=int(os.getenv("EVAL_WORKERS", "8")))
    ap.add_argument("--out", default=os.getenv("EVAL_OUT"))
    a = ap.parse_args()
    ids = a.ids + (SMOKE if a.smoke else [])
    sys.exit(run_parallel(ids, a.passes, a.workers, a.out))
