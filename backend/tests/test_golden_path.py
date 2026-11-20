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


def _dispatch(case_id: str, partner_id: str = "heizung-schmidt") -> dict:
    """APPROVAL_POLICY=always: dispatch stops at approval_pending until staff approve."""
    with pytest.raises(rules.RuleViolation) as e:
        services.dispatch_job(case_id, partner_id)
    assert e.value.code == "approval_required"
    assert services.get_case(case_id).status == "approval_pending"
    return services.approve_case(case_id)["dispatched"]


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
    with pytest.raises(rules.RuleViolation) as e:
        services.dispatch_job(cid, "heizung-schmidt")
    assert e.value.code == "approval_required"
    pending = client.get(f"/api/staff/cases/{cid}").json()
    assert pending["status"] == "approval_pending"
    assert client.get("/api/partner/heizung-schmidt/jobs").json() == []  # partner not contacted yet
    ev = next(e for e in pending["events"] if e["kind"] == "approval.required")
    assert ev["summary"].startswith("Waiting for staff approval: Heizung Schmidt GmbH, est. €")
    approved = client.post(f"/api/staff/cases/{cid}/approve").json()
    assert approved["status"] == "requested" and approved["approval"]["granted"] is True

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
    _dispatch(case.id)
    job = client.get(f"/api/partner/heizung-schmidt/jobs/{case.id}").json()
    assert job["address"].startswith("Musterstraße")
    assert job["tenant"] is None
    # another partner can't see it
    assert client.get(f"/api/partner/waerme-wagner/jobs/{case.id}").status_code == 404


def _notify_spy(monkeypatch):
    from app import notify
    sent = []

    async def spy(case_id, event, data):
        sent.append((event, data))
    monkeypatch.setattr(notify, "notify_tenant", spy)
    return sent


def test_approval_always_approve(client, monkeypatch):
    """APPROVAL_POLICY=always (default): even a cheap job waits for staff, then goes out on approve."""
    sent = _notify_spy(monkeypatch)
    luka, boiler, case = _open_luka_case()
    assert case.estimated_cost_eur < 500  # would have been auto-approved under the old rule
    services.record_consent(luka.id, "heizung-schmidt", case.id, ["name", "address"], "repair", "whatsapp")
    with pytest.raises(rules.RuleViolation) as e:
        services.dispatch_job(case.id, "heizung-schmidt")
    assert e.value.code == "approval_required"
    with pytest.raises(rules.RuleViolation):  # retry (e.g. second consent tap) → no second event
        services.dispatch_job(case.id, "heizung-schmidt")
    d = client.get(f"/api/staff/cases/{case.id}").json()
    assert d["status"] == "approval_pending" and d["approval"]["required"] is True
    assert d["partner"] is None
    card = d["approval"]
    assert card["partner"] == {"partner_id": "heizung-schmidt", "name": "Heizung Schmidt GmbH"}
    assert card["amount_eur"] == d["estimated_cost_eur"]
    assert card["suggested_technician"] == {"tech_id": "tech_tom", "name": "Tom Schmidt"}  # Vaillant, free first
    assert card["suggested_slot"]["label"] == "Tomorrow 8–10"
    assert client.get("/api/staff/cases").json()[0]["status"] == "approval_pending"
    assert [e["kind"] for e in d["events"]].count("approval.required") == 1
    assert "job.sent" not in [e["kind"] for e in d["events"]]
    d = client.post(f"/api/staff/cases/{case.id}/approve").json()
    assert d["status"] == "requested" and d["partner"]["partner_id"] == "heizung-schmidt"
    kinds = [e["kind"] for e in d["events"]]
    assert kinds.index("approval.granted") < kinds.index("job.sent")
    granted = next(e for e in d["events"] if e["kind"] == "approval.granted")
    assert granted["summary"].startswith("Staff approved the job for Heizung Schmidt GmbH")
    assert ("approval_granted", {"partner_name": "Heizung Schmidt GmbH",
                                 "dispatched": sent[-1][1]["dispatched"]}) == sent[-1]
    assert [j["case_id"] for j in client.get("/api/partner/heizung-schmidt/jobs").json()] == [case.id]


def test_approval_always_reject(client, monkeypatch):
    sent = _notify_spy(monkeypatch)
    luka, boiler, case = _open_luka_case()
    services.record_consent(luka.id, "heizung-schmidt", case.id, ["name", "address"], "repair", "whatsapp")
    with pytest.raises(rules.RuleViolation):
        services.dispatch_job(case.id, "heizung-schmidt")
    r = client.post(f"/api/staff/cases/{case.id}/reject", json={"reason": "Caretaker fixes it tomorrow"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "rejected"
    assert d["approval"]["rejected"] is True and d["approval"]["reason"] == "Caretaker fixes it tomorrow"
    assert d["approval"]["suggested_technician"] is None
    ev = next(e for e in d["events"] if e["kind"] == "approval.rejected")
    assert ev["summary"] == "Staff rejected the job for Heizung Schmidt GmbH: Caretaker fixes it tomorrow"
    assert sent[-1] == ("approval_rejected", {"partner_name": "Heizung Schmidt GmbH",
                                              "reason": "Caretaker fixes it tomorrow"})
    assert client.get("/api/partner/heizung-schmidt/jobs").json() == []  # partner never contacted
    assert client.post(f"/api/staff/cases/{case.id}/reject", json={}).status_code == 409  # only once
    assert services.find_open_case_for_asset(boiler["id"]) is None  # a new report opens a new case


def test_approval_policy_limit(client, monkeypatch):
    """APPROVAL_POLICY=limit keeps the old rule: auto-approve below the framework limit."""
    from app.config import settings
    monkeypatch.setattr(settings, "approval_policy", "limit")
    luka, boiler, case = _open_luka_case()
    services.record_consent(luka.id, "heizung-schmidt", case.id, ["name", "address"], "repair", "whatsapp")
    out = services.dispatch_job(case.id, "heizung-schmidt")
    assert out["status"] == "requested" and out["approval"]["required"] is False
    # expensive case still needs approval under "limit"
    luka2 = services.get_contact_by_phone("+490000000002")
    c2 = services.open_case(luka2.id, "repair.heating", "urgent", "kalt", "kalt", "F.28", None)
    client.post("/demo/trigger/expensive_repair", json={"case_id": c2.id})
    services.record_consent(luka2.id, "heizung-schmidt", c2.id, ["address"], "repair", "whatsapp")
    with pytest.raises(rules.RuleViolation):
        services.dispatch_job(c2.id, "heizung-schmidt")
    d = client.get(f"/api/staff/cases/{c2.id}").json()
    assert d["status"] == "approval_pending" and "auto-approve limit" in d["approval"]["rule"]


def test_decline_reranks(client):
    luka, boiler, case = _open_luka_case()
    services.rank_partners(case.id)
    services.record_consent(luka.id, "heizung-schmidt", case.id, ["address"], "repair", "whatsapp")
    _dispatch(case.id)
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
    assert r.json()["blocked"] == "approval_required"
    assert client.post(f"/api/staff/cases/{cid}/approve").json()["status"] == "requested"
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
    _dispatch(case.id)
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
    _dispatch(case.id)
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


# ---------------------------------------------------------------- diagnosis (docs/diagnosis.md)
import json as _json

KB = _json.loads((Path(__file__).resolve().parents[2] / "data" / "diagnosis" / "no_hot_water.json")
                 .read_text(encoding="utf-8"))
CAUSES = {c["id"]: c for c in KB["causes"]}


def _diag(cause_id: str, confidence: float = 0.8) -> dict:
    c = CAUSES[cause_id]
    return {"cause_id": cause_id, "label": c["label"], "confidence": confidence,
            "reasoning": "Shower cold, radiators fine, other taps hot", "questions_asked": ["q_scope", "q_radiators"]}


def _open_with(cause_id: str):
    luka = services.get_contact_by_phone("+490000000001")
    boiler = services.get_unit_context(luka.unit_id)["assets"][0]
    trade = CAUSES[cause_id]["trade"]
    case = services.open_case(luka.id, "repair.hot_water", "normal", "No hot water in the shower",
                              "no hot water", None, boiler["id"], trade=trade, diagnosis=_diag(cause_id))
    return luka, case


def test_diagnosis_stored_and_shown(client):
    luka, case = _open_with("shower_mixer_faulty")
    d = client.get(f"/api/staff/cases/{case.id}").json()
    assert d["trade"] == "plumbing"
    assert d["diagnosis"]["cause_id"] == "shower_mixer_faulty"
    assert d["diagnosis"]["label"] == CAUSES["shower_mixer_faulty"]["label"]
    qs = {q["id"]: q["text"] for q in KB["questions"]}
    assert d["diagnosis"]["questions_asked"] == [{"question": qs["q_scope"], "answer": None},
                                                 {"question": qs["q_radiators"], "answer": None}]
    assert d["diagnosis"]["outcome"] == "technician" and d["diagnosis"]["trade"] == "plumbing"
    assert d["diagnosis"]["estimated_cost_eur"] == CAUSES["shower_mixer_faulty"]["estimated_cost_eur"]
    assert d["diagnosis"]["estimated_saving_eur"] is None
    assert d["estimated_cost_eur"] == CAUSES["shower_mixer_faulty"]["estimated_cost_eur"]  # KB estimate wins
    ev = next(e for e in d["events"] if e["kind"] == "diagnosis.recorded")
    assert ev["summary"] == f"Debye diagnosed: {CAUSES['shower_mixer_faulty']['label']} (80%)"
    assert client.get("/api/staff/cases").json()[0]["trade"] == "plumbing"


def test_plumbing_ranks_by_trade_and_preselects_ali(client):
    luka, case = _open_with("shower_mixer_faulty")
    ranking = services.rank_partners(case.id)
    assert [r["partner_id"] for r in ranking] == ["heizung-schmidt"]  # only partner with the plumbing trade
    assert "plumbing trade" in ranking[0]["reasons"]
    assert not any("certified" in r for r in ranking[0]["reasons"])  # no brand bonus for plumbing
    services.record_consent(luka.id, "heizung-schmidt", case.id, ["name", "address"], "repair", "whatsapp")
    with pytest.raises(rules.RuleViolation):
        services.dispatch_job(case.id, "heizung-schmidt")
    card = client.get(f"/api/staff/cases/{case.id}").json()["approval"]
    assert card["suggested_technician"]["tech_id"] == "tech_ali"  # the plumber
    assert card["trade"] == "plumbing"
    assert card["diagnosis"]["label"] == CAUSES["shower_mixer_faulty"]["label"]
    assert card["diagnosis"]["reasoning"].startswith("Shower cold")
    services.approve_case(case.id)
    client.post(f"/api/partner/heizung-schmidt/jobs/{case.id}/accept")
    slots = [s for t in client.get("/api/partner/heizung-schmidt/technicians").json()
             if t["tech_id"] == "tech_ali" for s in t["free_slots"]][:1]
    job = client.post(f"/api/partner/heizung-schmidt/jobs/{case.id}/slots", json={"slots": slots}).json()
    assert job["technician"]["tech_id"] == "tech_ali"  # auto-assign matches the trade skill


def test_electrical_goes_to_elektro_klein(client):
    luka = services.get_contact_by_phone("+490000000001")
    case = services.open_case(luka.id, "repair.electrical", "urgent", "Boiler has no power", "dead display",
                              None, None, trade="electrical",
                              diagnosis={"cause_id": "no_power_to_boiler", "label": "Boiler has no power",
                                         "confidence": 0.7, "reasoning": "display dark", "questions_asked": []})
    ranking = services.rank_partners(case.id)
    assert [r["partner_id"] for r in ranking] == ["elektro-klein"]
    sug = services.suggest_technician(case.id, "elektro-klein")
    assert sug["technician"]["tech_id"] == "tech_marco"


def test_heating_keeps_brand_bonus(client):
    luka, case = _open_with("boiler_fault")
    ranking = services.rank_partners(case.id)
    assert ranking[0]["partner_id"] == "heizung-schmidt"
    assert "Vaillant-certified" in ranking[0]["reasons"]
    assert len(ranking) == 3


def test_notify_caretaker(client):
    luka, case = _open_with("low_system_pressure")
    out = services.notify_caretaker(case.id, "top up system pressure")
    assert out["caretaker"]["name"] == "Peter Wolf"
    d = client.get(f"/api/staff/cases/{case.id}").json()
    ev = next(e for e in d["events"] if e["kind"] == "caretaker.notified")
    assert ev["summary"] == "Caretaker Peter Wolf notified: top up system pressure"
    assert d["caretaker"]["reason"] == "top up system pressure"
    assert d["partner"] is None and "job.sent" not in [e["kind"] for e in d["events"]]


def test_set_case_diagnosis_later(client):
    luka, boiler, case = _open_luka_case()
    services.set_case_diagnosis(case.id, _diag("circulation_pump_faulty", 0.6), trade="heating")
    d = client.get(f"/api/staff/cases/{case.id}").json()
    assert d["diagnosis"]["cause_id"] == "circulation_pump_faulty" and d["trade"] == "heating"



def test_diagnosis_shape_from_agent(client):
    """Agent-style input: question/answer pairs, confidence in percent, trade taken from the KB."""
    luka = services.get_contact_by_phone("+490000000001")
    case = services.open_case(
        luka.id, "repair.hot_water", "normal", "No hot water in the shower", "cold shower", None, None,
        diagnosis={"cause_id": "shower_mixer_faulty", "confidence": 85, "reasoning": "only the shower",
                   "questions_asked": [{"question": "Only the shower?", "answer": "yes, sinks are hot"}]})
    d = client.get(f"/api/staff/cases/{case.id}").json()
    assert d["trade"] == "plumbing"  # from the KB cause
    assert d["diagnosis"]["confidence"] == 0.85
    assert d["diagnosis"]["questions_asked"] == [{"question": "Only the shower?", "answer": "yes, sinks are hot"}]
    ev = next(e for e in d["events"] if e["kind"] == "diagnosis.recorded")
    assert ev["summary"].endswith("(85%)")


def test_self_help_case_closes_without_partner(client):
    luka = services.get_contact_by_phone("+490000000001")
    case = services.open_case(luka.id, "repair.hot_water", "normal", "Shower lukewarm", "others showered",
                              None, None, diagnosis={"cause_id": "hot_water_used_up", "confidence": 0.9,
                                                     "reasoning": "two people showered just before"})
    assert client.get(f"/api/staff/cases/{case.id}").json()["diagnosis"]["estimated_saving_eur"] == 180
    res = services.close_self_help(case.id, "tank reheated")
    assert res["resolution"] == "self_help" and res["estimated_saving_eur"] == 180
    d = client.get(f"/api/staff/cases/{case.id}").json()
    assert d["status"] == "closed" and d["partner"] is None
    assert d["resolution"] == "self_help" and d["saving_eur"] == 180
    ev = next(e for e in d["events"] if e["kind"] == "case.closed")
    assert ev["summary"] == "Closed without a technician (self-help), saved ~€180: tank reheated"
    row = client.get("/api/staff/cases").json()[0]
    assert row["status"] == "closed" and row["resolution"] == "self_help" and row["saving_eur"] == 180


def test_caretaker_case_closes_without_partner(client):
    luka, case = _open_with("low_system_pressure")
    services.notify_caretaker(case.id, "top up system pressure")
    res = services.close_without_partner(case.id, "caretaker", "pressure topped up")
    assert res["estimated_saving_eur"] == 180
    # a case with a partner can't be closed this way
    luka2, boiler, c2 = _open_luka_case()
    services.record_consent(luka2.id, "heizung-schmidt", c2.id, ["address"], "repair", "whatsapp")
    _dispatch(c2.id)
    with pytest.raises(rules.RuleViolation):
        services.close_without_partner(c2.id, "self_help")


# ---------------------------------------------------------------- demo scenarios
def test_demo_scenarios(client):
    r = client.post("/demo/scenarios")
    assert r.status_code == 200, r.text
    by = {c["scenario"]: c for c in r.json()["cases"]}
    expect = {"s1_approval_pending": "approval_pending", "s2_requested": "requested",
              "s3_awaiting_technician": "awaiting_technician", "s4_scheduled_electrical": "scheduled",
              "s5_closed_invoiced": "closed", "s6_self_help": "closed", "s7_caretaker": "new",
              "s8_wagner_closed": "closed", "s9_gruen_requested": "requested"}
    assert {k: v["status"] for k, v in by.items()} == expect

    # live demo units stay empty, and nothing open on Musterstraße's central boiler
    assert client.get("/api/staff/units/unit_4b").json()["cases"] == []
    assert client.get("/api/staff/units/unit_2a").json()["cases"] == []
    assert services.find_open_case_for_asset("asset_boiler_1") is None

    # every partner portal has a job
    for pid in ("heizung-schmidt", "elektro-klein", "waerme-wagner", "heiztechnik-gruen"):
        assert client.get(f"/api/partner/{pid}/jobs").json(), pid

    s1 = client.get(f"/api/staff/cases/{by['s1_approval_pending']['case_id']}").json()
    assert s1["diagnosis"]["confidence"] == 0.85 and s1["asset"]["make"] == "Viessmann"
    assert s1["asset"]["error_label"] == "No flame signal at start-up (ignition failed)"
    assert s1["approval"]["partner"]["partner_id"] == "heizung-schmidt" and len(s1["messages"]) >= 4
    s3 = client.get(f"/api/staff/cases/{by['s3_awaiting_technician']['case_id']}").json()
    assert s3["technician"]["tech_id"] == "tech_ali" and s3["trade"] == "plumbing"
    s4 = client.get(f"/api/staff/cases/{by['s4_scheduled_electrical']['case_id']}").json()
    assert s4["technician"]["tech_id"] == "tech_marco" and s4["partner"]["partner_id"] == "elektro-klein"
    s5 = client.get(f"/api/staff/cases/{by['s5_closed_invoiced']['case_id']}").json()
    inv = next(d for d in s5["documents"] if d["kind"] == "invoice")
    assert inv["extracted"]["gross_eur"] == 498.61 and inv["extracted"]["price_check"]["result"] == "ok"
    assert client.get(inv["url"]).content.startswith(b"%PDF-1.4")
    unit = client.get("/api/staff/units/unit_41_3").json()
    assert {"invoice", "report"} <= {d["kind"] for d in unit["documents"]}
    s6 = client.get(f"/api/staff/cases/{by['s6_self_help']['case_id']}").json()
    assert s6["resolution"] == "self_help" and s6["saving_eur"] == 180 and s6["partner"] is None
    s7 = client.get(f"/api/staff/cases/{by['s7_caretaker']['case_id']}").json()
    assert s7["caretaker"]["name"] == "Peter Wolf"
    # timelines look realistic: the closed case is days old
    assert s5["created_at"] < s1["created_at"]

    # reset with scenarios works too, and a plain reset empties everything
    assert len(client.post("/demo/reset?scenarios=1").json()["cases"]) == 9
    client.post("/demo/reset")
    assert client.get("/api/staff/cases").json() == []
