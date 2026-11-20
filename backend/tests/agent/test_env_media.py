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
