"""Caller context up front (no tool call at the start) and the hot-water diagnosis on the phone."""
import json
import time

H = {"X-Debye-Voice-Secret": "test-secret"}


def outbox_texts(c):
    return [json.dumps(m, ensure_ascii=False) for m in c.get("/webhooks/whatsapp/_outbox").json()["messages"]]


def ended(conv_id, secs=65):
    return {"type": "post_call_transcription", "event_timestamp": int(time.time()), "data": {
        "conversation_id": conv_id, "status": "done", "transcript": [],
        "metadata": {"call_duration_secs": secs}, "analysis": {"transcript_summary": "Hot water problem."},
        "conversation_initiation_client_data": {"dynamic_variables": {"contact_id": "c_202"}}}}


def tool(c, name, **body):
    r = c.post(f"/api/voice/tools/{name}", headers=H, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_signed_url_carries_caller_variables(app_client, monkeypatch):
    from app.voice import calls

    async def fake(agent_id):
        return "wss://example/x"

    monkeypatch.setenv("ELEVENLABS_AGENT_ID", "agent_test")
    monkeypatch.setattr(calls, "signed_url", fake)
    d = app_client.get("/api/voice/signed_url?contact=c_202").json()
    dyn = d["dynamic_variables"]
    assert dyn["contact_id"] == "c_202"
    assert dyn["tenant_name"] and dyn["tenant_name"] != "there"
    assert dyn["address"] != "unknown" and dyn["boiler"] != "unknown"
    assert dyn["open_case_summary"] == "none"
    assert set(dyn) == set(calls.UNKNOWN_CALLER_VARIABLES)


def test_init_webhook_for_phone_calls(app_client):
    c = app_client
    from app.agent import _backend as be

    phone = be.attr(be.get_contact("c_202"), "phone_e164")
    r = c.post("/api/voice/init", headers=H, json={"caller_id": phone, "agent_id": "a", "called_number": "+1"})
    d = r.json()
    assert d["type"] == "conversation_initiation_client_data"
    assert d["dynamic_variables"]["contact_id"] == "c_202"
    unknown = c.post("/api/voice/init", headers=H, json={"caller_id": "+4915199999999"}).json()
    assert unknown["dynamic_variables"]["address"] == "unknown"
    assert c.post("/api/voice/init", json={"caller_id": phone}).status_code == 401


def test_open_heating_case_shows_up_in_variables(app_client):
    c = app_client
    from app.agent import _backend as be
    from app.voice import calls

    tool(c, "report_issue", conversation_id="h1", contact_id="c_202", issue_type="heating",
         summary="Heating cold", all_radiators_cold="yes")
    dyn = calls.caller_variables(be.get_contact("c_203"))
    assert "already open" in dyn["open_case_summary"]


def test_heating_with_boiler_words_is_not_a_hot_water_diagnosis(app_client):
    r = tool(app_client, "report_issue", conversation_id="h2", contact_id="c_202",
             summary="Heating cold, boiler display shows F 28", error_code="F28")
    assert r.get("case_id") and not r.get("diagnosis")


def test_hot_water_diagnosis_on_the_phone_continues_on_whatsapp(app_client):
    c = app_client
    r = tool(c, "report_issue", conversation_id="w1", contact_id="c_202", issue_type="hot_water",
             summary="No hot water in the shower", symptoms="My shower is cold since this morning")
    assert r["diagnosis"] and r["ask"]["question_id"] == "q_safety"
    asked = []
    r = tool(c, "answer_question", conversation_id="w1", contact_id="c_202", question_id="q_safety", answer="no")
    for _ in range(6):
        if "ask" not in r:
            break
        q = r["ask"]
        asked.append(q["question_id"])
        r = tool(c, "answer_question", conversation_id="w1", contact_id="c_202",
                 question_id=q["question_id"], answer=list(q["answers"])[0])
    assert 1 <= len(asked) <= 3 and "q_safety" not in asked and "q_display" not in asked
    assert asked[0] == "q_scope"
    assert r.get("done_on_phone") and "WhatsApp" in r["say"]
    assert outbox_texts(c) == []  # nothing on WhatsApp during the call

    bad = tool(c, "answer_question", conversation_id="w1", contact_id="c_202", question_id="q_scope", answer="banana")
    assert bad["ok"] is False and "only_shower" in bad["message"]

    done = c.post("/api/voice/post_call", headers=H, json=ended("w1")).json()
    assert "no hot water" in done["line"] and "continues on WhatsApp" in done["line"]
    texts = outbox_texts(c)
    assert "Thanks for your call" in texts[0] and "Quick recap: no hot water" in texts[0]
    assert len(texts) >= 2  # then the next diagnosis question or the conclusion (tip / consent)
    joined = " ".join(texts)
    assert "Before anything else: do you smell gas" not in joined  # safety not asked twice
    for qid in asked:  # nothing asked twice
        assert f"diag:{qid}:" not in joined


def test_gas_smell_on_the_phone_is_an_emergency(app_client):
    c = app_client
    tool(c, "report_issue", conversation_id="g1", contact_id="c_202", issue_type="hot_water", summary="Shower cold")
    r = tool(c, "answer_question", conversation_id="g1", contact_id="c_202", question_id="q_safety", answer="yes")
    assert r["emergency"] and "leave the apartment" in r["say"]
    case = c.get("/api/staff/cases").json()[0]
    assert case["priority"] == "emergency"
    done = c.post("/api/voice/post_call", headers=H, json=ended("g1", 30)).json()
    assert done["line"].startswith("Call with") and "GAS SMELL" in done["line"]
    detail = c.get(f"/api/staff/cases/{case['case_id']}").json()
    assert any(e["kind"] == "call.completed" for e in detail["events"])


def test_hot_water_answers_in_one_tool_call(app_client):
    c = app_client
    r = tool(c, "report_issue", conversation_id="w2", contact_id="c_202", issue_type="hot_water",
             summary="Shower cold", symptoms="No hot water in the shower",
             answers="q_safety=no; q_scope=only_shower; q_hot_water_use=no; q_wait_result=stays_cold; q_bogus=x")
    assert r["done_on_phone"] and "WhatsApp" in r["say"]
    assert outbox_texts(c) == []
    from app.agent import state as st

    d = st.conversation("c_202").diagnosis
    assert d["safety_done"] and d["answers"]["q_scope"] == "only_shower" and d["answers"]["q_wait_result"] == "stays_cold"
    assert set(d["asked"]) == {"q_scope", "q_hot_water_use", "q_wait_result"}  # only what was really asked
    done = c.post("/api/voice/post_call", headers=H, json=ended("w2")).json()
    assert "3 diagnosis questions" in done["line"]
    texts = outbox_texts(c)
    joined = " ".join(texts)
    assert "only the shower is cold" in texts[0]
    assert "do you smell gas" not in joined
    for qid in ("q_scope", "q_hot_water_use", "q_wait_result"):
        assert f"diag:{qid}:" not in joined
    assert len(texts) >= 2


def test_hot_water_emergency_priority_means_gas(app_client):
    r = tool(app_client, "report_issue", conversation_id="g2", contact_id="c_202", issue_type="hot_water",
             summary="Smells like gas", priority="emergency")
    assert r["emergency"]
    assert app_client.get("/api/staff/cases").json()[0]["priority"] == "emergency"
