"""Golden path over services + REST APIs (no phones, stubbed media/notify)."""
from datetime import timedelta
from pathlib import Path

import pytest

from app import rules, services
from app.config import now

DEMO = Path(__file__).resolve().parents[2] / "data" / "demo"
PDF = (DEMO / "invoice_RE-2026-1187.pdf").read_bytes()
JPG = (DEMO / "repair_done.jpg").read_bytes()


def _open_luka_case():
    luka = services.get_contact_by_phone("490000000001")  # WhatsApp sends no "+"
    assert luka and luka.id == "c_202"
    ctx = services.get_unit_context(luka.unit_id)
    assert ctx["property"]["address"].startswith("Musterstraße 12")
    boiler = ctx["assets"][0]
    assert services.find_open_case_for_asset(boiler["id"]) is None
    case = services.open_case(luka.id, "repair.heating", "urgent", "Heizung kalt", "alles kalt",
                              "F.28", boiler["id"])
    return luka, boiler, case


DEMO_INVOICE = {  # numbers of data/demo/invoice_RE-2026-1187.pdf
    "invoice_number": "RE-2026-1187", "date": "2026-11-21",
    "net_eur": 199.50, "vat_eur": 37.91, "gross_eur": 237.41,
    "line_items": [
        {"desc": "Anfahrtspauschale (Rahmenvertrag)", "qty": 1, "unit_price": 89.00},
        {"desc": "Arbeitszeit Heizungstechniker, Std.", "qty": 1, "unit_price": 72.00},
        {"desc": "Zündelektrode Vaillant ecoTEC plus (0020107800)", "qty": 1, "unit_price": 38.50},
    ],
    "labour_hours": 1.0,
}


@pytest.fixture(autouse=True)
def _demo_invoice(monkeypatch):
    """Deterministic extraction, independent of API keys and of media.py's own fallback."""
    from app import media

    async def fake_extract(path: str) -> dict:
        return dict(DEMO_INVOICE)

    monkeypatch.setattr(media, "extract_invoice", fake_extract)


def test_golden_path(client):
    luka, boiler, case = _open_luka_case()
    cid = case.id
    assert case.status == "new" and case.unit_id == "unit_4b"

    # neighbour reports same central boiler → dedupe
    jonas = services.get_contact_by_phone("+490000000002")
    dup = services.find_open_case_for_asset(boiler["id"])
    assert dup.id == cid
    services.link_contact_to_case(cid, jonas.id, "affected")
    assert [c.id for c in services.get_case_contacts(cid)] == ["c_202", "c_203"]
    assert services.get_case(cid).partner_id is None
    m = services.log_message(luka.id, cid, "whatsapp", "in", "Heizung kalt", "wamid.T1", [])
    assert m.direction == "in" and services.message_seen("wamid.T1")

    ranking = services.rank_partners(cid)
    assert [r["partner_id"] for r in ranking][0] == "heizung-schmidt"
    assert len(ranking) == 3
    assert all(r["reasons"] for r in ranking)

    # consent gate
    with pytest.raises(rules.RuleViolation) as e:
        services.dispatch_job(cid, "heizung-schmidt")
    assert e.value.code == "consent_missing"

    services.record_consent(luka.id, "heizung-schmidt", cid,
                            ["name", "phone", "address", "photos"], "heating repair visit", "whatsapp")
    out = services.dispatch_job(cid, "heizung-schmidt")
    assert out["status"] == "requested"
    assert out["approval"]["required"] is False

    # partner page
    jobs = client.get("/api/partner/heizung-schmidt/jobs").json()
    assert [j["case_id"] for j in jobs] == [cid]
    r = client.post(f"/api/partner/heizung-schmidt/jobs/{cid}/accept")
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    # dispatcher picks a technician and proposes slots from that technician's free time
    techs = client.get("/api/partner/heizung-schmidt/technicians").json()
    assert [t["name"] for t in techs] == ["Ali Yilmaz", "Jana Krüger", "Tom Schmidt"]
    tom = next(t for t in techs if t["tech_id"] == "tech_tom")
    tomorrow = (now() + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    t_0810 = {"start": tomorrow.isoformat(timespec="seconds"),
              "end": (tomorrow + timedelta(hours=2)).isoformat(timespec="seconds")}
    t_1012 = {"start": (tomorrow + timedelta(hours=2)).isoformat(timespec="seconds"),
              "end": (tomorrow + timedelta(hours=4)).isoformat(timespec="seconds")}
    assert t_0810 in tom["free_slots"] and t_1012 not in tom["free_slots"]  # Tom busy tomorrow 10–12
    slots = [t_0810, tom["free_slots"][1]]
    url = f"/api/partner/heizung-schmidt/jobs/{cid}/slots"
    assert client.post(url, json={"tech_id": "tech_tom", "slots": [t_1012]}).status_code == 409  # busy
    assert client.post(url, json={"tech_id": "tech_wagner", "slots": slots}).status_code == 409  # other partner
    r = client.post(url, json={"tech_id": "tech_tom", "slots": slots})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "slots_proposed"
    assert job["technician"] == {"tech_id": "tech_tom", "name": "Tom Schmidt"}
    assert job["proposed_slots"][0]["label"] == "Tomorrow 8–10"  # tenant language is "en"
    assert job["tenant"] == {"name": "Luka", "phone": "+490000000001"}

    # technician can't confirm before the tenant picked
    assert client.post(f"/api/tech/tech_tom/jobs/{cid}/confirm").status_code == 409

    # tenant picks slot 1 on WhatsApp → waits for the technician
    with pytest.raises(rules.RuleViolation):
        services.confirm_slot(cid, 0)
    res = services.confirm_slot(cid, 1)  # 1-based
    assert res["status"] == "awaiting_technician"
    assert res["slot"]["label"] == "Tomorrow 8–10"
    assert res["technician"]["name"] == "Tom Schmidt"

    # technician phone page: sees the job (consented context only) and confirms
    assert client.get("/api/tech/tech_ali/jobs").json() == []
    assert client.get(f"/api/tech/tech_ali/jobs/{cid}").status_code == 404
    tjobs = client.get("/api/tech/tech_tom/jobs").json()
    assert [j["case_id"] for j in tjobs] == [cid] and tjobs[0]["needs_confirmation"] is True
    tjob = client.get(f"/api/tech/tech_tom/jobs/{cid}").json()
    assert tjob["chosen_slot"] == {"start": t_0810["start"], "end": t_0810["end"]}
    assert tjob["tenant"] == {"name": "Luka", "phone": "+490000000001"}
    assert tjob["address"].startswith("Musterstraße")
    r = client.post(f"/api/tech/tech_tom/jobs/{cid}/confirm")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "scheduled" and r.json()["needs_confirmation"] is False
    assert client.post(f"/api/tech/tech_tom/jobs/{cid}/confirm").status_code == 409  # only once
    tom = next(t for t in client.get("/api/partner/heizung-schmidt/technicians").json()
               if t["tech_id"] == "tech_tom")
    assert t_0810 not in tom["free_slots"]  # booked on his calendar
    staff = client.get(f"/api/staff/cases/{cid}").json()
    assert staff["status"] == "scheduled"
    assert staff["technician"] == {"tech_id": "tech_tom", "name": "Tom Schmidt"}
    assigned = next(e for e in staff["events"] if e["kind"] == "technician.assigned")
    assert assigned["summary"] == "Dispatcher assigned Tom Schmidt" and assigned["data"]["auto"] is False
    assert client.get("/api/staff/cases").json()[0]["technician"] == {"tech_id": "tech_tom", "name": "Tom Schmidt"}
    assert client.get("/api/tech/tech_tom").json()["partner_name"] == "Heizung Schmidt GmbH"
    ev = next(e for e in staff["events"] if e["kind"] == "technician.confirmed")
    assert ev["summary"].startswith("Technician Tom Schmidt confirmed ") and ev["summary"].endswith(" 08:00–10:00")
    assert ev["data"]["slot"]["label"] == "Tomorrow 8–10"  # same slot dict goes to notify_tenant

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
    assert detail["result"]["service_job"]["technician"] == "Tom Schmidt"
    for k in ["case.created", "case.linked_reporter", "partner.ranked", "consent.recorded",
              "job.sent", "job.accepted", "slot.proposed", "slot.confirmed", "technician.confirmed",
              "job.completed",
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
    luka, boiler, case = _open_luka_case()
    services.record_consent(luka.id, "heizung-schmidt", case.id, ["address"], "repair", "whatsapp")
    services.dispatch_job(case.id, "heizung-schmidt")
    job = client.get(f"/api/partner/heizung-schmidt/jobs/{case.id}").json()
    assert job["address"].startswith("Musterstraße")
    assert job["tenant"] is None
    # another partner can't see it
    assert client.get(f"/api/partner/waerme-wagner/jobs/{case.id}").status_code == 404


def test_approval_flow(client):
    luka, boiler, case = _open_luka_case()
    client.post("/demo/trigger/expensive_repair", json={"case_id": case.id})
    services.record_consent(luka.id, "heizung-schmidt", case.id, ["name", "address"], "repair", "whatsapp")
    with pytest.raises(rules.RuleViolation) as e:
        services.dispatch_job(case.id, "heizung-schmidt")
    assert e.value.code == "approval_required"
    d = client.get(f"/api/staff/cases/{case.id}").json()
    assert d["status"] == "awaiting_approval" and d["approval"]["required"] is True
    d = client.post(f"/api/staff/cases/{case.id}/approve").json()
    assert d["status"] == "requested"
    assert d["partner"]["partner_id"] == "heizung-schmidt"


def test_decline_reranks(client):
    luka, boiler, case = _open_luka_case()
    services.rank_partners(case.id)
    services.record_consent(luka.id, "heizung-schmidt", case.id, ["address"], "repair", "whatsapp")
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
    assert client.post("/demo/trigger/neighbour", json={}).json()["duplicate_of"] == cid
    from app.config import settings
    from app.db import get_session
    from app.models import Conversation
    with get_session() as s:
        s.add(Conversation(contact_id="c_202", case_id=cid, claude_messages=[{"role": "user"}]))
        s.commit()
    sim_id = client.post("/demo/sim-media", files={"file": ("x.jpg", b"jpg", "image/jpeg")}).json()["media_id"]
    from app.demo import sim_media_path
    assert sim_media_path(sim_id).exists()
    client.post("/demo/reset")
    assert client.get("/api/staff/cases").json() == []
    assert not sim_media_path(sim_id).exists()
    with get_session() as s:
        from sqlmodel import select
        assert s.exec(select(Conversation)).all() == []
    assert client.get("/healthz").json()["ok"] is True


def test_error_labels_everywhere(client):
    assert services.error_label("F.28") == "Ignition failed: no flame at start-up"
    assert services.error_label("f22") == "Water pressure too low"
    assert services.error_label("F.29") == "Flame lost during operation"
    assert services.error_label("F.99") == "Error code F.99"
    assert services.error_label(None) is None
    assert services.error_phrase("F.28") == "Boiler error: ignition failed (F.28)"

    luka, boiler, case = _open_luka_case()
    label = "Ignition failed: no flame at start-up"
    summary = client.get("/api/staff/cases").json()[0]
    assert summary["error_code"] == "F.28" and summary["error_label"] == label
    detail = client.get(f"/api/staff/cases/{case.id}").json()
    assert detail["asset"]["error_label"] == label
    created = next(e for e in detail["events"] if e["kind"] == "case.created")
    assert created["summary"] == "Case opened from Luka's report. Boiler error: ignition failed (F.28)"
    assert services.get_unit_context("unit_4b")["open_cases"][0]["error_label"] == label

    services.record_consent(luka.id, "heizung-schmidt", case.id, ["address"], "repair", "whatsapp")
    services.dispatch_job(case.id, "heizung-schmidt")
    jobs = client.get("/api/partner/heizung-schmidt/jobs").json()
    assert jobs[0]["error_label"] == label
    job = client.get(f"/api/partner/heizung-schmidt/jobs/{case.id}").json()
    assert job["error_label"] == label and job["asset"]["error_label"] == label
    sent = next(e for e in client.get(f"/api/staff/cases/{case.id}").json()["events"] if e["kind"] == "job.sent")
    assert sent["summary"].endswith("Boiler error: ignition failed (F.28)")


def test_set_case_error_code(client):
    luka = services.get_contact_by_phone("+490000000001")
    boiler = services.get_unit_context(luka.unit_id)["assets"][0]
    case = services.open_case(luka.id, "repair.heating", "urgent", "kalt", "kalt", None, boiler["id"])
    assert case.error_code is None
    est_before = case.estimated_cost_eur

    updated = services.set_case_error_code(case.id, "f22")
    assert updated.error_code == "F.22"
    assert updated.estimated_cost_eur != est_before  # re-estimated for the new code
    services.set_case_error_code(case.id, "F.22")  # same code → no second event

    detail = client.get(f"/api/staff/cases/{case.id}").json()
    evs = [e for e in detail["events"] if e["kind"] == "case.error_code"]
    assert len(evs) == 1
    assert evs[0]["summary"] == "Boiler error: water pressure too low (F.22)"
    assert evs[0]["data"]["error_label"] == "Water pressure too low"
    assert detail["asset"]["error_label"] == "Water pressure too low"

    with pytest.raises(rules.RuleViolation):
        services.set_case_error_code(case.id, " ")



def _dispatched_case(client):
    luka, boiler, case = _open_luka_case()
    services.record_consent(luka.id, "heizung-schmidt", case.id, ["name", "address"], "repair", "whatsapp")
    services.dispatch_job(case.id, "heizung-schmidt")
    client.post(f"/api/partner/heizung-schmidt/jobs/{case.id}/accept")
    return case.id


def _slot(days: int, hour: int) -> dict:
    t = (now() + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return {"start": t.isoformat(timespec="seconds"),
            "end": (t + timedelta(hours=2)).isoformat(timespec="seconds")}


def test_auto_assign_technician_without_tech_id(client):
    """Live partner page may not send tech_id yet: the dispatcher auto-assigns the best free technician."""
    cid = _dispatched_case(client)
    # tomorrow 08–10: Tom (Vaillant) is free, Ali and Jana are busy → Tom (brand skill wins)
    r = client.post(f"/api/partner/heizung-schmidt/jobs/{cid}/slots", json={"slots": [_slot(1, 8)]})
    assert r.status_code == 200, r.text
    assert r.json()["technician"] == {"tech_id": "tech_tom", "name": "Tom Schmidt"}
    ev = next(e for e in client.get(f"/api/staff/cases/{cid}").json()["events"]
              if e["kind"] == "technician.assigned")
    assert ev["summary"].startswith("Dispatcher auto-assigned Tom Schmidt") and ev["data"]["auto"] is True
    # same flow afterwards: tenant picks → awaiting_technician → technician confirms → scheduled
    assert services.confirm_slot(cid, 1)["status"] == "awaiting_technician"
    assert client.post(f"/api/tech/tech_tom/jobs/{cid}/confirm").json()["status"] == "scheduled"


def test_auto_assign_skips_busy_brand_technician(client):
    cid = _dispatched_case(client)
    # tomorrow 10–12: Tom and Jana busy → Ali (heating trade, free)
    r = client.post(f"/api/partner/heizung-schmidt/jobs/{cid}/slots", json={"slots": [_slot(1, 10)]})
    assert r.status_code == 200, r.text
    assert r.json()["technician"]["tech_id"] == "tech_ali"


def test_auto_assign_no_one_free_and_explicit_busy(client):
    cid = _dispatched_case(client)
    # tomorrow 08–10 AND 10–12: nobody is free in both → 409
    r = client.post(f"/api/partner/heizung-schmidt/jobs/{cid}/slots",
                    json={"slots": [_slot(1, 8), _slot(1, 10)]})
    assert r.status_code == 409
    # explicitly chosen busy technician stays 409
    r = client.post(f"/api/partner/heizung-schmidt/jobs/{cid}/slots",
                    json={"tech_id": "tech_tom", "slots": [_slot(1, 10)]})
    assert r.status_code == 409


def test_english_slot_labels(client):
    lbl = services.case_label_slot
    tomorrow = _slot(1, 8)
    assert lbl(tomorrow["start"], tomorrow["end"], "en") == "Tomorrow 8–10"
    later = _slot(3, 14)
    from datetime import datetime
    d = datetime.fromisoformat(later["start"])
    assert lbl(later["start"], later["end"], "en") == f"{services.EN_DAYS[d.weekday()]} {d.day} {services.EN_MONTHS[d.month - 1]}, 14–16"
