"""Feature 4: the partner asks the tenant a question (needs_info) + just-in-time access details."""
import asyncio
from datetime import timedelta

import pytest

from app import services
from app.config import advance_clock, now

ALL_FIELDS = ["name", "phone", "address", "unit_floor", "photos", "access_details"]


@pytest.fixture()
def tenant_texts(monkeypatch):
    from app.agent import outbound
    sent = []

    async def text(contact, case_id, body, *a, **kw):
        sent.append(body)
    monkeypatch.setattr(outbound, "text", text)
    return sent


def _scheduled_case(client, fields=ALL_FIELDS):
    luka = services.get_contact_by_phone("+490000000001")
    boiler = services.get_unit_context(luka.unit_id)["assets"][0]
    case = services.open_case(luka.id, "repair.heating", "urgent", "Heizung kalt", "alles kalt", "F.28", boiler["id"])
    cid = case.id
    services.record_consent(luka.id, "heizung-schmidt", cid, fields, "heating repair visit", "whatsapp")
    try:
        services.dispatch_job(cid, "heizung-schmidt")
    except Exception:
        services.approve_case(cid)
    assert client.post(f"/api/partner/heizung-schmidt/jobs/{cid}/accept").status_code == 200
    tom = next(t for t in client.get("/api/partner/heizung-schmidt/technicians").json() if t["tech_id"] == "tech_tom")
    slot = next(s for s in tom["free_slots"] if s["start"][:10] > now().date().isoformat())  # a later day
    r = client.post(f"/api/partner/heizung-schmidt/jobs/{cid}/slots", json={"tech_id": "tech_tom", "slots": [slot]})
    assert r.status_code == 200, r.text
    services.confirm_slot(cid, 1)
    assert client.post(f"/api/tech/tech_tom/jobs/{cid}/confirm").status_code == 200
    assert services.get_case(cid).status == "scheduled"
    return luka, cid, slot


def test_partner_question_reaches_tenant_and_answer_comes_back(client, tenant_texts):
    luka, cid, _ = _scheduled_case(client)
    url = f"/api/partner/heizung-schmidt/jobs/{cid}/question"
    assert client.post(url, json={"text": "   "}).status_code == 422
    assert client.post(f"/api/partner/waerme-wagner/jobs/{cid}/question", json={"text": "Hi?"}).status_code == 404

    r = client.post(url, json={"text": "Is there parking nearby?"})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["open_question"]["text"] == "Is there parking nearby?"
    assert job["questions"][0]["answer"] is None
    assert tenant_texts[-1] == "Tom from Heizung Schmidt GmbH asks: Is there parking nearby?"
    assert client.post(url, json={"text": "And the stairs?"}).status_code == 409  # one open question at a time

    # the tenant's next free-text reply is the answer, not a new agent turn
    from app import router
    from app.agent import loop, state as st

    async def no_agent(*a, **kw):  # pragma: no cover - must not be reached
        raise AssertionError("agent turn instead of the open question")
    st.conversation(luka.id).case_id = cid
    loop_turn = loop.run_tenant_turn
    loop.run_tenant_turn = no_agent
    try:
        assert asyncio.run(router.process_text(luka, "Yes, visitor spaces in the courtyard", [])) is False
    finally:
        loop.run_tenant_turn = loop_turn
    assert tenant_texts[-1] == "Thanks, I've passed that on to Heizung Schmidt GmbH."

    job = client.get(f"/api/partner/heizung-schmidt/jobs/{cid}").json()
    assert job["open_question"] is None
    assert job["questions"][0]["answer"] == "Yes, visitor spaces in the courtyard"
    kinds = [e["kind"] for e in job["events"]]
    assert "job.needs_info" in kinds and "job.info_provided" in kinds
    staff = client.get(f"/api/staff/cases/{cid}").json()
    assert {"job.needs_info", "job.info_provided"} <= {e["kind"] for e in staff["events"]}

    # without an open question the router doesn't touch the reply
    from app.agent import flow
    assert asyncio.run(flow.answer_open_question(luka, st.conversation(luka.id), "thanks")) is False


def test_access_details_released_only_on_the_visit_day(client):
    _, cid, slot = _scheduled_case(client)
    url = f"/api/partner/heizung-schmidt/jobs/{cid}"
    before = client.get(url).json()["access"]
    assert before == {"consented": True, "released": False, "available_on": slot["start"][:10]}

    while now().date().isoformat() < slot["start"][:10]:
        advance_clock(timedelta(days=1))
    on_day = client.get(url).json()
    assert on_day["access"]["released"] is True
    assert on_day["access"]["key_safe_code"] == "4711" and on_day["access"]["parking_note"]
    again = client.get(url).json()
    assert [e["kind"] for e in again["events"]].count("access.released") == 1
    # the technician's phone page gets them too
    assert client.get(f"/api/tech/tech_tom/jobs/{cid}").json()["access"]["released"] is True

    advance_clock(timedelta(days=1))  # the day after: held back again
    assert client.get(url).json()["access"]["released"] is False


def test_access_details_need_consent(client):
    _, cid, slot = _scheduled_case(client, fields=["name", "phone", "address"])
    while now().date().isoformat() < slot["start"][:10]:
        advance_clock(timedelta(days=1))
    acc = client.get(f"/api/partner/heizung-schmidt/jobs/{cid}").json()["access"]
    assert acc == {"consented": False, "released": False}
    assert "key_safe_code" not in acc


def test_seeded_access_and_manifest_context(client):
    from app.db import get_session
    from app.models import Unit
    with get_session() as s:
        assert s.get(Unit, "unit_4b").access["key_safe_code"] == "4711"
    m = services.get_partner_manifest("heizung-schmidt")
    ctx = next(c for c in m.required_context if c.key == "access_details")
    assert ctx.source == "unit.access" and ctx.pii and ctx.consent_required
