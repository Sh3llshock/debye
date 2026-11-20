"""Real-Claude smoke test (costs a few cents). Runs only with DEBYE_LIVE=1 and ANTHROPIC_API_KEY set."""
import os

import pytest

import conftest

pytestmark = pytest.mark.skipif(
    not (os.getenv("DEBYE_LIVE") == "1" and conftest.LIVE_ANTHROPIC_KEY), reason="live Claude test disabled"
)


def test_real_claude_triage(client, svc, monkeypatch):
    from app.agent import loop

    monkeypatch.setenv("ANTHROPIC_API_KEY", conftest.LIVE_ANTHROPIC_KEY)
    loop.set_client(None)
    body = {"entry": [{"changes": [{"value": {"messages": [{
        "from": "490000000001", "id": "wamid.live1", "type": "text",
        "text": {"body": "Hallo, bei mir ist die Heizung seit heute früh komplett kalt. Am Kessel steht F.28."}}]}}]}]}
    client.post("/webhooks/whatsapp", json=body)
    assert loop.last_turn_fallback is False, "Claude call failed; scripted fallback answered"
    msgs = client.get("/webhooks/whatsapp/_outbox").json()["messages"]
    assert any(c[0] == "open_case" for c in svc.calls), svc.calls
    last = msgs[-1]["payload"]
    print(last)
    assert last["type"] == "interactive"
    assert last["interactive"]["action"]["buttons"][0]["reply"]["id"].startswith("cold_all:case_")
    loop.set_client(None)
