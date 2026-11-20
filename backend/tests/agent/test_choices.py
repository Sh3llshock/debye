"""Free-text answers to open questions are understood and recorded like taps."""
import asyncio

import pytest

from app.agent import choice
from app.channels.base import Option

LUKA = "490000000001"
_n = 0


def wa(body, from_=LUKA):
    global _n
    _n += 1
    return {"entry": [{"changes": [{"value": {"messages": [
        {"from": from_, "id": f"wamid.ch.{_n}", "type": "text", "text": {"body": body}}]}}]}]}


def last(client):
    p = client.get("/webhooks/whatsapp/_outbox").json()["messages"][-1]["payload"]
    return p["text"]["body"] if p["type"] == "text" else p["interactive"]["body"]["text"]


CONSENT = [Option("consent_yes:c1", "Yes, go ahead"), Option("consent_no:c1", "No")]
COLD = [Option("cold_all:c1", "All cold"), Option("cold_some:c1", "Just one room")]
SLOTS = [Option("slot_1:c1", "Sat 8–10"), Option("slot_2:c1", "Sun 14–16"), Option("slot_none:c1", "None of these work")]
FIXED = [Option("fixed_yes:c1", "Yes, all warm"), Option("fixed_no:c1", "No, still cold")]


@pytest.mark.parametrize("text,expected", [
    ("Sure", "consent_yes:c1"), ("ok", "consent_yes:c1"), ("yes go ahead", "consent_yes:c1"), ("fine 👍", "consent_yes:c1"),
    ("Yes, go ahead", "consent_yes:c1"), ("1", "consent_yes:c1"), ("no", "consent_no:c1"), ("rather not", "consent_no:c1"),
])
def test_fast_consent(text, expected):
    assert choice.fast_match(text, CONSENT).id == expected


@pytest.mark.parametrize("text,expected", [
    ("Saturday works", "slot_1:c1"), ("the first one", "slot_1:c1"), ("8-10", "slot_1:c1"), ("sunday", "slot_2:c1"),
    ("14 to 16", "slot_2:c1"), ("2", "slot_2:c1"),
])
def test_fast_slots(text, expected):
    assert choice.fast_match(text, SLOTS).id == expected


def test_fast_fixed_and_unclear():
    assert choice.fast_match("yes it's warm", FIXED).id == "fixed_yes:c1"
    assert choice.fast_match("is it ok if he comes later?", CONSENT) is None  # a question is not a yes
    assert choice.fast_match("just the shower", COLD) is None  # needs the model step


def test_free_text_consent_records_and_dispatches(client, svc, claude):
    claude([RuntimeError("down")])
    client.post("/webhooks/whatsapp", json=wa("My heating is cold"))
    client.post("/webhooks/whatsapp", json=wa("all of them"))  # model off → fast path miss → agent (down) …
    client.post("/webhooks/whatsapp", json=wa("All cold"))  # exact title → cold_all
    assert "share your name" in last(client)
    client.post("/webhooks/whatsapp", json=wa("Sure"))
    assert any(c[0] == "consent" for c in svc.calls)  # consent really recorded
    assert ("dispatch", "case_0001", "heizung-schmidt") in svc.calls
    assert "booked" in last(client)


def test_model_step_maps_free_text(client, svc, claude, monkeypatch):
    async def fake_model(text, options, question=None):
        return next(o for o in options if o.id.startswith("cold_some:")) if "shower" in text else None

    monkeypatch.setattr(choice, "model_match", fake_model)
    claude([RuntimeError("down")])
    client.post("/webhooks/whatsapp", json=wa("Heating cold"))
    client.post("/webhooks/whatsapp", json=wa("just the shower"))
    assert svc.events and any(e[2] == "triage.answer" and e[3] == "Only one room cold" for e in svc.events)
    assert "share your name" in last(client)


def test_unclear_answer_goes_to_agent_not_recorded(client, svc, claude, monkeypatch):
    async def none_model(*a, **k):
        return None

    monkeypatch.setattr(choice, "model_match", none_model)
    stub = claude([RuntimeError("down"), RuntimeError("down"), RuntimeError("down")])
    client.post("/webhooks/whatsapp", json=wa("Heating cold"))
    client.post("/webhooks/whatsapp", json=wa("All cold"))
    client.post("/webhooks/whatsapp", json=wa("what data exactly?"))
    assert not any(c[0] == "consent" for c in svc.calls)
    assert not any(c[0] == "dispatch" for c in svc.calls)


def test_approval_pending_told_once(client, svc, claude):
    from app import notify

    svc.approval_required = True
    claude([RuntimeError("down")])
    client.post("/webhooks/whatsapp", json=wa("Heating cold"))
    client.post("/webhooks/whatsapp", json=wa("All cold"))
    client.post("/webhooks/whatsapp", json=wa("yes"))
    asyncio.run(notify.notify_tenant("case_0001", "approval_pending", {}))
    msgs = client.get("/webhooks/whatsapp/_outbox").json()["messages"]
    texts = [m["payload"]["text"]["body"] for m in msgs if m["payload"]["type"] == "text"]
    assert sum("property manager is confirming the repair" in t for t in texts) == 1
    asyncio.run(notify.notify_tenant("case_0001", "approval_granted", {}))
    assert "approved the repair" in last(client)


def test_natural_list_text():
    from app.channels import twilio

    t = twilio.natural_text("Heizung Schmidt can send Tom at one of these times. Which one works for you?", SLOTS,
                            is_list=True)
    assert t.endswith("on Sat between 8 and 10 or on Sun between 14 and 16? Or just tell me if none of these work.")
    assert "1 =" not in t
