"""'No hot water' diagnosis: safety first, centrix shortcuts, max 5 questions, three outcome paths."""
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


def run_with_truth(client, truth: dict, from_=LUKA, limit=8):
    """Answer whatever diagnosis question comes next from `truth` until the diagnosis concludes."""
    asked = []
    for _ in range(limit):
        ids = last_ids(client)
        diag = [i for i in ids if i.startswith("diag:")]
        if not diag:
            return asked
        qid = diag[0].split(":")[1]
        asked.append(qid)
        key = truth.get(qid) or diag[0].split(":")[2]  # unknown to the test: first option
        client.post("/webhooks/whatsapp", json=tap(f"diag:{qid}:{key}", from_))
    return asked


def start(client, claude, text="My shower is cold"):
    claude([RuntimeError("down")] * 10)  # model down → code policy (next_step) drives the questions
    client.post("/webhooks/whatsapp", json=wa(text))
    ids = last_ids(client)
    assert ids == ["diag:q_safety:yes", "diag:q_safety:no"], ids  # safety question first, by code
    assert "smell gas" in texts(client)[-1]


def test_gas_smell_is_emergency_and_stops(client, svc, claude):
    start(client, claude)
    client.post("/webhooks/whatsapp", json=tap("diag:q_safety:yes"))
    assert svc.cases["case_0001"]["priority"] == "emergency" and svc.cases["case_0001"]["type"] == "emergency.gas"
    assert any(e[2] == "staff.alert" for e in svc.events)
    assert "leave the apartment" in texts(client)[-1]
    assert last_ids(client) == []  # no further questions


def test_path_used_up_tank_self_help_no_technician(client, svc, claude, monkeypatch):
    from app.agent import diagnosis

    start(client, claude)
    truth = {"q_safety": "no", "q_scope": "everywhere", "q_recent_use": "yes", "q_radiators": "no",
             "q_other_tap": "no", "q_timing": "slow", "q_waited": "yes"}
    asked = run_with_truth(client, truth)
    assert asked[0] == "q_safety" and len(asked) - 1 <= 5
    assert "reheats" in texts(client)[-1]  # the KB tip
    assert not svc.cases  # no case, nobody dispatched
    assert not any(c[0] in ("dispatch", "consent") for c in svc.calls)
    assert "c_202" in diagnosis._followups  # follow-up check scheduled
    diagnosis._followups.pop("c_202").cancel()


def test_follow_up_still_cold_escalates(client, svc, claude):
    import asyncio

    from app.agent import diagnosis

    start(client, claude)
    run_with_truth(client, {"q_safety": "no", "q_scope": "everywhere", "q_recent_use": "yes", "q_radiators": "no",
                            "q_other_tap": "no", "q_timing": "slow", "q_waited": "yes"})
    diagnosis._followups.pop("c_202").cancel()
    contact = svc.contacts["c_202"]
    asyncio.run(diagnosis.send_follow_up(contact, "hot_water_used_up"))
    assert last_ids(client) == ["diagfu_yes:hot_water_used_up", "diagfu_no:hot_water_used_up"]
    client.post("/webhooks/whatsapp", json=tap("diagfu_no:hot_water_used_up"))
    assert svc.cases["case_0001"]["trade"] == "heating"
    assert "share your name" in texts(client)[-1]  # consent → approval → partner by trade


def test_path_only_shower_plumbing(client, svc, claude):
    start(client, claude)
    truth = {"q_safety": "no", "q_scope": "only_shower", "q_knob": "correct", "q_waited": "yes",
             "q_weather_pipe": "no", "q_recent_work": "no", "q_handle_feel": "normal"}
    asked = run_with_truth(client, truth)
    assert len(asked) - 1 <= 5
    case = svc.cases["case_0001"]
    assert case["trade"] == "plumbing" and case["type"] == "repair.plumbing"
    diag = case["data"]["diagnosis"]
    assert diag["cause_id"] == "shower_mixer_faulty" and diag["questions_asked"]
    assert any(e[2] == "diagnosis.concluded" for e in svc.events)
    assert "share your name" in texts(client)[-1]


def test_path_radiators_cold_f28_heating(client, svc, claude):
    start(client, claude)
    truth = {"q_safety": "no", "q_scope": "everywhere", "q_radiators": "yes", "q_recent_use": "no",
             "q_display": "code", "q_waited": "yes", "q_timing": "stays_cold", "q_power": "yes", "q_gas_stove": "yes",
             "q_pressure": "ok", "q_other_tap": "no", "q_heater_type": "no"}
    run_with_truth(client, truth)
    case = svc.cases["case_0001"]
    assert case["trade"] == "heating" and case["data"]["diagnosis"]["cause_id"] == "boiler_fault"
    assert case["priority"] == "urgent"
    assert "share your name" in texts(client)[-1]


def test_neighbour_open_case_shortcut(client, svc, claude):
    claude([RuntimeError("down")] * 10)
    client.post("/webhooks/whatsapp", json=wa("My heating is cold"))  # Luka: classic heating flow, case open
    client.post("/webhooks/whatsapp", json=wa("our shower is cold", from_=JONAS))
    client.post("/webhooks/whatsapp", json=tap("diag:q_safety:no", from_=JONAS))
    assert ("link", "case_0001", "c_203", "affected") in svc.calls  # boiler_fault without asking
    assert "already been reported" in texts(client, "+490000000002")[-1]


def test_max_five_questions():
    import asyncio

    from app.agent import diagnosis, state, tools

    conv = state.Conversation(contact_id="x")
    diagnosis.start(conv, "cold")
    conv.diagnosis["safety_done"] = True
    conv.diagnosis["asked"] = ["q_scope", "q_radiators", "q_recent_use", "q_waited", "q_timing"]
    ctx = tools.TurnContext(contact=None, conv=conv)
    try:
        asyncio.run(tools._ask_question(ctx, "q_display", None))
        raise AssertionError("expected refusal")
    except ValueError as e:
        assert "conclude_diagnosis" in str(e)
    assert diagnosis.next_step(conv)[0] == "conclude"


def test_model_path_free_text_answers(client, svc, gpt):
    """The model records free-text answers ('my roommate just showered') and concludes."""
    gpt([
        [oa_call("ask_question", question_id="q_scope", lead_in=None)],  # after the safety answer
        "",
        [oa_call("record_answer", question_id="q_scope", answer_key="everywhere"),
         oa_call("record_answer", question_id="q_recent_use", answer_key="yes")],
        [oa_call("conclude_diagnosis", cause_id="hot_water_used_up", confidence=0.85,
                 reasoning="Roommate just showered, cold everywhere, radiators fine.")],
        "",
    ])
    client.post("/webhooks/whatsapp", json=wa("no hot water in the shower"))
    client.post("/webhooks/whatsapp", json=tap("diag:q_safety:no"))
    assert last_ids(client) == ["diag:q_scope:only_shower", "diag:q_scope:everywhere"]
    client.post("/webhooks/whatsapp", json=wa("everywhere, my roommate just showered"))
    assert "reheats" in texts(client)[-1] and not svc.cases
    from app.agent import diagnosis

    t = diagnosis._followups.pop("c_202", None)
    t and t.cancel()


def test_free_text_safety_answer(client, svc, claude):
    start(client, claude)
    client.post("/webhooks/whatsapp", json=wa("no, no gas smell"))
    assert last_ids(client)[0].startswith("diag:q_scope:")  # moved on to the first real question
    assert not svc.cases


def test_new_backend_api_used_when_present(client, svc, claude, monkeypatch):
    """open_case(diagnosis=…) records the event itself; caretaker via notify_caretaker; self-help closed
    with close_self_help once the tenant confirms. No duplicate diagnosis events from the agent."""
    import asyncio

    from app.agent import diagnosis, state

    calls = []
    svc.set_case_diagnosis = lambda cid, d, trade=None: calls.append(("set_case_diagnosis", cid, d["cause_id"]))
    svc.notify_caretaker = lambda cid, reason: calls.append(("notify_caretaker", cid, reason))
    svc.close_self_help = lambda cid, text: calls.append(("close_self_help", cid, text))
    contact = svc.contacts["c_202"]

    # caretaker: low pressure
    conv = state.conversation("c_202")
    diagnosis.start(conv, "shower cold")
    conv.diagnosis["safety_done"] = True
    asyncio.run(diagnosis.conclude(contact, conv, "low_system_pressure", 0.8, "F.22 and gauge below 1 bar."))
    assert ("notify_caretaker", "case_0001", diagnosis.causes()["low_system_pressure"]["label"]) in calls
    assert not any(e[2] == "diagnosis.concluded" for e in svc.events)  # services record it (open_case diagnosis)
    assert not any(c[0] == "dispatch" for c in svc.calls)

    # self-help: case with diagnosis, closed when it worked
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
    assert not any(c[0] == "dispatch" for c in svc.calls)
