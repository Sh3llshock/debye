"""Golden path over services + REST APIs (no phones, stubbed media/notify)."""
from datetime import timedelta
from pathlib import Path

import pytest

from app import rules, services
from app.config import now

DEMO = Path(__file__).resolve().parents[2] / "data" / "demo"
PDF = (DEMO / "invoice_RE-2026-1187.pdf").read_bytes()
JPG = (DEMO / "repair_done.jpg").read_bytes()


def _open_lena_case():
    lena = services.get_contact_by_phone("490000000001")  # WhatsApp sends no "+"
    assert lena and lena.id == "c_202"
    ctx = services.get_unit_context(lena.unit_id)
    assert ctx["property"]["address"].startswith("Musterstraße 12")
    boiler = ctx["assets"][0]
    assert services.find_open_case_for_asset(boiler["id"]) is None
    case = services.open_case(lena.id, "repair.heating", "urgent", "Heizung kalt", "alles kalt",
                              "F.28", boiler["id"])
    return lena, boiler, case


def test_golden_path(client):
    lena, boiler, case = _open_lena_case()
    cid = case.id
    assert case.status == "new" and case.unit_id == "unit_4b"

    # neighbour reports same central boiler → dedupe
    jonas = services.get_contact_by_phone("+490000000002")
    dup = services.find_open_case_for_asset(boiler["id"])
    assert dup.id == cid
    services.link_contact_to_case(cid, jonas.id, "affected")
    assert [c.id for c in services.get_case_contacts(cid)] == ["c_202", "c_203"]
    assert services.get_case(cid).partner_id is None
    m = services.log_message(lena.id, cid, "whatsapp", "in", "Heizung kalt", "wamid.T1", [])
    assert m.direction == "in" and services.message_seen("wamid.T1")

    ranking = services.rank_partners(cid)
    assert [r["partner_id"] for r in ranking][0] == "heizung-schmidt"
    assert len(ranking) == 3
    assert all(r["reasons"] for r in ranking)

    # consent gate
    with pytest.raises(rules.RuleViolation) as e:
        services.dispatch_job(cid, "heizung-schmidt")
    assert e.value.code == "consent_missing"

    services.record_consent(lena.id, "heizung-schmidt", cid,
                            ["name", "phone", "address", "photos"], "heating repair visit", "whatsapp")
    out = services.dispatch_job(cid, "heizung-schmidt")
    assert out["status"] == "requested"
    assert out["approval"]["required"] is False

    # partner page
    jobs = client.get("/api/partner/heizung-schmidt/jobs").json()
    assert [j["case_id"] for j in jobs] == [cid]
    r = client.post(f"/api/partner/heizung-schmidt/jobs/{cid}/accept")
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    tomorrow = (now() + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    slots = [{"start": tomorrow.isoformat(), "end": (tomorrow + timedelta(hours=2)).isoformat()},
             {"start": (tomorrow + timedelta(days=1, hours=6)).isoformat(),
              "end": (tomorrow + timedelta(days=1, hours=8)).isoformat()}]
    r = client.post(f"/api/partner/heizung-schmidt/jobs/{cid}/slots", json={"slots": slots})
    assert r.status_code == 200
    job = r.json()
    assert job["status"] == "slots_proposed"
    assert job["proposed_slots"][0]["label"] == "Morgen 8–10"
    assert job["tenant"] == {"name": "Lena Hoffmann", "phone": "+490000000001"}

    # tenant picks slot 1 on WhatsApp
    with pytest.raises(rules.RuleViolation):
        services.confirm_slot(cid, 2)
    res = services.confirm_slot(cid, 0)  # 0-based
    assert res["status"] == "scheduled"
    assert res["slot"]["label"] == "Morgen 8–10"

    # partner completes with photo + invoice
    r = client.post(f"/api/partner/heizung-schmidt/jobs/{cid}/complete",
                    data={"notes": "Zündelektrode getauscht, Kessel läuft"},
                    files={"photo": ("after.jpg", JPG, "image/jpeg"),
                           "invoice": ("RE-2026-1187.pdf", PDF, "application/pdf")})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "invoiced"
    assert job["price_check"]["result"] == "ok"
    inv = [d for d in job["documents"] if d["kind"] == "invoice"][0]
    assert inv["extracted"]["gross_eur"] == 237.41
    assert client.get(inv["url"]).content == PDF

    # tenant confirms → case closes with result payload
    result = services.tenant_confirms_fixed(cid, True)
    sj = result["service_job"]
    assert sj["status"] == "closed" and sj["invoice"]["number"] == "RE-2026-1187"
    assert sj["affected_units"] == ["unit_4b", "unit_2a"]
    assert sj["consent"]["channel"] == "whatsapp"

    # staff page
    detail = client.get(f"/api/staff/cases/{cid}").json()
    assert detail["status"] == "closed"
    assert detail["partner"]["partner_id"] == "heizung-schmidt"
    assert [r["contact_id"] for r in detail["reporters"]] == ["c_202", "c_203"]
    assert detail["result"]["service_job"]["case_id"] == cid
    assert detail["result"]["service_job"]["invoice"]["gross_eur"] == 237.41
    assert detail["messages"][0]["text"] == "Heizung kalt"
    kinds = [e["kind"] for e in detail["events"]]
    # services record each state-change event once
    assert kinds.count("job.sent") == 1 and kinds.count("case.closed") == 1
    for k in ["case.created", "case.linked_reporter", "partner.ranked", "consent.recorded",
              "job.sent", "job.accepted", "slot.proposed", "slot.confirmed", "job.completed",
              "invoice.checked", "case.closed"]:
        assert k in kinds, k
    unit = client.get("/api/staff/units/unit_4b").json()
    doc_kinds = {d["kind"] for d in unit["documents"]}
    assert {"invoice", "report"} <= doc_kinds
    assert unit["cases"][0]["case_id"] == cid
    # neighbour's unit sees the linked case too
    assert client.get("/api/staff/units/unit_2a").json()["cases"][0]["case_id"] == cid
    assert client.get("/api/staff/cases").json()[0]["case_id"] == cid


def test_partner_sees_only_consented_fields(client):
    lena, boiler, case = _open_lena_case()
    services.record_consent(lena.id, "heizung-schmidt", case.id, ["address"], "repair", "whatsapp")
    services.dispatch_job(case.id, "heizung-schmidt")
    job = client.get(f"/api/partner/heizung-schmidt/jobs/{case.id}").json()
    assert job["address"].startswith("Musterstraße")
    assert job["tenant"] is None
    # another partner can't see it
    assert client.get(f"/api/partner/waerme-wagner/jobs/{case.id}").status_code == 404


def test_approval_flow(client):
    lena, boiler, case = _open_lena_case()
    client.post("/demo/trigger/expensive_repair", json={"case_id": case.id})
    services.record_consent(lena.id, "heizung-schmidt", case.id, ["name", "address"], "repair", "whatsapp")
    with pytest.raises(rules.RuleViolation) as e:
        services.dispatch_job(case.id, "heizung-schmidt")
    assert e.value.code == "approval_required"
    d = client.get(f"/api/staff/cases/{case.id}").json()
    assert d["status"] == "awaiting_approval" and d["approval"]["required"] is True
    d = client.post(f"/api/staff/cases/{case.id}/approve").json()
    assert d["status"] == "requested"
    assert d["partner"]["partner_id"] == "heizung-schmidt"


def test_decline_reranks(client):
    lena, boiler, case = _open_lena_case()
    services.rank_partners(case.id)
    services.record_consent(lena.id, "heizung-schmidt", case.id, ["address"], "repair", "whatsapp")
    services.dispatch_job(case.id, "heizung-schmidt")
    r = client.post(f"/api/partner/heizung-schmidt/jobs/{case.id}/decline", json={"reason": "krank"})
    assert r.json()["status"] == "declined"
    ranking = services.rank_partners(case.id)
    assert "heizung-schmidt" not in [p["partner_id"] for p in ranking]


def test_demo_triggers_and_reset(client):
    r = client.post("/demo/trigger/tenant_report",
                    json={"media_ids": [f"local:{DEMO / 'boiler_display_F28.jpg'}"]})
    cid = r.json()["case_id"]
    assert r.json()["ranking"][0]["partner_id"] == "heizung-schmidt"
    r = client.post("/demo/trigger/neighbour_report", json={})
    assert r.json()["duplicate_of"] == cid
    r = client.post("/demo/trigger/consent", json={"case_id": cid})
    assert r.json()["dispatched"]["status"] == "requested"
    detail = client.get(f"/api/staff/cases/{cid}").json()
    assert detail["messages"] and detail["zero_forms"]["tenant_inputs"]
    assert any(d["kind"] == "photo" for d in detail["documents"])
    assert client.post("/demo/skip-to-tomorrow").json()["ok"]
    assert client.post("/demo/trigger/nope").status_code == 404
    client.post("/demo/reset")
    assert client.get("/api/staff/cases").json() == []
