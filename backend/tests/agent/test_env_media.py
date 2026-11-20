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
    from app.config import settings

    monkeypatch.setattr(settings, "demo_mode", True)
    assert asyncio.run(media.transcribe(str(tmp_path / "x.ogg"))) == media.DEMO_TRANSCRIPT
    monkeypatch.setattr(settings, "demo_mode", False)
    assert asyncio.run(media.transcribe(str(tmp_path / "x.ogg"))) == ""


def test_invoice_fallback_matches_demo_pdf(monkeypatch, tmp_path):
    from app import media

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    inv = asyncio.run(media.extract_invoice(str(tmp_path / "x.pdf")))
    assert (inv["invoice_number"], inv["net_eur"], inv["vat_eur"], inv["gross_eur"], inv["labour_hours"]) == (
        "RE-2026-1187", 199.5, 37.91, 237.41, 1.0)
    assert [(li["qty"], li["unit_price"]) for li in inv["line_items"]] == [(1, 89.0), (1, 72.0), (1, 38.5)]


def test_outbox_follows_settings_demo_mode(client, monkeypatch):
    from app.config import settings

    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setattr(settings, "demo_mode", True)
    assert client.get("/webhooks/whatsapp/_outbox").status_code == 200
    monkeypatch.setattr(settings, "demo_mode", False)
    assert client.get("/webhooks/whatsapp/_outbox").status_code == 404


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
