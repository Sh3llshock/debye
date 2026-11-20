from datetime import datetime

from agent_stubs import oa_call

from app.agent.priority import enforce_priority

NOV = datetime(2026, 11, 20)
JUL = datetime(2026, 7, 15)


def test_heating_season_forces_urgent():
    assert enforce_priority("normal", "repair.heating", "Thermostat klemmt", when=NOV) == (
        "urgent", "heating fault during the heating season (Nov–Mar)")
    assert enforce_priority("normal", "repair.heating", "", when=datetime(2027, 3, 31))[0] == "urgent"


def test_no_heat_or_hot_water_urgent_all_year():
    for text in ("Kein Warmwasser seit gestern", "Die Heizung ist aus", "Überall kalt", "Wasser bleibt kalt",
                 "keine Heizung"):
        assert enforce_priority("normal", "repair.plumbing", text, when=JUL)[0] == "urgent", text


def test_summer_minor_issue_stays_normal_and_never_lowered():
    assert enforce_priority("normal", "repair.heating", "Heizkörper gluckert", when=JUL) == ("normal", None)
    assert enforce_priority("emergency", "repair.heating", "Gasgeruch", when=JUL) == ("emergency", None)
    assert enforce_priority("urgent", "repair.heating", "", when=JUL) == ("urgent", None)
    assert enforce_priority("bogus", "repair.heating", "", when=NOV)[0] == "urgent"


def test_model_normal_overridden_before_open_case(client, svc, gpt, monkeypatch):
    import app.agent.priority as pr

    monkeypatch.setattr(pr, "_now", lambda: NOV)
    gpt([
        [oa_call("open_case", summary="Heizung kalt", symptoms="Heizung kalt seit heute Morgen",
                 error_code=None, priority="normal")],
        [oa_call("reply", text="Ich kümmere mich.")],
        "",
    ])
    client.post("/webhooks/whatsapp", json={"entry": [{"changes": [{"value": {"messages": [{
        "from": "490000000001", "id": "wamid.prio1", "type": "text", "text": {"body": "Heizung kalt"}}]}}]}]})
    assert svc.cases["case_0001"]["priority"] == "urgent"
