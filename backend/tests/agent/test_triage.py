"""Triage (agent/triage.py): emergencies from the words, the area of a report, the area question,
a queued second problem, and the routing of every gold first message."""
import asyncio
import json
from pathlib import Path

import pytest
from test_diagnosis import last_ids, outbox, tap, texts, wa

DATA = Path(__file__).resolve().parents[3] / "data" / "diagnosis"


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
