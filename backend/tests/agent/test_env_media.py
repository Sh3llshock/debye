import asyncio


def test_env_loader_does_not_override(tmp_path, monkeypatch):
    from app.channels import base

    (tmp_path / ".env").write_text('WA_TOKEN_X="from-file"\nKEEP_X=file\n# comment\nEMPTY_X=\n', encoding="utf-8")
    monkeypatch.setattr(base, "_BACKEND_DIR", tmp_path / "backend")
    monkeypatch.delenv("DEBYE_NO_DOTENV", raising=False)
    monkeypatch.delenv("WA_TOKEN_X", raising=False)
    monkeypatch.setenv("KEEP_X", "env")
    base.load_env_files()
    import os

    assert os.environ["WA_TOKEN_X"] == "from-file"
    assert os.environ["KEEP_X"] == "env"
    assert "EMPTY_X" not in os.environ
    monkeypatch.delenv("WA_TOKEN_X")


def test_demo_transcript_without_key(monkeypatch, tmp_path):
    from app import media

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("DEMO_MODE", "1")
    assert asyncio.run(media.transcribe(str(tmp_path / "x.ogg"))) == media.DEMO_TRANSCRIPT
    monkeypatch.setenv("DEMO_MODE", "0")
    assert asyncio.run(media.transcribe(str(tmp_path / "x.ogg"))) == ""


def test_transcribe_switches_to_eu_endpoint(monkeypatch, tmp_path):
    import openai

    from app import media

    calls = []

    class FakeTranscriptions:
        def __init__(self, base_url):
            self.base_url = base_url

        async def create(self, **kw):
            calls.append((self.base_url, kw["model"]))
            if self.base_url != media.EU_OPENAI_BASE_URL:
                raise RuntimeError("401 - Attempted to access resource from outside project geography EU")
            return type("R", (), {"text": "Die Heizung ist kalt."})()

    class FakeClient:
        def __init__(self, timeout=None, base_url=None):
            self.audio = type("A", (), {"transcriptions": FakeTranscriptions(base_url)})()

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)
    monkeypatch.setattr(media, "_openai_base_url", None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-key")
    f = tmp_path / "v.ogg"
    f.write_bytes(b"OggS")
    assert asyncio.run(media.transcribe(str(f))) == "Die Heizung ist kalt."
    assert calls == [(None, "gpt-4o-transcribe"), (media.EU_OPENAI_BASE_URL, "gpt-4o-transcribe")]
    assert media._openai_base_url == media.EU_OPENAI_BASE_URL  # remembered for the next call


def test_no_anthropic_key_falls_back_immediately(client, svc, monkeypatch):
    import time as _t

    from app.agent import loop

    loop.set_client(None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    body = {"entry": [{"changes": [{"value": {"messages": [
        {"from": "490000000001", "id": "wamid.nokey", "type": "text", "text": {"body": "Heizung kalt"}}]}}]}]}
    t0 = _t.perf_counter()
    client.post("/webhooks/whatsapp", json=body)
    assert _t.perf_counter() - t0 < 3
    assert loop.last_turn_fallback is True
