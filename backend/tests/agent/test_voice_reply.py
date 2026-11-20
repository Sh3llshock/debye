import asyncio



def _voice(client, tmp_path, n):
    ogg = tmp_path / f"v{n}.ogg"
    ogg.write_bytes(b"OggS fake")
    body = {"entry": [{"changes": [{"value": {"messages": [{
        "from": "490000000001", "id": f"wamid.voice{n}", "type": "audio",
        "audio": {"id": f"local:{ogg}", "mime_type": "audio/ogg; codecs=opus"}}]}}]}]}
    client.post("/webhooks/whatsapp", json=body)


def _audio_msgs(client):
    return [m for m in client.get("/webhooks/whatsapp/_outbox").json()["messages"] if m["payload"]["type"] == "audio"]


def test_no_elevenlabs_key_no_voice_reply(client, svc, claude, tmp_path, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    claude([RuntimeError("down")])
    _voice(client, tmp_path, 1)
    assert _audio_msgs(client) == []


def test_voice_reply_once_per_conversation(client, svc, claude, tmp_path, monkeypatch):
    from app import media

    tts = tmp_path / "debye.ogg"
    tts.write_bytes(b"OggS tts")
    spoken = []

    async def fake_speak(t):
        spoken.append(t)
        return str(tts)

    monkeypatch.setattr(media, "speak", fake_speak)
    claude([RuntimeError("down"), RuntimeError("down")])
    _voice(client, tmp_path, 1)
    _voice(client, tmp_path, 2)
    audio = _audio_msgs(client)
    assert len(audio) == 1 and len(spoken) == 1
    assert spoken[0].startswith("Hi Luka, it's Debye.")
    assert audio[0]["to"] == "+490000000001"


def test_speak_with_fake_elevenlabs(monkeypatch, tmp_path):
    import httpx

    from app import media

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-not-a-key")
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    seen = {}

    class FakeResp:
        status_code = 200
        content = b"OggS" + b"\x00" * 50
        text = ""

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, params=None, headers=None, json=None):
            seen.update(url=url, params=params, json=json)
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    path = asyncio.run(media.speak("Hallo"))
    assert path and open(path, "rb").read(4) == b"OggS"
    assert seen["params"]["output_format"].startswith("opus")
    assert seen["json"]["text"] == "Hallo"

    monkeypatch.delenv("ELEVENLABS_API_KEY")
    assert asyncio.run(media.speak("Hallo")) is None
