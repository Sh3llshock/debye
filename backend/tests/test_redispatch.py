"""Feature 2: decline or no response → next partner (redispatch + SLA)."""
from datetime import timedelta

import pytest

from app import rules, services
from app.config import advance_clock


def _luka_case():
    luka = services.get_contact_by_phone("+490000000001")
    boiler = services.get_unit_context(luka.unit_id)["assets"][0]
    case = services.open_case(luka.id, "repair.heating", "urgent", "Heizung kalt", "alles kalt",
                              "F.28", boiler["id"])
    return luka, case


def _sent_to(case_id: str, partner_id: str, luka) -> None:
    services.record_consent(luka.id, partner_id, case_id, ["name", "phone", "address"], "repair", "whatsapp")
    with pytest.raises(rules.RuleViolation):
        services.dispatch_job(case_id, partner_id)
    services.approve_case(case_id)
    assert services.get_case(case_id).status == "requested"


def _spy(monkeypatch):
    from app import notify
    sent = []

    async def spy(case_id, event, data):
        sent.append((event, data))
    monkeypatch.setattr(notify, "notify_tenant", spy)
    return sent


def test_decline_asks_tenant_consent_for_next_partner(client, monkeypatch):
    sent = _spy(monkeypatch)
    luka, case = _luka_case()
    first, second = [r["partner_id"] for r in services.rank_partners(case.id)][:2]
    _sent_to(case.id, first, luka)

    r = client.post(f"/api/partner/{first}/jobs/{case.id}/decline", json={"reason": "fully booked"})
    assert r.status_code == 200
    c = services.get_case(case.id)
    assert c.status == "awaiting_consent" and c.data["pending_partner_id"] == second
    assert c.data["redispatch"]["outcome"] == "needs_consent"
    assert sent[-1][0] == "partner_declined" and sent[-1][1]["next_partner_id"] == second
    # the declined job left the first partner's inbox; the staff timeline shows both
    assert case.id not in [j["case_id"] for j in client.get(f"/api/partner/{first}/jobs").json()]
    kinds = [e["kind"] for e in client.get(f"/api/staff/cases/{case.id}").json()["events"]]
    assert "job.declined" in kinds and "partner.redispatched" in kinds

    # tenant agrees → staff approve the new partner → job goes out
    services.record_consent(luka.id, second, case.id, ["name", "phone", "address"], "repair", "whatsapp")
    with pytest.raises(rules.RuleViolation):
        services.dispatch_job(case.id, second)
    services.approve_case(case.id)
    c = services.get_case(case.id)
    assert c.status == "requested" and c.partner_id == second


def test_decline_without_new_consent_goes_to_approval(client, monkeypatch):
    _spy(monkeypatch)
    luka, case = _luka_case()
    first, second = [r["partner_id"] for r in services.rank_partners(case.id)][:2]
    services.record_consent(luka.id, second, case.id, ["name", "phone", "address", "tenant_name", "tenant_phone", "unit_floor", "access_details", "photos"], "repair", "whatsapp")
    _sent_to(case.id, first, luka)
    services.partner_decline(case.id, first, "sick")
    c = services.get_case(case.id)
    assert c.data["redispatch"]["outcome"] == "approval_pending"
    assert c.status == "approval_pending" and c.data["pending_partner_id"] == second
    assert services.approve_case(case.id)["dispatched"]["partner_id"] == second


def test_flow_message_to_tenant(client):
    """The real notify path sends one short message naming both companies."""
    import asyncio
    from app import notify
    from app.agent import outbound
    luka, case = _luka_case()
    first, second = [r for r in services.rank_partners(case.id)][:2]
    _sent_to(case.id, first["partner_id"], luka)
    services.partner_decline(case.id, first["partner_id"], "fully booked")
    texts = []

    async def fake_buttons(contact, case_id, text, options, **kw):
        texts.append(text)

    async def fake_text(contact, case_id, text, **kw):
        texts.append(text)
    import pytest as _pt
    mp = _pt.MonkeyPatch()
    mp.setattr(outbound, "buttons", fake_buttons)
    mp.setattr(outbound, "text", fake_text)
    try:
        asyncio.run(notify.notify_tenant(case.id, "partner_declined", services.get_case(case.id).data["redispatch"]))
    finally:
        mp.undo()
    assert len(texts) == 1
    assert first["name"] in texts[0] and second["name"] in texts[0]


def test_no_partner_left_needs_staff(client, monkeypatch):
    _spy(monkeypatch)
    luka, case = _luka_case()
    ranked = [r["partner_id"] for r in services.rank_partners(case.id)]
    services.record_consent(luka.id, ranked[0], case.id, ["address"], "repair", "whatsapp")
    with services.get_session() if hasattr(services, "get_session") else _nullctx() as s:
        c = s.get(services.Case, case.id)
        others = [p.id for p in s.exec(services.select(services.Partner)).all() if p.id != ranked[0]]
        c.data = {**c.data, "declined_by": others}  # everyone else already said no
        s.add(c)
        s.commit()
    _sent_to(case.id, ranked[0], luka)
    services.partner_decline(case.id, ranked[0], "no capacity")
    c = services.get_case(case.id)
    assert c.status == "needs_staff" and c.data["redispatch"]["outcome"] == "needs_staff"
    assert any(e["kind"] == "case.needs_staff" for e in client.get(f"/api/staff/cases/{case.id}").json()["events"])


def test_sla_timeout_redispatches(client, monkeypatch):
    _spy(monkeypatch)
    luka, case = _luka_case()
    first = services.rank_partners(case.id)[0]["partner_id"]
    _sent_to(case.id, first, luka)
    sla = services.get_case(case.id).data["sla"]
    assert sla["hours"] > 0  # urgent → urgent_response_hours from the manifest
    assert services.check_sla() == []
    advance_clock(timedelta(hours=sla["hours"] + 0.1))
    r = client.post("/demo/skip-to-tomorrow").json()
    assert case.id in [x["case_id"] for x in r["redispatched"]]
    c = services.get_case(case.id)
    assert first in c.data["declined_by"] and c.partner_id != first
    ev = [e for e in client.get(f"/api/staff/cases/{case.id}").json()["events"] if e["kind"] == "job.declined"]
    assert "no response within" in ev[-1]["summary"]


class _nullctx:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False
