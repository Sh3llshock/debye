"""Partner onboarding: a new partner plugs in through the connector spec, with no code change."""
import json
import shutil
from pathlib import Path

import pytest

from app import services
from app.partners.onboarding import build_manifest

REPO_PARTNERS = Path(__file__).resolve().parents[2] / "partners"


@pytest.fixture()
def partners_dir(tmp_path, monkeypatch):
    """Copy of partners/ so onboarding writes its manifest file somewhere disposable."""
    from app.config import settings
    d = tmp_path / "partners"
    shutil.copytree(REPO_PARTNERS, d)
    monkeypatch.setattr(settings, "partners_dir", str(d))
    return d


def _plumber() -> dict:
    return build_manifest({"name": "Sanitär Becker GmbH", "trades": ["plumbing"], "brands": ["Grohe"],
                           "base_postcode": "52062", "radius_km": 15})


def _open_plumbing_case():
    luka = services.get_contact_by_phone("+490000000001")
    boiler = services.get_unit_context(luka.unit_id)["assets"][0]
    return services.open_case(luka.id, "repair.hot_water", "normal", "Shower stays cold", "no hot water",
                              None, boiler["id"], trade="plumbing")


def test_schema_and_live_validation(client):
    sch = client.get("/api/partners/onboard/schema").json()
    assert {"heating", "plumbing", "electrical", "roofing", "locksmith"} <= {t["id"] for t in sch["trades"]}
    assert all(c["consent_required"] for c in sch["default_required_context"] if c["pii"])

    ok = client.post("/api/partners/onboard/validate", json={"manifest": _plumber()}).json()
    assert ok["valid"], [c for c in ok["checks"] if not c["ok"]]

    bad = _plumber()
    bad["required_context"][0]["consent_required"] = False  # address is PII
    bad["status_events"] = ["accepted", "teleported"]
    bad["eligibility"] = [{"field": "weather.today", "op": "near"}]
    res = client.post("/api/partners/onboard/validate", json={"manifest": bad}).json()
    failed = {c["id"] for c in res["checks"] if not c["ok"]}
    assert not res["valid"] and {"consent", "status_events", "eligibility", "eligibility_area"} <= failed

    r = client.post("/api/partners/onboard", json={"manifest": bad})
    assert r.status_code == 422


def test_onboarded_plumber_is_ranked_without_code_change(client, partners_dir):
    case = _open_plumbing_case()
    assert [r["partner_id"] for r in services.rank_partners(case.id)] == ["heizung-schmidt"]

    r = client.post("/api/partners/onboard", json={
        "manifest": _plumber(),
        "technicians": [{"name": "Lena Becker", "skills": ["plumbing", "Grohe"]},
                        {"name": "Max Roth", "skills": ["plumbing"]}]})
    assert r.status_code == 200, r.text
    out = r.json()
    pid = out["partner_id"]
    assert pid == "sanitaer-becker" and out["portal_url"] == "/partner/sanitaer-becker"
    assert len(out["technicians"]) == 2 and out["technicians"][0]["url"].startswith("/tech/")

    # live: listed on the Partners page, portal + technician endpoints work
    listed = {p["partner_id"]: p for p in client.get("/api/partners").json()}
    assert listed[pid]["name"] == "Sanitär Becker GmbH"
    assert {t["name"] for t in listed[pid]["technicians"]} == {"Lena Becker", "Max Roth"}
    assert client.get(f"/api/partner/{pid}").status_code == 200
    assert client.get(f"/api/partner/{pid}/technicians").json()[0]["free_slots"]
    assert client.get(f"/api/tech/{out['technicians'][0]['tech_id']}").status_code == 200

    # pending staff review first (feature 1): not ranked until approved
    assert out["status"] == "pending_review"
    assert pid not in [x["partner_id"] for x in services.rank_partners(_open_plumbing_case().id)]
    assert client.post(f"/api/staff/partners/{pid}/approve", json={}).status_code == 200

    # rankable: the next plumbing case considers it (radius 15 km around 52062 covers the property)
    ranking = services.rank_partners(_open_plumbing_case().id)
    assert pid in [x["partner_id"] for x in ranking]

    # the manifest is a file like every other partner, so it survives a demo reset
    saved = json.loads((partners_dir / f"{pid}.json").read_text(encoding="utf-8"))
    assert saved["service_area"] == {"base_postcode": "52062", "radius_km": 15}
    assert len(saved["technicians"]) == 2
    from app.seed import seed
    seed(reset=True)
    assert {t["name"] for t in client.get(f"/api/partner/{pid}/technicians").json()} == {"Lena Becker", "Max Roth"}

    # re-onboarding the same partner is idempotent; a seeded partner can't be overwritten
    again = client.post("/api/partners/onboard", json={"manifest": _plumber(), "technicians": [{"name": "Lena Becker"}]})
    assert again.status_code == 200 and len(client.get(f"/api/partner/{pid}/technicians").json()) == 1
    clash = {**_plumber(), "partner_id": "heizung-schmidt"}
    assert client.post("/api/partners/onboard", json={"manifest": clash}).status_code == 409


def test_radius_outside_area_not_eligible(client, partners_dir):
    far = {**_plumber(), "partner_id": "sanitaer-berlin", "service_area": {"base_postcode": "10115", "radius_km": 20}}
    assert client.post("/api/partners/onboard", json={"manifest": far}).status_code == 200
    ranking = services.rank_partners(_open_plumbing_case().id)
    assert "sanitaer-berlin" not in [x["partner_id"] for x in ranking]
