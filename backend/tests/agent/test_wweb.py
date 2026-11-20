"""Linked-phone bridge channel (WA_PROVIDER=wweb) with a stub bridge."""
import base64
import json
from types import SimpleNamespace

import pytest

LUKA = "+490000000001"


class StubBridge:
    def __init__(self):
        self.calls = []

    async def post(self, url, content=None, headers=None):
        self.calls.append({"url": url, "body": json.loads(content), "sig": headers.get("x-wweb-signature")})
        return SimpleNamespace(status_code=200, json=lambda: {"ok": True, "id": f"B{len(self.calls)}"}, text="")


@pytest.fixture
def bridge(monkeypatch, svc):
    from app.channels import twilio, wweb

    monkeypatch.delenv("WA_FAKE_SEND", raising=False)
    monkeypatch.setenv("WA_PROVIDER", "wweb")
    monkeypatch.setenv("WWEB_SECRET", "s3cret")
    monkeypatch.setenv("WWEB_BRIDGE_URL", "http://127.0.0.1:3010")
    stub = StubBridge()
    monkeypatch.setattr(wweb.channel, "_client", stub)
    twilio._pending.clear()
    return stub


def post_wweb(client, secret="s3cret", **payload):
    from app.channels import wweb

    body = {"from_e164": LUKA, "message_id": f"M{abs(hash(str(payload))) % 10**8}", "push_name": "Luka", **payload}
    raw = json.dumps(body).encode()
    import hashlib
    import hmac

    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post("/webhooks/wweb", content=raw, headers={"content-type": "application/json",
                                                                "x-wweb-signature": sig})


def test_signature_required(client, bridge):
    assert post_wweb(client, secret="wrong", text="hi").status_code == 401
    r = client.post("/webhooks/wweb", content=b"{}", headers={"content-type": "application/json"})
    assert r.status_code == 401


def test_numbered_flow_through_bridge(client, svc, claude, bridge):
    from app.channels import wweb

    claude([RuntimeError("down")])  # scripted flow
    assert post_wweb(client, text="My heating is cold").status_code == 200
    sent = bridge.calls[-1]
    assert sent["url"] == "http://127.0.0.1:3010/send" and sent["body"]["to_e164"] == LUKA
    assert "1 = All cold" in sent["body"]["text"] and "2 = Just one room" in sent["body"]["text"]
    raw = json.dumps(sent["body"], ensure_ascii=False).encode()
    assert sent["sig"] == wweb.sign(raw)  # outbound is signed for the bridge

    post_wweb(client, text="1")  # → cold_all:case_0001
    assert "share your name" in bridge.calls[-1]["body"]["text"]
    post_wweb(client, text="Yes, go ahead")
    assert ("dispatch", "case_0001", "heizung-schmidt") in svc.calls


def test_inbound_media_base64_saved_and_attached(client, svc, claude, bridge):
    claude([RuntimeError("down")])
    jpeg = base64.b64encode(b"\xff\xd8 fake jpeg").decode()
    post_wweb(client, text="", media=[{"base64": jpeg, "mime": "image/jpeg", "filename": None}])
    assert any(c[0] == "attach" and c[2] == "photo" for c in svc.calls)


def test_voice_note_sent_as_ptt(client, svc, bridge, tmp_path):
    import asyncio

    from app.channels import wweb

    ogg = tmp_path / "debye.ogg"
    ogg.write_bytes(b"OggS")
    asyncio.run(wweb.channel.send_media(LUKA, "audio", str(ogg)))
    body = bridge.calls[-1]["body"]
    assert bridge.calls[-1]["url"].endswith("/send-media")
    assert body["ptt"] is True and body["mime"] == "audio/ogg" and body["path"].endswith("debye.ogg")


def test_duplicate_message_ignored(client, svc, claude, bridge):
    claude([RuntimeError("down"), RuntimeError("down")])
    post_wweb(client, text="Heating cold", message_id="SAME1")
    n = len(bridge.calls)
    r = post_wweb(client, text="Heating cold", message_id="SAME1")
    assert r.json().get("duplicate") is True and len(bridge.calls) == n


def test_provider_switch(monkeypatch):
    from app.channels import twilio, whatsapp, wweb

    monkeypatch.delenv("WA_FAKE_SEND", raising=False)
    monkeypatch.setenv("WA_PROVIDER", "wweb")
    assert twilio.wa_provider() == "wweb" and not whatsapp.fake_send_enabled()
    assert whatsapp.provider_channel._impl() is wweb.channel
    monkeypatch.setenv("WA_FAKE_SEND", "1")
    assert whatsapp.provider_channel._impl() is whatsapp.channel  # simulator outbox
