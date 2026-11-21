"""Demo flow: staff approve → partner auto-accepts → technician's free times offered to the tenant."""
from app import services
from test_redispatch import _luka_case, _sent_to

ALL = ["name", "phone", "address", "tenant_name", "tenant_phone", "unit_floor", "access_details", "photos"]


def test_approve_offers_slots_from_calendar(client, monkeypatch):
    monkeypatch.setenv("AUTO_PARTNER_SLOTS", "1")
    luka, case = _luka_case()
    pid = services.rank_partners(case.id)[0]["partner_id"]
    services.record_consent(luka.id, pid, case.id, ALL, "repair", "whatsapp")
    services.dispatch_job(case.id, pid) if False else None
    _sent_to(case.id, pid, luka)  # approve → requested
    offer = services.auto_offer_slots(case.id)
    assert offer and 1 <= len(offer["slots"]) <= 3 and offer["technician_name"]
    c = services.get_case(case.id)
    assert c.status != "requested"


def test_auto_offer_off_by_flag(client, monkeypatch):
    monkeypatch.setenv("AUTO_PARTNER_SLOTS", "0")
    luka, case = _luka_case()
    pid = services.rank_partners(case.id)[0]["partner_id"]
    _sent_to(case.id, pid, luka)
    assert services.auto_offer_slots(case.id) is None
