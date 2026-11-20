"""Twilio WhatsApp sandbox adapter with a stubbed Twilio API."""
from types import SimpleNamespace

import pytest

LUKA = "whatsapp:+490000000001"


class FakeTwilioHTTP:
    def __init__(self):
        self.posts, self.gets = [], []

    async def post(self, url, data=None, auth=None):
        self.posts.append({"url": url, "data": dict(data), "auth": auth})
        return SimpleNamespace(status_code=201, json=lambda: {"sid": f"SM{len(self.posts):04d}"}, text="")

    async def get(self, url, auth=None):
        self.gets.append({"url": url, "auth": auth})
        return SimpleNamespace(status_code=200, content=b"\xff\xd8 fake jpeg", raise_for_status=lambda: None)


@pytest.fixture
def tw(monkeypatch, svc):
    from app.channels import twilio

    monkeypatch.delenv("WA_FAKE_SEND", raising=False)
    monkeypatch.setenv("WA_PROVIDER", "twilio")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("TWILIO_WHATSAPP_FROM", "whatsapp:+4915888620339")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://debye.example.test")
    monkeypatch.setenv("TWILIO_VALIDATE_SIGNATURE", "0")
    fake = FakeTwilioHTTP()
    monkeypatch.setattr(twilio.channel, "_client", fake)
    twilio._pending.clear()
    return fake


def post_twilio(client, **params):
    base = {"From": LUKA, "To": "whatsapp:+4915888620339", "MessageSid": f"SMin{abs(hash(str(params))) % 10**8}",
            "NumMedia": "0", "ProfileName": "Luka"}
    base.update(params)
    r = client.post("/webhooks/twilio", data=base)
    assert r.status_code == 200 and "<Response>" in r.text
    return r


def test_provider_selection(monkeypatch):
    from app.channels import twilio

    monkeypatch.delenv("WA_PROVIDER", raising=False)
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    assert twilio.wa_provider() == "meta"
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACx")
    assert twilio.wa_provider() == "twilio"
    monkeypatch.setenv("WA_PROVIDER", "meta")
    assert twilio.wa_provider() == "meta"
    assert twilio.to_e164("whatsapp:+49 151 2345") == "+491512345"


def test_signature_validation(client, svc, monkeypatch):
    from app.channels import twilio

    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://tunnel.example.test")
    monkeypatch.delenv("TWILIO_VALIDATE_SIGNATURE", raising=False)
    monkeypatch.setattr(twilio, "parse_twilio", lambda p: SimpleNamespace(from_phone="", wa_message_id=None))
    params = {"From": LUKA, "Body": "hi", "MessageSid": "SMsig1", "NumMedia": "0"}
    assert client.post("/webhooks/twilio", data=params, headers={"X-Twilio-Signature": "nope"}).status_code == 403
    good = twilio.expected_signature("https://tunnel.example.test/webhooks/twilio", params, "test-token")
    assert client.post("/webhooks/twilio", data=params, headers={"X-Twilio-Signature": good}).status_code == 200
    # known vector from Twilio's docs
    doc = twilio.expected_signature(
        "https://mycompany.com/myapp.php?foo=1&bar=2",
        {"CallSid": "CA1234567890ABCDE", "Caller": "+12349013030", "Digits": "1234", "From": "+12349013030",
         "To": "+18005551212"}, "12345")
    assert doc == "0/KCTR6DLpKmkAf8muzZqo1nDgQ="  # Twilio docs example


def test_numbered_buttons_roundtrip(client, svc, claude, tw):
    claude([RuntimeError("down")])  # scripted flow, deterministic
    post_twilio(client, Body="Hallo, meine Heizung ist kalt")
    sent = tw.posts[-1]["data"]
    assert sent["From"] == "whatsapp:+4915888620339" and sent["To"] == LUKA
    assert "1 = All cold" in sent["Body"] and "2 = Just one room" in sent["Body"]
    assert tw.posts[-1]["auth"] == ("ACtest", "test-token")
    assert sent["StatusCallback"] == "https://debye.example.test/webhooks/twilio/status"

    post_twilio(client, Body="1")  # → cold_all:case_0001 in code
    assert any(c[0] == "open_case" for c in svc.calls)
    consent = tw.posts[-1]["data"]["Body"]
    assert "share your name" in consent and "1 = Yes, go ahead" in consent

    post_twilio(client, Body="yes, go ahead")  # option text also works
    assert any(c[0] == "consent" for c in svc.calls)
    assert ("dispatch", "case_0001", "heizung-schmidt") in svc.calls


def test_unmatched_number_goes_to_agent_as_text(client, svc, claude, tw):
    from app.channels import twilio

    twilio.remember_options("+490000000001", [twilio.Option("cold_all:c1", "All cold")])
    assert twilio.match_numbered_reply("+490000000001", "7") is None  # out of range → plain text
    assert twilio.match_numbered_reply("+490000000001", "1.").id == "cold_all:c1"
    assert twilio.match_numbered_reply("+490000000001", "1") is None  # cleared after use


def test_inbound_media_downloaded_with_basic_auth(client, svc, claude, tw):
    claude([RuntimeError("down")])
    post_twilio(client, Body="", NumMedia="1",
                MediaUrl0="https://api.twilio.com/2010-04-01/Accounts/ACtest/Messages/MM1/Media/ME1",
                MediaContentType0="image/jpeg")
    assert tw.gets and tw.gets[0]["auth"] == ("ACtest", "test-token")
    assert any(c[0] == "attach" and c[2] == "photo" for c in svc.calls)


def test_outbound_media_public_url(client, svc, tw, tmp_path):
    import asyncio

    from app.channels import twilio

    ogg = tmp_path / "debye.ogg"
    ogg.write_bytes(b"OggS voice")
    asyncio.run(twilio.channel.send_media("+490000000001", "audio", str(ogg)))
    url = tw.posts[-1]["data"]["MediaUrl"]
    assert url.startswith("https://debye.example.test/webhooks/twilio/media/") and url.endswith(".ogg")
    r = client.get(url.replace("https://debye.example.test", ""))
    assert r.status_code == 200 and r.content == b"OggS voice" and r.headers["content-type"].startswith("audio/ogg")
    assert client.get("/webhooks/twilio/media/unknown.ogg").status_code == 404


def test_status_callback_logs_failure(client, svc, tw, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="debye.twilio"):
        r = client.post("/webhooks/twilio/status", data={"MessageSid": "SM1", "MessageStatus": "undelivered",
                                                         "ErrorCode": "63016", "ErrorMessage": "outside window"})
    assert r.status_code == 204
    assert "Twilio delivery FAILED" in caplog.text and "63016" in caplog.text


def test_fake_send_still_uses_meta_outbox(client, svc, claude, monkeypatch):
    monkeypatch.setenv("WA_PROVIDER", "twilio")  # no Twilio creds → fake send → Meta-shaped outbox
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    claude([RuntimeError("down")])
    client.post("/webhooks/twilio", data={"From": LUKA, "Body": "Heizung kalt", "MessageSid": "SMfake1",
                                          "NumMedia": "0"})
    last = client.get("/webhooks/whatsapp/_outbox").json()["messages"][-1]["payload"]
    assert last["type"] == "interactive"  # simulator-compatible
