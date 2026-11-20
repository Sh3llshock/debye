"""Real-OpenAI smoke test (costs a few cents). Runs only with DEBYE_LIVE=1 and OPENAI_API_KEY in env or .env."""
import os
from pathlib import Path

import pytest

import conftest

REPO = Path(__file__).resolve().parents[3]


def _key():
    if conftest.LIVE_OPENAI_KEY:
        return conftest.LIVE_OPENAI_KEY
    for f in (REPO / ".env", REPO / "backend" / ".env"):
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                k, _, v = line.partition("=")
                if k.strip() == "OPENAI_API_KEY" and v.strip():
                    return v.strip().strip('"').strip("'")
    return None


pytestmark = pytest.mark.skipif(os.getenv("DEBYE_LIVE") != "1" or not _key(), reason="live OpenAI test disabled")


def test_real_openai_reads_f28_photo(client, svc, monkeypatch):
    from app.agent import loop, openai_loop

    monkeypatch.setenv("OPENAI_API_KEY", _key())
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    openai_loop.set_client(None)
    photo = REPO / "data" / "demo" / "boiler_display_F28.jpg"
    body = {"entry": [{"changes": [{"value": {"messages": [{
        "from": "490000000001", "id": "wamid.live.oa1", "type": "image",
        "image": {"id": f"local:{photo}", "mime_type": "image/jpeg", "caption": "Heizung ist kalt"}}]}}]}]}
    client.post("/webhooks/whatsapp", json=body)
    assert loop.last_turn_fallback is False, "model call failed; scripted fallback answered"
    assert any(c[0] == "open_case" and c[3] == "F.28" for c in svc.calls), svc.calls
    last = client.get("/webhooks/whatsapp/_outbox").json()["messages"][-1]["payload"]
    print(last)
    assert "F.28" in last["interactive"]["body"]["text"]
    assert last["interactive"]["action"]["buttons"][0]["reply"]["id"].startswith("cold_all:case_")
    openai_loop.set_client(None)
