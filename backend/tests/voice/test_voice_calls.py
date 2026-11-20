"""Server tools + end of call: the call lands in the same case and continues on WhatsApp."""
import asyncio
import hashlib
import hmac
import json
import time

H = {"X-Debye-Voice-Secret": "test-secret"}
LUKA_PHONE = "+490000000001"


def outbox(c):
    return c.get("/webhooks/whatsapp/_outbox").json()["messages"]


def outbox_texts(c):
    return [json.dumps(m, ensure_ascii=False) for m in outbox(c)]


def post_call_payload(conv_id, secs=72, summary="Luka reported the heating is cold; boiler shows F.28."):
    return {"type": "post_call_transcription", "event_timestamp": int(time.time()), "data": {
        "agent_id": "agent_x", "conversation_id": conv_id, "status": "done",
        "transcript": [{"role": "agent", "message": "Hallo, hier ist Debye.", "time_in_call_secs": 0},
                       {"role": "user", "message": "Meine Heizung ist kalt, F 28.", "time_in_call_secs": 4}],
        "metadata": {"call_duration_secs": secs},
        "analysis": {"transcript_summary": summary},
        "conversation_initiation_client_data": {"dynamic_variables": {"contact_id": "c_202"}}}}


def case_detail(c, case_id):
    return c.get(f"/api/staff/cases/{case_id}").json()


def report(c, conv_id, **kw):
    body = {"conversation_id": conv_id, "summary": "Heizung kalt", **kw}
    return c.post("/api/voice/tools/report_issue", headers=H, json=body).json()


def test_tools_need_the_secret(app_client):
    r = app_client.post("/api/voice/tools/identify_caller", json={"caller_id": LUKA_PHONE})
    assert r.status_code == 401
    r = app_client.post("/api/voice/tools/identify_caller", json={}, headers={"X-Debye-Voice-Secret": "nope"})
    assert r.status_code == 401
    assert app_client.post("/api/voice/post_call", json={}).status_code == 401


def test_identify_caller_by_phone_and_by_contact_id(app_client):
    c = app_client
    d = c.post("/api/voice/tools/identify_caller", headers=H,
               json={"conversation_id": "conv_1", "caller_id": LUKA_PHONE, "contact_id": "{{contact_id}}"}).json()
    assert d["known"] and d["first_name"] == "Luka" and d["contact_id"] == "c_202"
    assert d["heating"]["make"]
    d2 = c.post("/api/voice/tools/identify_caller", headers=H, json={"contact_id": "c_203", "caller_id": ""}).json()
    assert d2["first_name"] == "Jonas"
    d3 = c.post("/api/voice/tools/identify_caller", headers=H, json={"caller_id": "+4915100000000"}).json()
    assert d3["known"] is False


def test_call_opens_case_and_continues_on_whatsapp(app_client):
    c = app_client
    c.post("/api/voice/tools/identify_caller", headers=H, json={"conversation_id": "conv_2", "contact_id": "c_202"})
    r = report(c, "conv_2", contact_id="c_202", caller_id="None", summary="Heizung seit heute Morgen kalt",
               error_code="F 28", all_radiators_cold="yes")
    assert r["ok"] and not r["duplicate"]
    assert r["explain_error_code"].startswith(
        "That error means the boiler's ignition failed (error code F.28)")
    case_id = r["case_id"]
    assert case_detail(c, case_id)["error_code"] == "F.28"
    assert outbox(c) == []  # nothing on WhatsApp while the call is running

    done = c.post("/api/voice/post_call", headers=H, json=post_call_payload("conv_2")).json()
    assert done["case_id"] == case_id
    assert done["line"].startswith("Call with Luka (1:12): ")

    detail = case_detail(c, case_id)
    kinds = [e["kind"] for e in detail["events"]]
    assert "call.completed" in kinds and "triage.answer" in kinds
    call_ev = next(e for e in detail["events"] if e["kind"] == "call.completed")
    assert call_ev["summary"] == ("Call with Luka (1:12): heating cold, all radiators cold, ignition failed (F.28). "
                                  "Case opened, consent asked on WhatsApp.")
    assert call_ev["data"]["summary"].startswith("Luka reported")  # ElevenLabs' own summary kept in the data

    texts = outbox_texts(c)
    assert "Thanks for your call, Luka" in texts[0]
    assert "That error means the boiler's ignition failed (error code F.28)" in texts[0]
    assert any(f"consent_yes:{case_id}" in t for t in texts)  # consent buttons; triage not asked again
    assert not any("cold_all" in t for t in texts)

    # webhook retry, or page + webhook both firing: recorded once
    again = c.post("/api/voice/post_call", headers=H, json=post_call_payload("conv_2")).json()
    assert again.get("already_done")
    assert len(outbox(c)) == len(texts)

    # the consent tap on WhatsApp continues the same case
    tap = {"entry": [{"changes": [{"value": {"messages": [{
        "from": "490000000001", "id": "wamid.voice.consent", "type": "interactive",
        "interactive": {"type": "button_reply",
                        "button_reply": {"id": f"consent_yes:{case_id}", "title": "Ja, gerne"}}}]}}]}]}
    c.post("/webhooks/whatsapp", json=tap)
    assert case_detail(c, case_id)["status"] in ("requested", "approval_pending")


def test_call_without_triage_answer_asks_on_whatsapp(app_client):
    c = app_client
    r = report(c, "conv_3", contact_id="c_202")
    assert "still_ask" in r
    c.post("/api/voice/post_call", headers=H, json=post_call_payload("conv_3", secs=45))
    assert any(f"cold_all:{r['case_id']}" in t for t in outbox_texts(c))


def test_neighbour_call_joins_open_case(app_client):
    c = app_client
    first = report(c, "conv_4", contact_id="c_202", all_radiators_cold="yes")
    second = report(c, "conv_5", caller_id="+490000000002", summary="Auch bei uns kalt")
    assert second["duplicate"] and second["case_id"] == first["case_id"]


def test_post_call_hmac_signature(app_client, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_WEBHOOK_SECRET", "whsec")
    c = app_client
    report(c, "conv_6", contact_id="c_202")
    raw = json.dumps(post_call_payload("conv_6")).encode()
    t = str(int(time.time()))
    sig = hmac.new(b"whsec", f"{t}.".encode() + raw, hashlib.sha256).hexdigest()
    bad = c.post("/api/voice/post_call", content=raw,
                 headers={"ElevenLabs-Signature": f"t={t},v0=deadbeef", "content-type": "application/json"})
    assert bad.status_code == 401
    ok = c.post("/api/voice/post_call", content=raw,
                headers={"ElevenLabs-Signature": f"t={t},v0={sig}", "content-type": "application/json"})
    assert ok.status_code == 200 and ok.json()["case_id"]


def test_call_page_and_signed_url_without_agent(app_client, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_AGENT_ID", raising=False)
    r = app_client.get("/call")
    assert r.status_code == 200 and "Call Debye" in r.text
    assert app_client.get("/api/voice/signed_url").status_code == 503


def test_signed_url_stubbed(app_client, monkeypatch):
    from app.voice import calls

    async def fake(agent_id):
        return f"wss://example/{agent_id}"

    monkeypatch.setenv("ELEVENLABS_AGENT_ID", "agent_test")
    monkeypatch.setattr(calls, "signed_url", fake)
    d = app_client.get("/api/voice/signed_url?contact=c_202").json()
    assert d["signed_url"] == "wss://example/agent_test" and d["contact_name"] == "Luka"


def test_finish_when_done_polls_elevenlabs(app_client, monkeypatch):
    from app.voice import calls

    c = app_client
    report(c, "conv_7", contact_id="c_202", all_radiators_cold="no")
    answers = [{"status": "processing"}, post_call_payload("conv_7")["data"]]

    async def fake_fetch(cid):
        return answers.pop(0)

    monkeypatch.setattr(calls, "fetch_conversation", fake_fetch)
    monkeypatch.setattr(calls, "POLL_SECONDS", 0.01)
    res = asyncio.run(calls.finish_when_done("conv_7", 5))
    assert res["line"].startswith("Call with Luka (1:12)")
