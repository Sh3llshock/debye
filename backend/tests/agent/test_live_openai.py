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


def test_real_openai_english_default(client, svc, monkeypatch):
    from app.agent import loop, openai_loop

    monkeypatch.setenv("OPENAI_API_KEY", _key())
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    openai_loop.set_client(None)
    body = {"entry": [{"changes": [{"value": {"messages": [{
        "from": "490000000001", "id": "wamid.live.oa2", "type": "text",
        "text": {"body": "Hi, my heating stopped working this morning and the shower is cold too"}}]}}]}]}
    client.post("/webhooks/whatsapp", json=body)
    assert loop.last_turn_fallback is False
    last = client.get("/webhooks/whatsapp/_outbox").json()["messages"][-1]["payload"]
    text = last["interactive"]["body"]["text"] if last["type"] == "interactive" else last["text"]["body"]
    print("REPLY:", text)
    assert any(w in text.lower() for w in ("radiator", "cold", "heating"))
    assert not any(w in text for w in ("Heizkörper", "Heizung"))  # English, not German
    assert svc.cases["case_0001"]["priority"] == "urgent"
    openai_loop.set_client(None)


def test_real_openai_choice_matching(monkeypatch):
    import asyncio
    import time

    from app.agent import choice
    from app.channels.base import Option

    monkeypatch.setenv("OPENAI_API_KEY", _key())
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    cold = [Option("cold_all:c1", "All cold"), Option("cold_some:c1", "Just one room")]
    consent = [Option("consent_yes:c1", "Yes, go ahead"), Option("consent_no:c1", "No")]
    slots = [Option("slot_1:c1", "Sat 21 Nov, 8–10"), Option("slot_2:c1", "Sun 22 Nov, 14–16"),
             Option("slot_none:c1", "None of these work")]
    fixed = [Option("fixed_yes:c1", "Yes, all warm"), Option("fixed_no:c1", "No, still cold")]
    cases = [
        ("just the shower, the radiators are fine", cold, "Are all your radiators cold, or just one?", "cold_some:c1"),
        ("every single one is freezing", cold, "Are all your radiators cold, or just one?", "cold_all:c1"),
        ("sure thing, go for it", consent, "Is it okay if I share your name ... with them?", "consent_yes:c1"),
        ("hmm what exactly do you share?", consent, "Is it okay if I share your name ... with them?", None),
        ("the weekend morning one", slots, "Which one works for you?", "slot_1:c1"),
        ("neither, I'm away all weekend", slots, "Which one works for you?", "slot_none:c1"),
        ("yep toasty again, thanks!", fixed, "Is it nice and warm again?", "fixed_yes:c1"),
    ]
    for text, opts, q, want in cases:
        t0 = time.perf_counter()
        got = asyncio.run(choice.model_match(text, opts, q))
        print(f"{time.perf_counter() - t0:.2f}s  {text!r} -> {got.id if got else None}")
        assert (got.id if got else None) == want, text
