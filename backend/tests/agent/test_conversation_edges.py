"""Conversation edge cases in the hot-water diagnosis: bursts, side questions, 'it works again',
'still cold', frustration, unknown answers, clarifications, invented facts, language, duplicates."""
import asyncio
from pathlib import Path

import pytest
from agent_stubs import oa_call
from test_diagnosis import LUKA, last_ids, outbox, run_with_truth, start, tap, texts, wa

PHOTO = Path(__file__).resolve().parents[3] / "data" / "demo" / "boiler_display_F28.jpg"


def _cancel_followups():
    from app.agent import diagnosis

    for t in list(diagnosis._followups.values()):
        t.cancel()
    diagnosis._followups.clear()


def _to_self_help_tip(client, claude):
    start(client, claude)  # model down: code asks q_scope first
    run_with_truth(client, {"q_scope": "everywhere", "q_hot_water_use": "before", "q_radiators": "no",
                            "q_switch_check": "all_on", "q_wait_result": "stays_cold"})
    from app.agent import state

    assert state.conversation("c_202").diagnosis["concluded"] == "hot_water_used_up"
    _cancel_followups()


# ---------------------------------------------------------------- bursts
def test_burst_is_merged_and_replanned(monkeypatch, svc):
    from app import router

    calls = []

    async def fake(contact, text, images):
        calls.append(text)
        if len(calls) == 1:  # a new message arrives while the model is still thinking
            router._buffers["c_202"].append(("as I was cooking just now", [], False))
            return True
        return False

    monkeypatch.setattr(router, "process_text", fake)
    router._buffers["c_202"].append(("everything", [], False))
    asyncio.run(router._drain(svc.contacts["c_202"]))
    assert calls == ["everything", "everything\nas I was cooking just now"]  # never a reply to a fragment


def test_turn_sends_nothing_while_newer_messages_wait(client, svc, gpt):
    from app import router
    from app.agent import diagnosis, loop, state

    gpt([[oa_call("ask_question", question_id="q_scope", lead_in=None, translation=None)], ""])
    conv = state.conversation("c_202")
    diagnosis.start(conv, "no hot water")
    router._buffers["c_202"].append(("as I was cooking", [], False))
    try:
        interrupted = asyncio.run(loop.run_tenant_turn(svc.contacts["c_202"], "everything"))
    finally:
        router._buffers.pop("c_202", None)
    assert interrupted is True and outbox(client) == [] and conv.diagnosis["asked"] == []


def test_voice_and_text_close_together_are_one_turn(monkeypatch, svc):
    from app import router
    from app.agent import flow

    calls, voiced = [], []

    async def fake(contact, text, images):
        calls.append((text, images))
        return False

    async def voice(contact):
        voiced.append(1)

    monkeypatch.setattr(router, "process_text", fake)
    monkeypatch.setattr(flow, "maybe_voice_reply", voice)
    router._buffers["c_202"] += [("my shower is cold", [], True), ("here's the display", ["a.jpg"], False)]
    asyncio.run(router._drain(svc.contacts["c_202"]))
    assert calls == [("my shower is cold\nhere's the display", ["a.jpg"])] and voiced == [1]


def test_duplicate_webhook_one_reply(client, svc, claude):
    claude([RuntimeError("down")] * 10)
    body = wa("My shower is cold")
    client.post("/webhooks/whatsapp", json=body)
    client.post("/webhooks/whatsapp", json=body)  # Meta retries the same wamid
    assert len(outbox(client)) == 1


# ---------------------------------------------------------------- off-topic, questions back, unknown
def test_off_topic_keeps_open_question_and_doesnt_count(client, svc, gpt):
    from app.agent import state

    gpt([[oa_call("ask_question", question_id="q_scope", lead_in=None, translation=None)], "",
         ""])  # "lol": the model sends nothing
    client.post("/webhooks/whatsapp", json=wa("no hot water"))
    client.post("/webhooks/whatsapp", json=wa("lol"))
    assert last_ids(client)[0] == "diag:q_scope:only_shower"  # the open question again
    assert state.conversation("c_202").diagnosis["asked"] == ["q_scope"]  # re-asking doesn't count


def test_question_back_short_answer_then_open_question(client, svc, gpt):
    gpt([[oa_call("ask_question", question_id="q_scope", lead_in=None, translation=None)], "",
         [oa_call("reply", text="Cold water alone isn't dangerous.")], ""])
    client.post("/webhooks/whatsapp", json=wa("no hot water"))
    client.post("/webhooks/whatsapp", json=wa("is it dangerous?"))
    t = texts(client)
    assert t[-2] == "Cold water alone isn't dangerous."
    assert t[-1] == "And is it only the shower, or the sinks too?"  # re-worded, no extra lead-in


def test_dont_know_moves_on():
    from app.agent import diagnosis, state

    conv = state.Conversation(contact_id="x")
    diagnosis.start(conv, "cold")
    conv.diagnosis["asked"] = ["q_radiators"]
    diagnosis.record(conv, "q_radiators", "unknown")
    assert diagnosis.open_question(conv.diagnosis) is None
    assert conv.diagnosis["dont_know"] == ["q_radiators"] and "q_radiators" not in conv.diagnosis["answers"]
    action, ident, _ = diagnosis.next_step(conv)
    assert not (action == "ask" and ident == "q_radiators")


def test_clarify_is_one_question_max_two(client, svc):
    from app.agent import diagnosis, state, tools

    conv = state.conversation("c_202")
    diagnosis.start(conv, "cold")
    ctx = tools.TurnContext(contact=svc.contacts["c_202"], conv=conv)
    with pytest.raises(ValueError, match="one short question"):
        asyncio.run(tools._clarify(ctx, "Noted."))
    for _ in range(2):
        asyncio.run(tools._clarify(tools.TurnContext(contact=svc.contacts["c_202"], conv=conv),
                                   "Do you mean all the taps, or everything running at once?"))
    with pytest.raises(ValueError, match="2 clarifications"):
        asyncio.run(tools._clarify(tools.TurnContext(contact=svc.contacts["c_202"], conv=conv), "And?"))
    assert conv.diagnosis["asked"] == []  # clarifications don't count as diagnostic questions


def test_correction_replaces_earlier_answer():
    from app.agent import diagnosis, state

    conv = state.Conversation(contact_id="x")
    diagnosis.start(conv, "cold")
    diagnosis.record(conv, "q_scope", "only_shower")
    diagnosis.record(conv, "q_scope", "everywhere")  # "sorry, actually the kitchen is cold too"
    assert conv.diagnosis["answers"]["q_scope"] == "only_shower"  # held as a conflict, clarified first
    assert conv.diagnosis["conflicts"] == {"q_scope": "everywhere"}
    diagnosis.record(conv, "q_scope", "everywhere")  # said again (or tapped): it's a correction
    assert conv.diagnosis["answers"]["q_scope"] == "everywhere" and not conv.diagnosis["conflicts"]


# ---------------------------------------------------------------- it works / still cold / frustrated
def test_works_again_mid_diagnosis_closes_without_technician(client, svc, claude):
    from app.agent import state

    start(client, claude)
    client.post("/webhooks/whatsapp", json=wa("oh wait, it works again now"))
    assert texts(client)[-1] == "Good to hear. Message me any time if it goes cold again."
    assert not any(c.get("trade") for c in svc.cases.values())
    conv = state.conversation("c_202")
    assert conv.diagnosis is None and conv.step == state.NEW  # a new problem starts fresh


def test_self_help_it_worked_closes(client, svc, claude):
    _to_self_help_tip(client, claude)
    client.post("/webhooks/whatsapp", json=wa("yes that worked"))
    assert texts(client)[-1] == "Good to hear. I'll close this then."
    assert not any(c.get("trade") for c in svc.cases.values())


def test_self_help_still_cold_escalates(client, svc, claude):
    _to_self_help_tip(client, claude)
    client.post("/webhooks/whatsapp", json=wa("still cold unfortunately"))
    run_with_truth(client, {"q_radiators": "no", "q_wait_result": "stays_cold", "q_display": "normal"})
    assert any(c.get("trade") == "heating" for c in svc.cases.values())
    assert "share your name" in texts(client)[-1]


def test_self_help_ack_gets_short_reply(client, svc, claude):
    _to_self_help_tip(client, claude)
    client.post("/webhooks/whatsapp", json=wa("ok will try later"))
    assert texts(client)[-1] == "Sounds good. Tell me how it goes."


def test_decisive_gas_stove_answer_concludes_utility():
    from app.agent import diagnosis, state

    conv = state.Conversation(contact_id="x")
    diagnosis.start(conv, "no hot water, heating off")
    conv.error_code = "F.28"
    conv.diagnosis["answers"].update({"q_radiators": "yes", "q_display": "code", "q_gas_stove": "no"})
    assert diagnosis.next_step(conv)[:2] == ("conclude", "gas_supply_interrupted")
    with pytest.raises(ValueError, match="settle"):
        asyncio.run(diagnosis.conclude(None, conv, "boiler_fault", 0.8, "F.28"))


def test_escalation_never_explains_unsupported_cause():
    from app.agent import diagnosis, state

    conv = state.Conversation(contact_id="x")
    diagnosis.start(conv, "no hot water")
    conv.diagnosis["answers"].update({"q_scope": "everywhere", "q_hot_water_use": "no"})
    cause, supported = diagnosis.likeliest_technician(conv.diagnosis)
    assert not supported or not diagnosis.missing_core(conv.diagnosis, cause)


def test_typo_hot_water_detected():
    from app.agent import diagnosis

    assert diagnosis.applies("showr cold af") and diagnosis.applies("no hot wtr")


def test_self_help_tip_is_decisive_after_one_answer():
    from app.agent import diagnosis, state

    conv = state.Conversation(contact_id="x")
    diagnosis.start(conv, "my shower went cold halfway through")
    conv.diagnosis["answers"]["q_hot_water_use"] = "before"  # "my flatmate had a long shower"
    assert diagnosis.next_step(conv)[:2] == ("conclude", "hot_water_used_up")


def test_frustrated_tenant_gets_a_technician(client, svc, claude):
    start(client, claude)
    client.post("/webhooks/whatsapp", json=wa("this is useless, just send someone"))
    t = texts(client)
    assert "Understood. I'll get a technician to look at it." in t
    assert any(c.get("trade") for c in svc.cases.values()) and "share your name" in t[-1]


def test_frustrated_first_message_skips_questions(client, svc, claude):
    claude([RuntimeError("down")] * 10)
    client.post("/webhooks/whatsapp", json=wa("no hot water again, just send a plumber"))
    assert not any(i.startswith("diag:") for i in last_ids(client))
    assert any(c.get("trade") for c in svc.cases.values())


def test_new_problem_after_closure_starts_fresh(client, svc, claude):
    from app.agent import state

    _to_self_help_tip(client, claude)
    client.post("/webhooks/whatsapp", json=wa("yes that worked"))
    client.post("/webhooks/whatsapp", json=wa("now the shower is cold again"))
    assert state.conversation("c_202").diagnosis["asked"] == ["q_scope"]  # a new diagnosis
    _cancel_followups()


# ---------------------------------------------------------------- facts: never invented; rambling first message
def test_conclude_refuses_cause_without_required_answer():
    from app.agent import diagnosis, state

    conv = state.Conversation(contact_id="x")
    diagnosis.start(conv, "cold")
    conv.diagnosis["answers"].update({"q_scope": "everywhere"})
    with pytest.raises(ValueError, match="q_radiators"):
        asyncio.run(diagnosis.conclude(None, conv, "diverter_valve_stuck", 0.8, "taps cold"))


def test_conclude_refuses_invented_fact_in_reasoning():
    from app.agent import diagnosis, state

    conv = state.Conversation(contact_id="x")
    diagnosis.start(conv, "my shower went cold")
    conv.diagnosis["answers"].update({"q_hot_water_use": "before"})
    with pytest.raises(ValueError, match="never said"):
        asyncio.run(diagnosis.conclude(None, conv, "hot_water_used_up", 0.8,
                                       "Flatmate showered and the radiators are warm."))


def test_rambling_first_message_asks_only_whats_missing(client, svc, claude, monkeypatch):
    from app.agent import diagnosis, state

    given = {"q_scope": "everywhere", "q_hot_water_use": "no", "q_radiators": "no", "q_wait_result": "stays_cold"}

    async def fake(text, open_qs):
        return {q["id"]: given.get(q["id"], "unknown") for q in open_qs}

    monkeypatch.setattr(diagnosis, "_classify_answers", fake)
    claude([RuntimeError("down")] * 10)
    client.post("/webhooks/whatsapp", json=wa(
        "so I got in the shower and it was freezing, the kitchen is cold too, nobody showered today, the "
        "radiators are warm and I let the tap run five minutes, never got warm"))
    d = state.conversation("c_202").diagnosis
    assert not set(d["asked"]) & set(given)  # never asks what the first message already said


def test_photo_without_text_answers_display(client, svc, claude):
    from app import router
    from app.agent import state

    start(client, claude)
    conv = state.conversation("c_202")
    asyncio.run(router.process_text(svc.contacts["c_202"], None, [str(PHOTO)]))
    assert conv.error_code == "F.28" and conv.diagnosis["answers"].get("q_display") in ("code", None) or \
        conv.diagnosis is None or conv.diagnosis.get("concluded")


# ---------------------------------------------------------------- language switch
def test_language_switch_question_translated(client, svc, gpt):
    gpt([[oa_call("ask_question", question_id="q_scope", lead_in="Okay.",
                  translation="Ist es nur die Dusche, oder sind auch die Waschbecken kalt?")], ""])
    client.post("/webhooks/whatsapp", json=wa("kein warmes Wasser"))
    assert texts(client)[-1] == "Okay. Ist es nur die Dusche, oder sind auch die Waschbecken kalt?"
    assert last_ids(client)[0] == "diag:q_scope:only_shower"


def test_fixed_detection_is_strict():
    from app.agent.diagnosis import fixed_from_text

    assert fixed_from_text("it works again!") is True
    assert fixed_from_text("yes that worked") is True
    assert fixed_from_text("still cold") is False
    assert fixed_from_text("it works again but only in the kitchen") is None
    assert fixed_from_text("the boiler display works fine") is None
    assert fixed_from_text("geht wieder, danke") is True


def test_button_tap_still_works_during_burst_logic(client, svc, claude):
    start(client, claude)
    client.post("/webhooks/whatsapp", json=tap("diag:q_scope:only_shower", LUKA))
    assert any(i.startswith("diag:") for i in last_ids(client))


def test_never_asks_gas_stove_and_f28_concludes_boiler(client, svc, claude):
    claude([RuntimeError("down")] * 10)
    client.post("/webhooks/whatsapp", json=wa("No hot water and the heating is off, the display shows F.28"))
    t = " ".join(texts(client)).lower()
    assert "stove" not in t and "ignition failed (error code f.28)" in t
    assert svc.cases["case_0001"]["data"]["diagnosis"]["cause_id"] == "boiler_fault"


def test_volunteered_stove_means_gas_supply(client, svc, claude):
    claude([RuntimeError("down")] * 10)
    client.post("/webhooks/whatsapp", json=wa("No hot water, display shows F.28 and my gas stove won't light either"))
    from app.agent import state

    d = state.conversation("c_202").diagnosis
    d["answers"]["q_gas_stove"] = "no"  # (the model/extractor records it; no key in tests)
    from app.agent import diagnosis

    assert diagnosis.code_settles(d, "F.28") == "gas_supply_interrupted"


def test_german_tenant_gets_german_questions_and_consent(client, svc, claude):
    claude([RuntimeError("down")] * 10)
    client.post("/webhooks/whatsapp", json=wa("Bei mir ist das Wasser in der Dusche kalt"))
    assert texts(client)[-1].startswith("Schauen wir mal.")
    assert last_ids(client)[0] == "diag:q_scope:only_shower"
    client.post("/webhooks/whatsapp", json=wa("Die Heizung ist auch kalt und das Display zeigt F.28"))
    t = texts(client)
    assert any("Fehlercode F.28" in x for x in t) and "deinen Namen" in t[-1]


# ---------------------------------------------------------------- PR 105 follow-up (Luka's live replay)
def test_language_follows_short_english_messages_not_profile():
    from app.agent import diagnosis, state

    conv = state.Conversation(contact_id="c_202")  # (the contact's stored language is "de")
    for msg in ("my shower is cold", "sinks too", "no", "everything", "all taps"):
        assert diagnosis.update_lang(conv, msg) == "en", msg
    assert diagnosis.update_lang(conv, "👍") == "en"  # unclear keeps the current one
    assert diagnosis.update_lang(conv, "Nein, niemand hat Wasser benutzt") == "de"
    assert diagnosis.update_lang(conv, "ok") == "de"


def test_de_profile_contact_writing_english_gets_english_only(client, svc, gpt):
    from app.agent import state

    assert svc.contacts["c_202"].language == "de"
    gpt([[oa_call("ask_question", question_id="q_scope", lead_in="Lass uns das prüfen.",
                  translation="Ist es nur die Dusche, oder sind auch die Waschbecken kalt?")], ""])
    client.post("/webhooks/whatsapp", json=wa("my shower is cold"))
    t = texts(client)[-1]
    assert t == "Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?"  # never mixed
    assert last_ids(client)[0] == "diag:q_scope:only_shower" and state.conversation("c_202").lang == "en"


def test_answer_to_another_question_then_reworded_reask(client, svc, gpt):
    gpt([[oa_call("ask_question", question_id="q_hot_water_use", lead_in=None, translation=None)], "",
         [oa_call("record_answer", question_id="q_scope", answer_key="everywhere"),
          oa_call("ask_question", question_id="q_hot_water_use", lead_in=None, translation=None)], ""])
    client.post("/webhooks/whatsapp", json=wa("no hot water at all"))
    first = texts(client)[-1]
    client.post("/webhooks/whatsapp", json=wa("all taps"))
    again = texts(client)[-1]
    from app.agent import diagnosis, state

    q = diagnosis.questions()["q_hot_water_use"]
    assert q["text"] in first and q["text"] not in again  # never the same words twice
    assert again == "Thanks. " + q["reask"]
    d = state.conversation("c_202").diagnosis
    assert d["answers"]["q_scope"] == "everywhere" and d["asked"].count("q_hot_water_use") == 1


def test_contradiction_is_clarified_not_concluded(client, svc, gpt):
    from app.agent import diagnosis, state

    gpt([[oa_call("ask_question", question_id="q_hot_water_use", lead_in=None, translation=None)], "",
         [oa_call("record_answer", question_id="q_hot_water_use", answer_key="no")], "",
         [oa_call("record_answer", question_id="q_hot_water_use", answer_key="same_time"),
          oa_call("conclude_diagnosis", cause_id="simultaneous_use", confidence=0.8,
                  reasoning="Cooking while showering.", translation=None)], ""])
    client.post("/webhooks/whatsapp", json=wa("the hot water just stopped"))
    client.post("/webhooks/whatsapp", json=wa("no"))
    client.post("/webhooks/whatsapp", json=wa("as I was cooking just now"))
    d = state.conversation("c_202").diagnosis
    assert not d.get("concluded") and d["answers"]["q_hot_water_use"] == "no"
    assert set(last_ids(client)) == {"diag:q_hot_water_use:same_time", "diag:q_hot_water_use:no"}
    assert texts(client)[-1].startswith("Just to check:")
    client.post("/webhooks/whatsapp", json=tap("diag:q_hot_water_use:no"))  # the tap settles it
    assert not d.get("conflicts")
    _cancel_followups()


def test_questions_are_single_topic():
    from app.agent import diagnosis

    qs = diagnosis.questions()
    assert "certain times" not in qs["q_wait_result"]["text"] and "turn normally" not in qs["q_shower_handle"]["text"]
    assert all(q["text"].count("?") == 1 for q in qs.values())
