"""Experimental planner (PLANNER_ENABLED): off by default; on: holding message, plan stored and shown
to the agent, its next question allowed, one re-plan."""
import asyncio

from test_diagnosis import texts, wa


def _plan():
    return {"causes": [{"id": "hot_water_used_up", "probability": 0.5, "why": "x"},
                       {"id": "boiler_fault", "probability": 0.2, "why": "y"}],
            "questions": [{"id": "q_scope", "if_answers": []}, {"id": "q_hot_water_use", "if_answers": []}],
            "self_help": ["hot_water_used_up"], "stop_when": "after the hot-water-use answer"}


def test_planner_off_by_default(client, svc, claude, monkeypatch):
    from app.agent import planner

    monkeypatch.delenv("PLANNER_ENABLED", raising=False)
    called = []
    monkeypatch.setattr(planner, "make_plan", lambda *a, **k: called.append(1))
    claude([RuntimeError("down")] * 5)
    client.post("/webhooks/whatsapp", json=wa("my shower is cold"))
    assert not called and not texts(client)[0].startswith("Let me look into it")


def test_planner_on_holding_message_and_plan(client, svc, claude, monkeypatch):
    from app.agent import diagnosis, planner, state

    monkeypatch.setenv("PLANNER_ENABLED", "1")
    calls = []

    async def fake(contact, conv, reason="first message"):
        calls.append(reason)
        conv.diagnosis["plan"] = _plan()
        return conv.diagnosis["plan"]

    monkeypatch.setattr(planner, "make_plan", fake)
    claude([RuntimeError("down")] * 5)
    client.post("/webhooks/whatsapp", json=wa("my shower is cold"))
    t = texts(client)
    assert t[0] == "Let me look into it, one moment." and "only the shower" in t[1]
    conv = state.conversation("c_202")
    block = diagnosis.context_block(conv)
    assert block["plan"]["next_question"] in ("q_scope", "q_hot_water_use") and calls == ["first message"]


def test_replan_once_when_tenant_volunteers_something_else():
    from app.agent import diagnosis, planner, state

    conv = state.Conversation(contact_id="x")
    diagnosis.start(conv, "my shower is cold")
    conv.diagnosis["plan"] = _plan()
    before = dict(conv.diagnosis["answers"])
    conv.diagnosis["answers"]["q_radiators"] = "yes"  # not in the plan's questions
    assert planner.should_replan(conv, before)
    conv.diagnosis["replanned"] = True
    assert not planner.should_replan(conv, before)  # only once


def test_planner_failure_keeps_diagnosis_working(client, svc, claude, monkeypatch):
    from app.agent import planner

    monkeypatch.setenv("PLANNER_ENABLED", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    claude([RuntimeError("down")] * 5)
    client.post("/webhooks/whatsapp", json=wa("my shower is cold"))  # real make_plan fails without a key
    assert "only the shower" in texts(client)[-1]
    assert asyncio.run(planner.make_plan(None, type("C", (), {"diagnosis": {}, "error_code": None})())) is None
