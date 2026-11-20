"""'No hot water' diagnosis (KB PR 90): no proactive gas question (gas only if mentioned), centrix
shortcuts, max 3 questions, likeliest first, three outcome paths."""
import asyncio

import pytest
from agent_stubs import oa_call

LUKA, JONAS = "490000000001", "490000000002"
_n = 0


def wa(body, from_=LUKA):
    global _n
    _n += 1
    return {"entry": [{"changes": [{"value": {"messages": [
        {"from": from_, "id": f"wamid.dg.{_n}", "type": "text", "text": {"body": body}}]}}]}]}


def tap(id_, from_=LUKA):
    global _n
    _n += 1
    return {"entry": [{"changes": [{"value": {"messages": [
        {"from": from_, "id": f"wamid.dg.{_n}", "type": "interactive",
         "interactive": {"type": "button_reply", "button_reply": {"id": id_, "title": "t"}}}]}}]}]}


def outbox(client):
    return client.get("/webhooks/whatsapp/_outbox").json()["messages"]


def last_ids(client):
    p = outbox(client)[-1]["payload"]
    if p["type"] != "interactive":
        return []
    return [b["reply"]["id"] for b in p["interactive"]["action"]["buttons"]]


def texts(client, to="+490000000001"):
    out = []
    for m in outbox(client):
        if m["to"] != to:
            continue
        p = m["payload"]
        out.append(p["text"]["body"] if p["type"] == "text" else p["interactive"]["body"]["text"])
    return out


def run_with_truth(client, truth: dict, from_=LUKA, limit=6):
    """Answer whatever diagnosis question comes next from `truth` until the diagnosis concludes."""
    asked = []
    for _ in range(limit):
        diag = [i for i in last_ids(client) if i.startswith("diag:")]
        if not diag:
            return asked
        qid = diag[0].split(":")[1]
        asked.append(qid)
        key = truth.get(qid) or diag[0].split(":")[2]
        client.post("/webhooks/whatsapp", json=tap(f"diag:{qid}:{key}", from_))
    return asked


def start(client, claude, text="My shower is cold"):
    claude([RuntimeError("down")] * 10)  # model down → code policy (next_step) drives the questions
    client.post("/webhooks/whatsapp", json=wa(text))
    assert not any("gas" in t.lower() for t in texts(client))  # never asked proactively
    assert last_ids(client)[0] == "diag:q_scope:only_shower"  # likeliest split first


def test_no_gas_question_first_question_is_scope(client, svc, claude):
    start(client, claude)


def test_gas_mention_is_emergency_any_time(client, svc, claude):
    start(client, claude)
    client.post("/webhooks/whatsapp", json=wa("actually it smells of gas in the kitchen"))
    case = svc.cases["case_0001"]
    assert case["priority"] == "emergency" and case["type"] == "emergency.gas"
    assert any(e[2] == "staff.alert" for e in svc.events)
    assert "leave the apartment" in texts(client)[-1]


def test_gas_mention_without_diagnosis_too(client, svc, claude):
    claude([RuntimeError("down")])
    client.post("/webhooks/whatsapp", json=wa("there's a hissing sound at the boiler and it smells like gas"))
    assert svc.cases["case_0001"]["priority"] == "emergency"


def test_path_used_up_tank_self_help_no_technician(client, svc, claude):
    from app.agent import diagnosis

    start(client, claude)
    asked = run_with_truth(client, {"q_scope": "everywhere", "q_recent_use": "yes", "q_radiators": "no"})
    assert len(asked) <= 3
    assert "reheats" in texts(client)[-1]
    assert not any(c[0] in ("dispatch", "consent") for c in svc.calls)
    assert "c_202" in diagnosis._followups
    diagnosis._followups.pop("c_202").cancel()


def test_follow_up_still_cold_escalates(client, svc, claude):
    from app.agent import diagnosis

    start(client, claude)
    run_with_truth(client, {"q_scope": "everywhere", "q_recent_use": "yes", "q_radiators": "no"})
    diagnosis._followups.pop("c_202").cancel()
    asyncio.run(diagnosis.send_follow_up(svc.contacts["c_202"], "hot_water_used_up"))
    assert last_ids(client) == ["diagfu_yes:hot_water_used_up", "diagfu_no:hot_water_used_up"]
    client.post("/webhooks/whatsapp", json=tap("diagfu_no:hot_water_used_up"))
    assert any(c.get("trade") == "heating" for c in svc.cases.values())
    assert "share your name" in texts(client)[-1]


def test_path_only_shower_plumbing(client, svc, claude):
    start(client, claude)
    asked = run_with_truth(client, {"q_scope": "only_shower", "q_knob": "correct", "q_waited": "yes",
                                    "q_recent_work": "no", "q_handle_feel": "normal", "q_weather_pipe": "no",
                                    "q_other_tap": "no"})
    assert len(asked) <= 3
    case = svc.cases["case_0001"]
    assert case["trade"] == "plumbing" and case["type"] == "repair.plumbing"
    assert case["data"]["diagnosis"]["cause_id"] == "shower_mixer_faulty"
    assert "share your name" in texts(client)[-1]


def test_path_radiators_cold_f28_heating(client, svc, claude):
    start(client, claude, "No hot water and the flat is cold, the boiler display shows F.28")
    asked = run_with_truth(client, {"q_scope": "everywhere", "q_radiators": "yes", "q_recent_use": "no",
                                    "q_waited": "yes", "q_timing": "stays_cold", "q_pressure": "ok",
                                    "q_other_tap": "no", "q_knob": "correct"})
    assert len(asked) <= 3
    case = svc.cases["case_0001"]
    assert case["trade"] == "heating" and case["data"]["diagnosis"]["cause_id"] == "boiler_fault"
    assert case["priority"] == "urgent"
    assert "share your name" in texts(client)[-1]


def test_neighbour_open_case_shortcut(client, svc, claude):
    claude([RuntimeError("down")] * 10)
    client.post("/webhooks/whatsapp", json=wa("My heating is cold"))  # Luka: classic heating flow, case open
    client.post("/webhooks/whatsapp", json=wa("our shower is cold", from_=JONAS))
    assert ("link", "case_0001", "c_203", "affected") in svc.calls  # boiler_fault without asking
    assert "already been reported" in texts(client, "+490000000002")[-1]


def test_max_three_questions_then_likeliest_technician():
    from app.agent import diagnosis, state, tools

    conv = state.Conversation(contact_id="x")
    diagnosis.start(conv, "cold")
    conv.diagnosis["safety_done"] = True
    conv.diagnosis["asked"] = ["q_scope", "q_waited", "q_timing"]
    conv.diagnosis["answers"] = {"q_scope": "everywhere", "q_waited": "yes", "q_timing": "stays_cold"}
    ctx = tools.TurnContext(contact=None, conv=conv)
    with pytest.raises(ValueError, match="conclude_diagnosis"):
        asyncio.run(tools._ask_question(ctx, "q_display", None))
    action, cause, _ = diagnosis.next_step(conv)
    assert action == "conclude" and diagnosis.causes()[cause]["outcome"] == "technician"


def test_model_path_free_text_answers(client, svc, gpt):
    gpt([
        [oa_call("record_answer", question_id="q_scope", answer_key="everywhere"),
         oa_call("ask_question", question_id="q_recent_use", lead_in=None)],
        "",
        [oa_call("record_answer", question_id="q_recent_use", answer_key="yes"),
         oa_call("record_answer", question_id="q_radiators", answer_key="no"),
         oa_call("conclude_diagnosis", cause_id="hot_water_used_up", confidence=0.85,
                 reasoning="Roommate just showered, cold everywhere, radiators fine.")],
        "",
    ])
    client.post("/webhooks/whatsapp", json=wa("no hot water anywhere"))
    assert last_ids(client) == ["diag:q_recent_use:yes", "diag:q_recent_use:no"]
    client.post("/webhooks/whatsapp", json=wa("yes my roommate just showered, radiators are warm"))
    assert "reheats" in texts(client)[-1] and not any(c[0] == "dispatch" for c in svc.calls)
    from app.agent import diagnosis

    t = diagnosis._followups.pop("c_202", None)
    t and t.cancel()


def test_new_backend_api_used_when_present(client, svc, claude):
    from app.agent import diagnosis, state

    calls = []
    svc.set_case_diagnosis = lambda cid, d, trade=None: calls.append(("set_case_diagnosis", cid, d["cause_id"]))
    svc.notify_caretaker = lambda cid, reason: calls.append(("notify_caretaker", cid, reason))
    svc.close_self_help = lambda cid, text: calls.append(("close_self_help", cid, text))
    contact = svc.contacts["c_202"]

    conv = state.conversation("c_202")
    diagnosis.start(conv, "shower cold")
    conv.diagnosis["safety_done"] = True
    asyncio.run(diagnosis.conclude(contact, conv, "low_system_pressure", 0.8, "F.22 and gauge below 1 bar."))
    assert ("notify_caretaker", "case_0001", diagnosis.causes()["low_system_pressure"]["label"]) in calls
    assert not any(e[2] == "diagnosis.concluded" for e in svc.events)
    assert not any(c[0] == "dispatch" for c in svc.calls)

    state.reset_all()
    conv = state.conversation("c_202")
    diagnosis.start(conv, "shower cold")
    conv.diagnosis["safety_done"] = True
    asyncio.run(diagnosis.conclude(contact, conv, "hot_water_used_up", 0.9, "Roommate showered."))
    case_id = conv.case_id
    assert case_id and svc.cases[case_id]["type"] == "repair.hot_water"
    diagnosis._followups.pop("c_202").cancel()
    client.post("/webhooks/whatsapp", json=tap("diagfu_yes:hot_water_used_up"))
    assert any(c[0] == "close_self_help" and c[1] == case_id for c in calls)


def test_natural_when():
    from app.agent.flow import natural_when

    assert natural_when("Tomorrow 8–10") == "tomorrow between 8 and 10"
    assert natural_when("Today 14–16") == "today between 14 and 16"
    assert natural_when("Sat 21 Nov, 8–10") == "on Sat 21 Nov between 8 and 10"
    assert natural_when({"label": "Thu 26 Nov, 8:30–10"}) == "on Thu 26 Nov between 8:30 and 10"


def test_conclude_refuses_contradicting_cause():
    from app.agent import diagnosis, state

    conv = state.Conversation(contact_id="x")
    diagnosis.start(conv, "cold")
    conv.diagnosis["answers"].update({"q_gas_stove": "yes"})
    with pytest.raises(ValueError, match="contradicts"):
        asyncio.run(diagnosis.conclude(None, conv, "gas_supply_interrupted", 0.8, "x"))


def test_heater_type_known_from_centrix_not_asked(client, svc, claude):
    from app.agent import state

    start(client, claude)
    assert state.conversation("c_202").diagnosis["answers"]["q_heater_type"] == "no"
    asked = run_with_truth(client, {"q_scope": "only_shower", "q_knob": "correct", "q_waited": "yes"})
    assert "q_heater_type" not in asked


def test_applies_if_and_likelihood_in_context():
    from app.agent import diagnosis, state

    conv = state.Conversation(contact_id="x")
    diagnosis.start(conv, "cold")
    block = diagnosis.context_block(conv)
    assert "applies_if" in {c["id"]: c for c in block["causes"]}["electric_instant_heater"]
    assert block["likelihood_order"][0] == "hot_water_used_up"


def test_approval_rejected_text(client, svc, claude):
    from app import notify

    claude([RuntimeError("down")])
    client.post("/webhooks/whatsapp", json=wa("My heating is cold"))
    asyncio.run(notify.notify_tenant("case_0001", "approval_rejected",
                                     {"reason": "the landlord's own caretaker will check first"}))
    assert texts(client)[-1] == ("Your property manager has decided not to send a technician for now: the landlord's "
                                 "own caretaker will check first. They'll be in touch.")


def test_no_duplicate_question_via_ask_buttons(client, svc, gpt):
    stub = gpt([
        [oa_call("ask_question", question_id="q_scope", lead_in=None),
         oa_call("ask_buttons", text="Are the radiators cold?", options=[{"id": "yes", "title": "Yes"},
                                                                          {"id": "no", "title": "No"}])],
        "",
    ])
    client.post("/webhooks/whatsapp", json=wa("no hot water in the shower"))
    assert len([m for m in outbox(client) if m["payload"]["type"] == "interactive"]) == 1
    refused = stub.requests[0]["messages"]  # first request; the refusal is in the second
    refused = stub.requests[1]["messages"][-1]
    assert refused["role"] == "tool" and "ask_question" in refused["content"]


def test_tone_no_filler_in_diagnosis_prompt():
    from app.agent.prompts import TENANT_SYSTEM

    assert "No filler empathy" in TENANT_SYSTEM and "Never ask about gas" in TENANT_SYSTEM


def test_no_plain_text_repeat_of_open_question(client, svc, gpt):
    stub = gpt([
        [oa_call("ask_question", question_id="q_scope", lead_in=None)],
        "",
        [oa_call("reply", text="Is it only the shower, or is the hot water cold at the sinks too?")],
        [oa_call("reply", text="Thanks for the photo.")],
        "",
    ])
    client.post("/webhooks/whatsapp", json=wa("no hot water in the shower"))
    client.post("/webhooks/whatsapp", json=wa("here is a photo of it"))
    t = texts(client)
    assert sum("only the shower" in x for x in t) == 1 and t[-1] == "Thanks for the photo."


def test_extraction_merges_only_unanswered(monkeypatch):
    from app.agent import diagnosis, state

    async def fake(text, open_qs):
        return {"q_display": "dark", "q_scope": "only_shower", "q_bogus": "x", "q_power": "maybe"}

    monkeypatch.setattr(diagnosis, "_classify_answers", fake)
    conv = state.Conversation(contact_id="x")
    diagnosis.start(conv, "dark display")
    conv.diagnosis["answers"]["q_scope"] = "everywhere"
    got = asyncio.run(diagnosis.extract_answers(conv, "the boiler display is dark"))
    assert got == {"q_display": "dark"}  # unknown ids/keys dropped, existing answers kept
    assert conv.diagnosis["answers"]["q_scope"] == "everywhere"


def test_ask_refused_when_answers_point_to_a_cause():
    from app.agent import diagnosis, state, tools

    conv = state.Conversation(contact_id="x")
    diagnosis.start(conv, "dark")
    conv.diagnosis["answers"].update({"q_display": "dark", "q_power": "no"})
    ctx = tools.TurnContext(contact=None, conv=conv)
    with pytest.raises(ValueError, match="conclude_diagnosis now"):
        asyncio.run(tools._ask_question(ctx, "q_scope", None))


def test_likelier_equal_cause_preferred_on_conclude():
    from app.agent import diagnosis, state

    conv = state.Conversation(contact_id="x")
    diagnosis.start(conv, "cold")
    conv.diagnosis["answers"].update({"q_waited": "no", "q_radiators": "no", "q_scope": "everywhere"})
    with pytest.raises(ValueError, match="not_run_long_enough|likelier"):
        asyncio.run(diagnosis.conclude(None, conv, "diverter_valve_stuck", 0.8, "x"))
