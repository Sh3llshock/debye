"""Feature 3: API transport (signed orders) + the partner events webhook with lifecycle checks."""
import base64
import json
from pathlib import Path

import httpx
import pytest

from app import notify, rules, services
from app.partners import transport

DEMO = Path(__file__).resolve().parents[2] / "data" / "demo"
PDF = (DEMO / "invoice_RE-2026-1187.pdf").read_bytes()
SECRET = "test-partner-secret"
PID = "heiztechnik-api"
INVOICE = {
    "invoice_number": "RE-2026-1187", "date": "2026-11-21",
    "net_eur": 199.50, "vat_eur": 37.91, "gross_eur": 237.41,
    "line_items": [
        {"desc": "Anfahrtspauschale (Rahmenvertrag)", "qty": 1, "unit_price": 89.00},
        {"desc": "Arbeitszeit Heizungstechniker, Std.", "qty": 1, "unit_price": 72.00},
        {"desc": "Zündelektrode Vaillant ecoTEC plus (0020107800)", "qty": 1, "unit_price": 38.50},
    ],
}


@pytest.fixture()
def partner_system(monkeypatch):
    """Stands in for scripts/fake_partner.py: records the orders and checks their signature."""
    monkeypatch.setenv("PARTNER_API_SECRET", SECRET)
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raw = request.read()
        assert request.headers["X-Centrix-Signature"] == transport.sign(raw, SECRET)
        sent.append({"url": str(request.url), "body": json.loads(raw)})
        return httpx.Response(200, json={"partner_order_id": "HT-0001", "status": "received"})

    monkeypatch.setattr(transport, "client_factory",
                        lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    tenant_msgs: list = []

    async def spy(case_id, event, data):
        tenant_msgs.append((event, data))

    monkeypatch.setattr(notify, "notify_tenant", spy)
    return sent, tenant_msgs


def _case_dispatched_to_api(consent_fields=("address",)):
    luka = services.get_contact_by_phone("+490000000001")
    boiler = services.get_unit_context(luka.unit_id)["assets"][0]
    case = services.open_case(luka.id, "repair.heating", "urgent", "Heizung kalt", "alles kalt",
                              "F.28", boiler["id"])
    services.record_consent(luka.id, PID, case.id, list(consent_fields), "repair", "whatsapp")
    with pytest.raises(rules.RuleViolation):
        services.dispatch_job(case.id, PID)
    services.approve_case(case.id, staff_name="Anna Becker")
    return case.id


def _post(client, body: dict, secret: str = SECRET, pid: str = PID):
    raw = json.dumps(body).encode()
    return client.post(f"/api/partners/{pid}/events", content=raw,
                       headers={"Content-Type": "application/json",
                                "X-Centrix-Signature": transport.sign(raw, secret)})


def _ev(cid: str, status: str, data=None, documents=None) -> dict:
    return {"order_ref": transport.order_ref(cid), "partner_id": PID, "status": status,
            "at": "2026-11-21T09:00:00+01:00", "data": data or {}, "documents": documents or []}


def test_order_is_signed_and_carries_only_consented_context(client, partner_system):
    sent, _ = partner_system
    cid = _case_dispatched_to_api(consent_fields=("address",))
    assert len(sent) == 1 and sent[0]["url"] == "http://localhost:8100/orders"
    body = sent[0]["body"]
    assert body["order_ref"] == f"ord_{cid}" and body["partner_id"] == PID
    assert body["trade"] == "heating" and body["priority"] == "urgent"
    assert body["cost_cap_eur"] == services.get_case(cid).estimated_cost_eur
    ctx = body["context"]
    assert ctx["address"].startswith("Musterstraße 12")
    assert ctx["error_code"] == "F.28" and ctx["asset"]["make"] == "Vaillant"
    assert "tenant_name" not in ctx and "tenant_phone" not in ctx  # not consented
    assert body["consent"]["data_shared"] == ["address"] and body["consent"]["channel"] == "whatsapp"
    assert len(body["slot_hints"]) == 2
    case = services.get_case(cid)
    assert case.status == "requested"
    assert case.data["partner_order"]["partner_order_id"] == "HT-0001"


def test_portal_transport_unchanged(client, partner_system):
    sent, _ = partner_system
    luka = services.get_contact_by_phone("+490000000001")
    boiler = services.get_unit_context(luka.unit_id)["assets"][0]
    case = services.open_case(luka.id, "repair.heating", "urgent", "x", "x", "F.28", boiler["id"])
    services.record_consent(luka.id, "heizung-schmidt", case.id, ["address"], "repair", "whatsapp")
    with pytest.raises(rules.RuleViolation):
        services.dispatch_job(case.id, "heizung-schmidt")
    services.approve_case(case.id)
    assert sent == [] and "partner_order" not in services.get_case(case.id).data


def test_unreachable_partner_is_recorded_not_raised(client, monkeypatch):
    monkeypatch.setenv("PARTNER_API_SECRET", SECRET)

    def down(request):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(transport, "client_factory",
                        lambda: httpx.Client(transport=httpx.MockTransport(down)))
    cid = _case_dispatched_to_api()
    case = services.get_case(cid)
    assert case.status == "requested" and "unreachable" in case.data["partner_order"]["error"]
    from sqlmodel import select
    from app.db import get_session
    from app.models import CaseEvent
    with get_session() as s:
        kinds = [e.kind for e in s.exec(select(CaseEvent).where(CaseEvent.case_id == cid)).all()]
    assert "job.send_failed" in kinds


def test_signature_checked(client, partner_system):
    cid = _case_dispatched_to_api()
    assert _post(client, _ev(cid, "accepted"), secret="wrong").status_code == 401
    raw = json.dumps(_ev(cid, "accepted")).encode()
    r = client.post(f"/api/partners/{PID}/events", content=raw,
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 401
    assert services.get_case(cid).status == "requested"


def test_bad_shape_and_unknown_order(client, partner_system):
    cid = _case_dispatched_to_api()
    assert _post(client, {"order_ref": "x"}).status_code == 422
    assert _post(client, {**_ev(cid, "accepted"), "status": "teleported"}).status_code == 422
    assert _post(client, {**_ev(cid, "accepted"), "order_ref": "ord_nope"}).status_code == 404
    assert _post(client, {**_ev(cid, "accepted"), "partner_id": "heizung-schmidt"}).status_code == 422


def test_invalid_transition_rejected(client, partner_system):
    cid = _case_dispatched_to_api()
    r = _post(client, _ev(cid, "completed"))
    assert r.status_code == 409 and "requested → completed" in r.json()["detail"]
    assert _post(client, _ev(cid, "invoiced")).status_code == 409
    assert services.get_case(cid).status == "requested"


def test_happy_path_through_webhook_ends_invoiced_with_price_check(client, partner_system):
    _, tenant = partner_system
    cid = _case_dispatched_to_api(consent_fields=("address", "name", "phone"))
    r = _post(client, _ev(cid, "accepted"))
    assert r.status_code == 200 and r.json()["case_status"] == "accepted"
    hints = transport.slot_hints()
    r = _post(client, _ev(cid, "accepted", {"slots": hints}))
    assert r.status_code == 200 and r.json()["case_status"] == "slots_proposed"
    assert [e for e, _ in tenant] == ["job_accepted", "slots_proposed"]
    # the tenant picks a slot on WhatsApp (no technician roster → straight to scheduled)
    services.confirm_slot(cid, 1)
    assert services.get_case(cid).status == "scheduled"
    assert _post(client, _ev(cid, "in_progress")).json()["status"] == "in_progress"
    doc = {"kind": "invoice", "filename": "invoice_RE-2026-1187.pdf", "mime": "application/pdf",
           "base64": base64.b64encode(PDF).decode()}
    r = _post(client, _ev(cid, "completed", {"notes": "Zündelektrode getauscht", "invoice": INVOICE}, [doc]))
    assert r.status_code == 200, r.text
    assert r.json()["case_status"] == "invoiced" and r.json()["status"] == "invoiced"
    case = services.get_case(cid)
    assert case.data["price_check"]["result"] == "ok"
    assert case.data["invoice"]["gross_eur"] == 237.41
    assert case.data["partner_order"]["status"] == "invoiced"
    # the same partner-page view works for an API partner
    job = client.get(f"/api/partner/{PID}/jobs/{cid}").json()
    assert job["status"] == "invoiced" and any(d["kind"] == "invoice" for d in job["documents"])
    # no going back
    assert _post(client, _ev(cid, "accepted")).status_code == 409


def test_decline_and_needs_info_from_anywhere(client, partner_system):
    cid = _case_dispatched_to_api()
    r = _post(client, _ev(cid, "needs_info", {"question": "Is there parking nearby?"}))
    assert r.status_code == 200
    assert services.get_case(cid).data["open_question"]["text"] == "Is there parking nearby?"
    assert _post(client, _ev(cid, "declined", {"reason": "no capacity"})).status_code == 200
    case = services.get_case(cid)
    assert PID in case.data["declined_by"] and case.partner_id != PID


def test_document_url_must_be_on_partner_host(client, partner_system):
    cid = _case_dispatched_to_api()
    _post(client, _ev(cid, "accepted"))
    _post(client, _ev(cid, "accepted", {"slots": transport.slot_hints()}))
    services.confirm_slot(cid, 1)
    doc = {"kind": "invoice", "filename": "x.pdf", "mime": "application/pdf",
           "url": "http://169.254.169.254/latest/meta-data"}
    r = _post(client, _ev(cid, "completed", {"notes": "done"}, [doc]))
    assert r.status_code == 422
