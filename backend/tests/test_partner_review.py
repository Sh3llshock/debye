"""Feature 1: staff review of self-onboarded partners."""
import shutil
from datetime import timedelta
from pathlib import Path

import pytest

from app import services
from app.partners.onboarding import build_manifest

REPO_PARTNERS = Path(__file__).resolve().parents[2] / "partners"


@pytest.fixture()
def partners_dir(tmp_path, monkeypatch):
    from app.config import settings
    d = tmp_path / "partners"
    shutil.copytree(REPO_PARTNERS, d)
    monkeypatch.setattr(settings, "partners_dir", str(d))
    return d


def _docs(ins_valid="2030-06-30", cover=5_000_000, name="Sanitär Becker GmbH"):
    return [
        {"doc_type": "trade_licence", "filename": "hwk.pdf", "number": "HWK-AC 1", "company_name": name},
        {"doc_type": "insurance", "filename": "ins.pdf", "number": "BHV-1", "valid_until": ins_valid,
         "coverage_eur": cover, "company_name": name},
        {"doc_type": "vat", "filename": "vat.pdf", "number": "DE123456789", "company_name": name},
    ]


def _onboard(client, docs=None):
    m = build_manifest({"name": "Sanitär Becker GmbH", "trades": ["plumbing"], "brands": ["Grohe"],
                        "base_postcode": "52062", "radius_km": 15})
    r = client.post("/api/partners/onboard", json={
        "manifest": m, "technicians": [{"name": "Lena Becker", "skills": ["plumbing"]}],
        "documents": docs if docs is not None else _docs(),
        "company": {"name": "Sanitär Becker GmbH", "postcode": "52062", "city": "Aachen"}})
    assert r.status_code == 200, r.text
    return r.json()["partner_id"]


def _plumbing_case():
    luka = services.get_contact_by_phone("+490000000001")
    boiler = services.get_unit_context(luka.unit_id)["assets"][0]
    return services.open_case(luka.id, "repair.hot_water", "normal", "Shower stays cold", "no hot water",
                              None, boiler["id"], trade="plumbing")


def _ranked(case_id):
    return [r["partner_id"] for r in services.rank_partners(case_id)]


def test_onboarding_creates_pending_review_with_documents(client, partners_dir):
    pid = _onboard(client)
    p = client.get(f"/api/partner/{pid}").json()
    assert p["status"] == "pending_review" and p["active"] is False
    apps = client.get("/api/staff/partners/applications").json()
    app_ = next(a for a in apps if a["partner_id"] == pid)
    assert len(app_["documents"]) == 3
    assert client.get(app_["documents"][0]["url"]).status_code == 200
    checks = {c["id"]: c["status"] for c in app_["precheck"]}
    assert checks["documents"] == "pass" and checks["insurance_cover"] == "pass"
    assert checks["company_name"] == "pass" and checks["service_area"] == "pass"


def test_pending_partner_never_ranked_until_approved(client, partners_dir):
    pid = _onboard(client)
    case = _plumbing_case()
    assert pid not in _ranked(case.id)
    import app.rules as rules
    with pytest.raises(rules.RuleViolation) as e:
        services.dispatch_job(case.id, pid)
    assert e.value.code == "partner_not_active"

    r = client.post(f"/api/staff/partners/{pid}/approve", json={})
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert r.json()["review"]["reviewer"] == "Anna Becker"
    assert pid in _ranked(_plumbing_case().id)
    assert pid not in [a["partner_id"] for a in client.get("/api/staff/partners/applications").json()]


def test_reject_needs_reason_and_shows_on_portal(client, partners_dir):
    pid = _onboard(client)
    assert client.post(f"/api/staff/partners/{pid}/reject", json={"reason": ""}).status_code == 422
    r = client.post(f"/api/staff/partners/{pid}/reject", json={"reason": "Insurance certificate unreadable"})
    assert r.status_code == 200
    p = client.get(f"/api/partner/{pid}").json()
    assert p["status"] == "rejected" and p["review"]["reason"] == "Insurance certificate unreadable"
    assert pid not in _ranked(_plumbing_case().id)


def test_precheck_flags_bad_documents(client, partners_dir):
    pid = _onboard(client, _docs(ins_valid="2020-01-01", cover=500_000, name="Other Name GmbH")[:2])
    app_ = client.get(f"/api/staff/partners/{pid}/application").json()
    checks = {c["id"]: c["status"] for c in app_["precheck"]}
    assert checks["documents"] == "fail"  # VAT certificate missing
    assert checks["validity"] == "fail" and checks["insurance_cover"] == "fail"
    assert checks["company_name"] == "fail"
    assert app_["precheck_result"] == "fail"


def test_expired_insurance_suspends(client, partners_dir):
    from app.config import advance_clock, now
    soon = (now() + timedelta(days=1)).date().isoformat()  # still valid today, lapses after tomorrow
    pid = _onboard(client, _docs(ins_valid=soon))
    client.post(f"/api/staff/partners/{pid}/approve", json={})
    assert services.check_partner_expiry() == []
    advance_clock(timedelta(days=1))
    r = client.post("/demo/skip-to-tomorrow").json()
    assert pid in r["suspended_partners"]
    assert client.get(f"/api/partner/{pid}").json()["status"] == "suspended"
    assert pid not in _ranked(_plumbing_case().id)


def test_review_state_survives_reset(client, partners_dir):
    pid = _onboard(client)
    from app.seed import seed
    seed(reset=True)
    assert client.get(f"/api/partner/{pid}").json()["status"] == "pending_review"
    assert len(client.get(f"/api/staff/partners/{pid}/application").json()["documents"]) == 3
    client.post(f"/api/staff/partners/{pid}/approve", json={})
    seed(reset=True)
    assert client.get(f"/api/partner/{pid}").json()["status"] == "active"
