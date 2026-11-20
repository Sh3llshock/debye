import asyncio
import hashlib
import hmac
import json
from pathlib import Path

from agent_stubs import text, tool_use

LENA = "490000000001"
JONAS = "490000000002"
_n = 0


def wa_body(from_, **msg):
    global _n
    _n += 1
    m = {"from": from_, "id": msg.pop("id", f"wamid.{_n}"), "timestamp": "1"}
    m.update(msg)
    return {"object": "whatsapp_business_account", "entry": [{"id": "x", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "contacts": [{"wa_id": from_, "profile": {"name": "X"}}], "messages": [m]}}]}]}


def button(from_, id_, title="t"):
    return wa_body(from_, type="interactive", interactive={"type": "button_reply", "button_reply": {"id": id_, "title": title}})


def list_reply(from_, id_, title="t"):
    return wa_body(from_, type="interactive", interactive={"type": "list_reply", "list_reply": {"id": id_, "title": title}})


def outbox(client):
    return client.get("/webhooks/whatsapp/_outbox").json()["messages"]


def last_payload(client):
    return outbox(client)[-1]["payload"]


def ids(payload):
    it = payload["interactive"]
    if it["type"] == "button":
        return [b["reply"]["id"] for b in it["action"]["buttons"]]
    return [r["id"] for s in it["action"]["sections"] for r in s["rows"]]


def _media_files(tmp_path):
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"OggS fake")
    photo = tmp_path / "display.jpg"
    photo.write_bytes(b"\xff\xd8\xff fake jpeg")
    return audio, photo


def test_verify_endpoint(client):
    ok = client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                                                   "hub.challenge": "123"})
    assert ok.status_code == 200 and ok.text == "123"
    bad = client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "nope",
                                                    "hub.challenge": "123"})
    assert bad.status_code == 403


def test_signature_check(client, monkeypatch):
    monkeypatch.setenv("WA_APP_SECRET", "s3cret")
    raw = json.dumps(wa_body(LENA, type="text", text={"body": "hi"})).encode()
    r = client.post("/webhooks/whatsapp", content=raw, headers={"X-Hub-Signature-256": "sha256=deadbeef"})
    assert r.status_code == 401
    sig = hmac.new(b"s3cret", raw, hashlib.sha256).hexdigest()
    from app.channels import whatsapp

    monkeypatch.setattr(whatsapp, "process_inbound", _noop)
    r = client.post("/webhooks/whatsapp", content=raw, headers={"X-Hub-Signature-256": f"sha256={sig}"})
    assert r.status_code == 200


async def _noop(msg):
    return None


def test_golden_path(client, svc, claude, monkeypatch, tmp_path):
    from app import media, notify

    async def fake_transcribe(path, language="de"):
        return "Hallo, meine Heizung ist seit heute Morgen komplett kalt."

    monkeypatch.setattr(media, "transcribe", fake_transcribe)
    stub = claude([
        [tool_use("open_case", summary="Heizung kalt, Fehler F.28", symptoms="komplett kalt",
                  error_code="F.28", priority="urgent")],
        [tool_use("ask_buttons", text="Oh nein! Der Kessel zeigt F.28 (Zündung). Sind alle Heizkörper kalt?",
                  options=[{"id": "cold_all:case_0001", "title": "Überall kalt"},
                           {"id": "cold_some:case_0001", "title": "Nur ein Raum"}])],
        [text("done")],
    ])
    audio, photo = _media_files(tmp_path)

    # 1. voice note + photo (two webhooks, batched by the router lock/drain)
    client.post("/webhooks/whatsapp", json=wa_body(LENA, type="audio", audio={"id": f"local:{audio}", "mime_type": "audio/ogg; codecs=opus"}))
    client.post("/webhooks/whatsapp", json=wa_body(LENA, type="image", image={"id": f"local:{photo}", "mime_type": "image/jpeg"}))
    assert ("open_case", "case_0001", "Heizung kalt, Fehler F.28", "F.28") in svc.calls
    assert ids(last_payload(client)) == ["cold_all:case_0001", "cold_some:case_0001"]
    req = stub.requests[0]
    assert req["model"] == "claude-opus-5-5" and req["output_config"] == {"effort": "low"}
    assert req["fallbacks"] == "default" and all(t["strict"] for t in req["tools"])
    assert any(c[0] == "attach" and c[2] == "photo" for c in svc.calls)

    # 2. tap "Überall kalt" → consent buttons, no LLM
    n_req = len(stub.requests)
    client.post("/webhooks/whatsapp", json=button(LENA, "cold_all:case_0001", "Überall kalt"))
    assert len(stub.requests) == n_req
    assert ids(last_payload(client)) == ["consent_yes:case_0001", "consent_no:case_0001"]
    assert "Heizung Schmidt" in last_payload(client)["interactive"]["body"]["text"]

    # 3. consent → consent row + dispatch
    client.post("/webhooks/whatsapp", json=button(LENA, "consent_yes:case_0001", "Ja, gerne"))
    assert any(c[0] == "consent" and c[2] == "heizung-schmidt" for c in svc.calls)
    assert ("dispatch", "case_0001", "heizung-schmidt") in svc.calls

    # 4. partner proposes slots → list message
    slots = [{"start": "2026-11-21T08:00:00+01:00", "end": "2026-11-21T10:00:00+01:00", "label": "Morgen 8–10"},
             {"start": "2026-11-26T14:00:00+01:00", "end": "2026-11-26T16:00:00+01:00", "label": "Do 14–16"}]
    asyncio.run(notify.notify_tenant("case_0001", "slots_proposed", {"slots": slots}))
    p = last_payload(client)
    assert p["interactive"]["type"] == "list"
    assert ids(p) == ["slot_1:case_0001", "slot_2:case_0001", "slot_none:case_0001"]

    # 5. resident picks slot 1 → confirm_slot with 1-based index
    client.post("/webhooks/whatsapp", json=list_reply(LENA, "slot_1:case_0001", "Morgen 8–10"))
    assert ("confirm_slot", "case_0001", 1) in svc.calls
    assert "Morgen 8–10" in last_payload(client)["text"]["body"]

    # 6. partner done → "warm again?" → yes closes
    asyncio.run(notify.notify_tenant("case_0001", "job_completed", {}))
    assert ids(last_payload(client)) == ["fixed_yes:case_0001", "fixed_no:case_0001"]
    client.post("/webhooks/whatsapp", json=button(LENA, "fixed_yes:case_0001", "Ja, alles warm"))
    assert ("fixed", "case_0001", True) in svc.calls
    assert svc.cases["case_0001"]["status"] == "closed"
    # every outbound + inbound message was logged for the dashboard
    assert any(m["direction"] == "in" for m in svc.messages)
    assert sum(m["direction"] == "out" for m in svc.messages) == len(outbox(client))


def test_claude_down_uses_scripted_fallback(client, svc, claude):
    claude([RuntimeError("API down")])
    client.post("/webhooks/whatsapp", json=wa_body(LENA, type="text", text={"body": "Heizung kalt!"}))
    assert any(c[0] == "open_case" for c in svc.calls)
    assert ids(last_payload(client)) == ["cold_all:case_0001", "cold_some:case_0001"]


def test_refusal_hands_off(client, svc, claude):
    claude(["refusal"])
    client.post("/webhooks/whatsapp", json=wa_body(LENA, type="text", text={"body": "hallo"}))
    assert "Hausverwaltung" in last_payload(client)["text"]["body"]


def test_agent_silent_turn_falls_back(client, svc, claude):
    claude([[text("I would ask about radiators")]])  # forgot to use a tool
    client.post("/webhooks/whatsapp", json=wa_body(LENA, type="text", text={"body": "Heizung kalt"}))
    assert ids(last_payload(client))[0].startswith("cold_all:")


def test_neighbour_duplicate_is_linked(client, svc, claude):
    claude([RuntimeError("down"), RuntimeError("down")])
    client.post("/webhooks/whatsapp", json=wa_body(LENA, type="text", text={"body": "Heizung kalt"}))
    client.post("/webhooks/whatsapp", json=wa_body(JONAS, type="text", text={"body": "Bei mir auch kalt"}))
    assert ("link", "case_0001", "c_203", "affected") in svc.calls
    assert sum(c[0] == "open_case" for c in svc.calls) == 1
    assert "schon gemeldet" in last_payload(client)["text"]["body"]


def test_dedupe_same_message_id(client, svc, claude):
    stub = claude([[tool_use("reply", text="Hallo!")], [text("ok")], [tool_use("reply", text="again")]])
    body = wa_body(LENA, type="text", text={"body": "hi"}, id="wamid.dup")
    client.post("/webhooks/whatsapp", json=body)
    client.post("/webhooks/whatsapp", json=body)
    assert len(stub.requests) == 2  # one turn (tool_use + end), not two
    assert len(outbox(client)) == 1


def test_approval_required(client, svc, claude):
    svc.approval_required = True
    claude([RuntimeError("down")])
    client.post("/webhooks/whatsapp", json=wa_body(LENA, type="text", text={"body": "kalt"}))
    client.post("/webhooks/whatsapp", json=button(LENA, "cold_all:case_0001"))
    client.post("/webhooks/whatsapp", json=button(LENA, "consent_yes:case_0001"))
    assert "freigeben" in last_payload(client)["text"]["body"]


def test_unknown_sender(client, svc, claude):
    client.post("/webhooks/whatsapp", json=wa_body("4917600000000", type="text", text={"body": "hi"}))
    assert "nicht registriert" in last_payload(client)["text"]["body"]


def test_tool_error_is_reported_to_claude(client, svc, claude):
    stub = claude([[tool_use("ask_buttons", text="?", options=[])], [tool_use("reply", text="Wie kann ich helfen?")], [text("ok")]])
    client.post("/webhooks/whatsapp", json=wa_body(LENA, type="text", text={"body": "hi"}))
    second = stub.requests[1]["messages"][-1]["content"][0]
    assert second["is_error"] is True
    assert last_payload(client)["text"]["body"] == "Wie kann ich helfen?"


def test_slots_go_to_reporter_neighbour_gets_update(client, svc, claude):
    from app import notify

    claude([RuntimeError("down"), RuntimeError("down")])
    client.post("/webhooks/whatsapp", json=wa_body(LENA, type="text", text={"body": "Heizung kalt"}))
    client.post("/webhooks/whatsapp", json=wa_body(JONAS, type="text", text={"body": "auch kalt"}))
    asyncio.run(notify.notify_tenant("case_0001", "slots_proposed", {"slots": [{"start": "a", "end": "b", "label": "Morgen 8–10"}]}))
    lists = [m for m in outbox(client) if m["payload"].get("type") == "interactive" and m["payload"]["interactive"]["type"] == "list"]
    assert [m["to"] for m in lists] == ["+490000000001"]
    client.post("/webhooks/whatsapp", json=list_reply(LENA, "slot_1:case_0001"))
    assert outbox(client)[-1]["to"] == "+490000000002"
    assert "Morgen 8–10" in outbox(client)[-1]["payload"]["text"]["body"]
