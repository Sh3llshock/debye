"""Feature 8: a second partner type through the same spec (example-fibre, kind sell, tenant.move_in)."""
import asyncio
import json

import httpx
import pytest
from sqlmodel import select

from app import services, triggers
from app.agent import outbound
from app.db import get_session
from app.models import Contract
from app.partners import transport

SECRET = "test-fibre-secret"
PID = "example-fibre"


@pytest.fixture()
def fibre(monkeypatch):
    monkeypatch.setenv("FIBRE_SECRET", SECRET)
    orders: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raw = request.read()
        assert request.headers["X-Centrix-Signature"] == transport.sign(raw, SECRET)
        orders.append({"url": str(request.url), "body": json.loads(raw)})
        return httpx.Response(200, json={"partner_order_id": "EF-42", "status": "received"})

    monkeypatch.setattr(transport, "client_factory",
                        lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    sent: list[tuple] = []

    async def fake_buttons(contact, case_id, body, options):
        sent.append(("buttons", case_id, body, [o.id for o in options], [o.title for o in options]))

    async def fake_text(contact, case_id, body):
        sent.append(("text", case_id, body))

    monkeypatch.setattr(outbound, "buttons", fake_buttons)
    monkeypatch.setattr(outbound, "text", fake_text)
    return orders, sent


def _event(client, cid, status, data=None, documents=None):
    body = {"order_ref": transport.order_ref(cid), "partner_id": PID, "status": status,
            "data": data or {}, "documents": documents or []}
    raw = json.dumps(body).encode()
    return client.post(f"/api/partners/{PID}/events", content=raw,
                       headers={"Content-Type": "application/json",
                                "X-Centrix-Signature": transport.sign(raw, SECRET)})


def _press(button_id: str):
    from app import router
    luka = services.get_contact_by_phone("+490000000001")
    return asyncio.run(router.handle_button(luka, button_id))


def test_move_in_offer_consent_order_active_contract(client, fibre):
    orders, sent = fibre
    r = client.post("/demo/trigger/move_in", json={"unit_id": "unit_4b", "move_in_date": "2026-12-01"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert len(res["opened"]) == 1
    cid = res["opened"][0]
    case = services.get_case(cid)
    assert case.type == "telecom.internet" and case.status == "offered" and case.partner_id == PID
    assert case.reporter_contact_id == "c_202"

    # offer buttons straight from the manifest
    kind, _, body, ids, titles = sent[-1]
    assert kind == "buttons" and "Example Fibre GmbH" in body
    assert titles == ["Fibre 250 · €29.99/month", "Fibre 500 · €34.99/month", "No thanks"]
    assert ids == [f"offer:{cid}:fibre-250", f"offer:{cid}:fibre-500", f"offer:{cid}:none"]

    # pick → consent question for the manifest's consent fields
    assert _press(f"offer:{cid}:fibre-500")
    kind, _, body, ids, _ = sent[-1]
    assert kind == "buttons" and "your name, your address and your move-in date" in body
    assert services.get_case(cid).data["sell"]["chosen"]["offer_id"] == "fibre-500"
    assert orders == []  # nothing leaves centrix before consent

    # consent → signed order through the API transport (feature 3)
    assert _press(f"sellconsent:{cid}:yes")
    assert len(orders) == 1 and orders[0]["url"] == "http://localhost:8101/orders"
    order = orders[0]["body"]
    assert order["offer_id"] == "fibre-500"
    assert order["context"]["name"] == "Luka" and order["context"]["move_in_date"] == "2026-12-01"
    assert order["context"]["address"].startswith("Musterstraße 12")
    assert set(order["consent"]["data_shared"]) == {"name", "address", "move_in_date"}
    assert "slot_hints" not in order
    assert services.get_case(cid).status == "ordered"

    # sell lifecycle via the events webhook: accepted → signed → active
    assert _event(client, cid, "signed").status_code == 409  # offered → signed skips accepted
    assert _event(client, cid, "accepted").json()["case_status"] == "accepted"
    r = _event(client, cid, "signed", {"product": "Fibre 500"},
               [{"kind": "contract", "filename": "contract_EF-42.pdf", "mime": "application/pdf",
                 "base64": "JVBERi0xLjQK"}])
    assert r.status_code == 200 and r.json()["status"] == "signed"
    r = _event(client, cid, "active", {"start": "2026-12-01", "product": "Fibre 500", "monthly_price_eur": 34.99})
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert "active from 2026-12-01" in sent[-1][2]

    # the result on the unit, in reltix's exact shape
    with get_session() as s:
        row = s.exec(select(Contract).where(Contract.unit_id == "unit_4b", Contract.type == "service")).one()
        consent_given = row.data["service_contract"]["consent"]["given_at"]
    expected = {
        "unit_id": "unit_4b", "contact_id": "c_202",
        "service_contract": {"partner": "Example Fibre GmbH", "category": "telecom.internet",
                             "product": "Fibre 500", "status": "active", "start": "2026-12-01",
                             "monthly_price_eur": 34.99,
                             "consent": {"data_shared": ["name", "address", "move_in_date"],
                                         "given_at": consent_given, "channel": "whatsapp"}},
    }
    assert services.get_case(cid).data["result"] == expected
    assert {k: row.data[k] for k in ("unit_id", "contact_id", "service_contract")} == expected
    unit = client.get("/api/staff/units/unit_4b").json()
    assert unit["service_contracts"][0]["service_contract"] == expected["service_contract"]
    assert {"service_contract", "service_record"} <= {d["kind"] for d in unit["documents"]}
    assert services.get_case(cid).status == "closed"
    assert _event(client, cid, "accepted").status_code == 409


def test_not_eligible_without_fibre(client, fibre):
    """prop_41 has no fibre: eligibility filters the partner out, no case, no message."""
    orders, sent = fibre
    with get_session() as s:
        from app.models import Unit
        unit = s.exec(select(Unit).where(Unit.property_id == "prop_41")).first()
    if unit is None:
        pytest.skip("no unit on prop_41 in the seed")
    res = client.post("/api/centrix/events", json={"type": "tenant.move_in", "unit_id": unit.id,
                                                   "contact_id": "c_202"}).json()
    assert res["opened"] == []
    assert any("fibre_available" in " ".join(x["reasons"]) for x in res["skipped"])
    assert sent == []


def test_no_thanks_and_idempotent(client, fibre):
    orders, sent = fibre
    cid = client.post("/api/centrix/events", json={"type": "tenant.move_in", "unit_id": "unit_4b"}).json()["opened"][0]
    again = client.post("/api/centrix/events", json={"type": "tenant.move_in", "unit_id": "unit_4b"}).json()
    assert again["opened"] == [] and again["skipped"][0]["reasons"] == ["offer already open"]
    assert _press(f"offer:{cid}:none")
    assert services.get_case(cid).status == "closed" and orders == []
    assert client.post("/api/centrix/events", json={"type": "tenant.boom", "unit_id": "unit_4b"}).status_code == 422


def test_sell_partner_not_in_repair_ranking(client):
    luka = services.get_contact_by_phone("+490000000001")
    boiler = services.get_unit_context(luka.unit_id)["assets"][0]
    case = services.open_case(luka.id, "repair.heating", "urgent", "x", "x", "F.28", boiler["id"])
    assert PID not in [r["partner_id"] for r in services.rank_partners(case.id)]
    assert triggers.KNOWN_EVENTS == {"tenant.move_in"}
