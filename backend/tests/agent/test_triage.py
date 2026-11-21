"""Triage (agent/triage.py): emergencies from the words, the area of a report, the area question,
a queued second problem, and the routing of every gold first message."""
import asyncio
import json
from pathlib import Path

import pytest
from test_diagnosis import last_ids, outbox, tap, texts, wa

DATA = Path(__file__).resolve().parents[3] / "data" / "diagnosis"


@pytest.fixture(autouse=True)
def _reset_kb_area():
    yield
    from app.agent import diagnosis

    diagnosis._AREA.set(diagnosis.HOT_WATER)  # tests that call diagnosis.start() directly must not leak the area


def _cancel_followups():
    from app.agent import diagnosis

    for t in list(diagnosis._followups.values()):
        t.cancel()
    diagnosis._followups.clear()


# ---------------------------------------------------------------- unit: words → area
@pytest.mark.parametrize("text,area,cause", [
    ("HELP water is spreading all over the kitchen floor, a pipe burst", "water_leak", "major_leak_flooding"),
    ("there's a burning smell from the socket and it sparked", "electrics", "electrical_burning"),
    ("someone broke into my flat, the door was forced", "windows_doors", "break_in"),
    ("my mum is stuck in the lift between floors", "lift", "person_trapped"),
    ("the CO alarm is going off in the kitchen", "other", "co_alarm"),
    ("power is out, the whole building and the stairwell are dark", "electrics", "building_power_outage"),
])
def test_emergencies_from_the_words(text, area, cause):
    from app.agent import triage

    assert triage.emergency_from_text(text)[:2] == (area, cause)


@pytest.mark.parametrize("text", ["the smoke alarm keeps beeping", "water drips from the ceiling when it rains",
                                  "my tap is dripping", "no hot water"])
def test_no_emergency(text):
    from app.agent import triage

    assert triage.emergency_from_text(text) is None


@pytest.mark.parametrize("text,primary,second", [
    ("my kitchen tap is dripping", "water_leak", None),
    ("the radiator is leaking", "water_leak", None),
    ("the radiators are cold", "heating", None),
    ("my shower is cold", "no_hot_water", None),
    ("No hot water, display shows F.28 and my gas stove won't light either", "no_hot_water", None),
    ("The washing machine is leaking at the back", "water_leak", None),
    ("Eine Fliese ist locker", "other", None),  # 'lock' never matches German 'locker'
    ("the kitchen tap drips and also the bedroom window won't close", "water_leak", "windows_doors"),
    ("question about my rent", "management", None),
    ("hi", None, None),
])
def test_keyword_routing(text, primary, second):
    from app.agent import triage

    p, s, _ = triage.classify_keywords(text)
    assert (p, s) == (primary, second)


def _first_message(c):
    t = c["turns"][0]["text"]
    return c["turns"][2]["text"] if t.strip().lower() in ("hi", "hello", "hallo") else t


@pytest.mark.parametrize("gold", ["triage_gold_a.json", "triage_gold_b.json"])
def test_every_gold_first_message_routes(gold):
    from app.agent import triage

    misses = []
    for c in json.loads((DATA / gold).read_text(encoding="utf-8"))["conversations"]:
        t = _first_message(c)
        em = triage.emergency_from_text(t)
        p, s, _ = triage.classify_keywords(t)
        got = em[0] if em else p
        if "vague_area" in c["tags"]:
            ok = got is None and bool(triage.PROBLEM_RE.search(t))
        else:
            ok = got == c["expected_area"] or (got in triage.PASSTHROUGH and s == c["expected_area"])
        if c["expected_cause"] in {e[1] for e in triage.EMERGENCIES} | {"building_power_outage"}:
            ok = ok and bool(em) and em[1] == c["expected_cause"]
        if not ok:
            misses.append((c["id"], c["expected_area"], got, t[:60]))
    assert not misses


# ---------------------------------------------------------------- conversations (model down: code policy)
def test_flooding_gets_safety_steps_and_an_emergency_case(client, svc, claude):
    claude([RuntimeError("down")] * 10)
    client.post("/webhooks/whatsapp", json=wa("HELP water is spreading all over the kitchen floor, a pipe burst"))
    t = texts(client)
    assert len(t) == 1 and "main water valve" in t[0]  # the KB's safety message, no question first
    case = svc.cases["case_0001"]
    assert case["priority"] == "emergency" and case["type"] == "emergency.water_leak" and case["trade"] == "plumbing"
    assert any(e[2] == "staff.alert" for e in svc.events if len(e) > 2)


def test_dripping_tap_asks_the_leak_question_not_hot_water(client, svc, claude):
    claude([RuntimeError("down")] * 10)
    client.post("/webhooks/whatsapp", json=wa("my kitchen tap is dripping"))
    ids = last_ids(client)
    assert ids and all(i.startswith("diag:lk_") for i in ids)
    from app.agent import state

    assert state.conversation("c_202").diagnosis["area"] == "water_leak"


def test_vague_report_gets_the_area_list_then_the_area_question(client, svc, claude):
    claude([RuntimeError("down")] * 10)
    client.post("/webhooks/whatsapp", json=wa("Hi, I have a problem and need help"))
    assert texts(client)[-1] == "Ok. What is it about?"
    ids = last_ids(client)
    assert "triage:no_hot_water" in ids and "triage:blocked_drain" in ids and len(ids) <= 10
    client.post("/webhooks/whatsapp", json=tap("triage:blocked_drain"))
    assert all(i.startswith("diag:dr_") for i in last_ids(client))


def test_area_typed_instead_of_tapped(client, svc, claude):
    claude([RuntimeError("down")] * 10)
    client.post("/webhooks/whatsapp", json=wa("something isn't working, can you help?"))
    client.post("/webhooks/whatsapp", json=wa("the sink won't drain"))
    from app.agent import state

    assert state.conversation("c_202").diagnosis["area"] == "blocked_drain"


def test_leak_case_is_never_the_buildings_heating_case(client, svc, claude):
    claude([RuntimeError("down")] * 10)
    client.post("/webhooks/whatsapp", json=wa("HELP water is spreading all over the bathroom, the pipe burst"))
    assert svc.cases["case_0001"]["asset_id"] is None  # no boiler asset, no link to an open boiler case


def test_second_problem_starts_after_the_first(client, svc, claude):
    claude([RuntimeError("down")] * 10)
    client.post("/webhooks/whatsapp",
                json=wa("the kitchen tap drips and also the bedroom window won't close"))
    from app.agent import diagnosis, state, triage

    conv = state.conversation("c_202")
    assert conv.diagnosis["area"] == "water_leak" and conv.triage["queued"]["area"] == "windows_doors"
    conv.diagnosis["concluded"] = "tap_washer_worn"  # first problem settled (e.g. consent answered)
    asyncio.run(triage.after_conclusion(svc.contacts["c_202"], conv))
    _cancel_followups()
    assert any(t == "Now to the window or door." or t.startswith("Now to ") for t in texts(client))
    conv = state.conversation("c_202")
    assert diagnosis.area_of(conv) == "windows_doors" and conv.case_id is None
    assert all(i.startswith("diag:wd_") for i in last_ids(client))


def test_radiators_cold_keeps_the_heating_flow(client, svc, claude):
    claude([RuntimeError("down")] * 10)
    client.post("/webhooks/whatsapp", json=wa("my radiators are cold"))
    from app.agent import state

    conv = state.conversation("c_202")
    assert not conv.diagnosis and (conv.triage or {}).get("area") == "heating"
    assert not any(m["payload"].get("type") == "interactive" and "triage:" in json.dumps(m["payload"])
                   for m in outbox(client))


# ---------------------------------------------------------------- planner (PLANNER_ENABLED), mocked model
def test_planner_off_by_default_sends_no_holding_message(client, svc, claude):
    claude([RuntimeError("down")] * 10)
    client.post("/webhooks/whatsapp", json=wa("toilet blocked"))
    assert not any(t.startswith("Let me look into it") for t in texts(client))


def test_planner_plan_steers_the_first_question(client, svc, claude, monkeypatch):
    from app.agent import diagnosis, state, triage

    claude([RuntimeError("down")] * 10)
    monkeypatch.setenv("PLANNER_ENABLED", "1")

    async def fake_plan(text, candidates):
        return {"area": "blocked_drain", "likely_causes": ["main_stack_blockage"], "questions": ["dr_backup"],
                "reason": "test"}

    monkeypatch.setattr(triage, "plan", fake_plan)
    client.post("/webhooks/whatsapp", json=wa("toilet blocked"))
    assert texts(client)[0] == triage.HOLDING_EN
    conv = state.conversation("c_202")
    assert conv.diagnosis["area"] == "blocked_drain" and conv.diagnosis["plan"]["questions"] == ["dr_backup"]
    assert diagnosis.context_block(conv)["plan"]["likely_causes"] == ["main_stack_blockage"]


def test_planner_unclear_asks_the_area(client, svc, claude, monkeypatch):
    from app.agent import triage

    claude([RuntimeError("down")] * 10)
    monkeypatch.setenv("PLANNER_ENABLED", "1")

    async def fake_plan(text, candidates):
        return {"area": "unclear", "likely_causes": [], "questions": [], "reason": "test"}

    monkeypatch.setattr(triage, "plan", fake_plan)
    client.post("/webhooks/whatsapp", json=wa("I have a problem, can you help"))
    assert texts(client)[-1] == "Ok. What is it about?"


def test_planner_never_runs_for_hot_water(client, svc, claude, monkeypatch):
    from app.agent import triage

    claude([RuntimeError("down")] * 10)
    monkeypatch.setenv("PLANNER_ENABLED", "1")
    called = []

    async def fake_plan(text, candidates):
        called.append(text)

    monkeypatch.setattr(triage, "plan", fake_plan)
    client.post("/webhooks/whatsapp", json=wa("My shower is cold"))
    assert not called and last_ids(client)[0] == "diag:q_scope:only_shower"


# ---------------------------------------------------------------- extraction guards
def test_no_but_yes_in_one_reply_is_clarified(svc, monkeypatch):
    from app.agent import diagnosis, state

    conv = state.conversation("c_202")
    diagnosis.start(conv, "sink drains slowly", "blocked_drain")
    conv.diagnosis["asked"].append("dr_backup")

    async def fake(text, qs):
        return {"dr_backup": "yes"}

    monkeypatch.setattr(diagnosis, "_classify_answers", fake)
    asyncio.run(diagnosis.extract_answers(conv, "No, only the sink. Although when I flush, dirty water comes up in the shower."))
    d = conv.diagnosis
    assert d["answers"]["dr_backup"] == "no" and d["conflicts"] == {"dr_backup": "yes"}


def test_ask_only_question_is_never_inferred_from_the_first_message(svc, monkeypatch):
    from app.agent import diagnosis, state

    conv = state.conversation("c_202")
    diagnosis.start(conv, "my smoke alarm is going off", "other")
    seen = []

    async def fake(text, qs):
        seen.extend(q["id"] for q in qs)
        return {}

    monkeypatch.setattr(diagnosis, "_classify_answers", fake)
    asyncio.run(diagnosis.extract_answers(conv, "my smoke alarm is going off and won't stop"))
    assert "ot_alarm" not in seen


# ---------------------------------------------------------------- anti-loop (Luka's chat on live)
def test_luka_ceiling_typo_reroutes_instead_of_looping(client, svc, claude):
    claude([RuntimeError("down")] * 20)
    from app.agent import diagnosis, state

    client.post("/webhooks/whatsapp", json=wa("Water is dripping from my ceeling"))
    client.post("/webhooks/whatsapp", json=wa("I said the ceeling"))
    conv = state.conversation("c_202")
    assert diagnosis.area_of(conv) == "roof_ceiling_leak"
    qs = [t for t in texts(client) if "?" in t]
    assert len(qs) == len(set(qs))  # no question twice


def test_every_question_outside_hot_water_has_an_escape(client, svc, claude):
    claude([RuntimeError("down")] * 10)
    client.post("/webhooks/whatsapp", json=wa("my kitchen tap is dripping"))
    assert last_ids(client)[-1].endswith(":_other")


def test_hot_water_questions_have_no_escape(client, svc, claude):
    claude([RuntimeError("down")] * 10)
    client.post("/webhooks/whatsapp", json=wa("My shower is cold"))
    assert not any(i.endswith(":_other") for i in last_ids(client))


# ---------------------------------------------------------------- model_first guards (DIAGNOSIS_MODE default)
def _mf(svc, monkeypatch, area="roof_ceiling_leak", complaint="water dripping from my ceeling"):
    from app.agent import diagnosis, state
    from app.agent.tools import TurnContext

    monkeypatch.setenv("DIAGNOSIS_MODE", "model_first")
    conv = state.conversation("c_202")
    conv.tenant_texts.append(complaint)
    diagnosis.start(conv, complaint, area)
    return conv, TurnContext(contact=svc.contacts["c_202"], conv=conv, effort="low")


def test_model_first_is_the_default_outside_hot_water(monkeypatch):
    from app.agent import diagnosis

    monkeypatch.delenv("DIAGNOSIS_MODE", raising=False)
    assert diagnosis.model_first({"area": "water_leak"}) and not diagnosis.model_first({})  # hot water stays guided


def test_model_first_never_repeats_a_question(client, svc, monkeypatch):
    from app.agent import tools

    conv, ctx = _mf(svc, monkeypatch)
    asyncio.run(tools._ask_free(ctx, "Does it drip when it rains, or also when it's dry outside?", ["Rain", "Dry"]))
    conv.diagnosis["turn"] += 1
    ctx.sent = 0
    with pytest.raises(ValueError, match="already asked"):
        asyncio.run(tools._ask_free(ctx, "Is it mainly when it rains, or does it also drip when it's dry?", []))


def test_model_first_max_three_questions(client, svc, monkeypatch):
    from app.agent import tools

    conv, ctx = _mf(svc, monkeypatch)
    for q in ("Is it only when it rains?", "Are you on the top floor?", "Is there a bathroom above you?"):
        ctx.sent = 0
        asyncio.run(tools._ask_free(ctx, q, []))
        conv.diagnosis["turn"] += 1
    ctx.sent = 0
    with pytest.raises(ValueError, match="3 questions"):
        asyncio.run(tools._ask_free(ctx, "Is the stain growing?", []))


def test_model_first_conclusion_must_quote_the_tenant(client, svc, monkeypatch):
    from app.agent import tools

    conv, ctx = _mf(svc, monkeypatch)
    with pytest.raises(ValueError, match="Quote the resident"):
        asyncio.run(tools._conclude(ctx, "roof_leak", 0.8, "The roof leaks after heavy rain on the top floor."))
    res = asyncio.run(tools._conclude(ctx, "roof_leak", 0.8, 'Tenant: "water dripping from my ceeling".'))
    assert res["outcome"] == "technician"


def test_model_first_has_no_fixed_questions_or_clarify(client, svc, monkeypatch):
    from app.agent import tools

    conv, ctx = _mf(svc, monkeypatch)
    with pytest.raises(ValueError, match="ask_free"):
        asyncio.run(tools._ask_question(ctx, "rf_rain"))
    with pytest.raises(ValueError, match="ask_free"):
        asyncio.run(tools._clarify(ctx, "Do you mean the ceiling?"))
