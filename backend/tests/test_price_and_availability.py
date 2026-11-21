"""Judges' findings: price check against the approved cap; availability and prices from data, not ids."""
from app import rules, services
from app.db import get_session
from app.models import Case, Technician
from app.partners.manifest import Manifest
from app.partners.ranking import availability_for

INVOICE = {"invoice_number": "RE-1", "gross_eur": 498.61,
           "line_items": [{"desc": "Anfahrtspauschale", "qty": 1, "unit_price": 89.0},
                          {"desc": "Arbeitszeit, Std.", "qty": 2, "unit_price": 72.0}]}


def _case(cap: float, approved: bool = True) -> Case:
    luka = services.get_contact_by_phone("+490000000001")
    c = services.open_case(luka.id, "repair.heating", "urgent", "kalt", "kalt", "F.28", None)
    with get_session() as s:
        case = s.get(Case, c.id)
        case.estimated_cost_eur = cap
        case.data = {**case.data, "approval": {"granted": approved, "granted_by": "Anna Becker"}}
        s.add(case)
        s.commit()
        s.refresh(case)
        return case


def test_invoice_above_approved_estimate_is_flagged(client):
    case = _case(320.0)
    with get_session() as s:
        check = rules.price_check(s, "heizung-schmidt", INVOICE, case)
    assert check["result"] == "flagged" and check["cap"]["exceeded"] and check["needs_staff_review"]
    assert any("approved estimate of €320.00" in f for f in check["flags"])


def test_invoice_within_cap_is_ok(client):
    case = _case(600.0)
    with get_session() as s:
        check = rules.price_check(s, "heizung-schmidt", INVOICE, case)
    assert check["result"] == "ok" and not check["cap"]["exceeded"]


def test_approved_quote_wins_over_estimate(client):
    case = _case(320.0)
    case.data = {**case.data, "quote": {"amount_eur": 520.0, "status": "approved"}}
    with get_session() as s:
        check = rules.price_check(s, "heizung-schmidt", INVOICE, case)
    assert check["result"] == "ok" and check["cap"]["source"] == "approved quote"


def test_manifest_prices_without_framework(client):
    """A partner without a framework contract (e.g. onboarded via the form) still gets a price check."""
    with get_session() as s:
        prices = rules.partner_prices(s, "waerme-wagner")
        check = rules.price_check(s, "waerme-wagner", {"gross_eur": 100, "line_items": [
            {"desc": "Anfahrt", "unit_price": 140.0}]})
    assert prices["source"] == "manifest" and prices["callout_fee_eur"] == 95
    assert check["result"] == "flagged" and "listed €95.00" in check["flags"][0]


def test_availability_from_technician_calendars(client):
    with get_session() as s:
        def av(pid):
            techs = s.exec(__import__("sqlmodel").select(Technician).where(Technician.partner_id == pid)).all()
            from app.models import Partner
            return availability_for(Manifest.model_validate(s.get(Partner, pid).manifest),
                                    [t.busy for t in techs])
        schmidt, wagner = av("heizung-schmidt"), av("waerme-wagner")
    assert schmidt["days"] == 1 and schmidt["label"].startswith("free tomorrow")
    assert wagner["days"] > 3 and "fully booked" in wagner["label"]
    # no technicians → the manifest's availability block
    m = Manifest.model_validate({"partner_id": "x", "name": "X", "category": "repair.heating",
                                 "availability": {"next_free_days": 2}})
    assert availability_for(m, None) == {"days": 2, "label": "next free slot in 2 days"}


def test_booking_a_technician_changes_the_ranking_reason(client):
    luka = services.get_contact_by_phone("+490000000001")
    c = services.open_case(luka.id, "repair.heating", "urgent", "kalt", "kalt", "F.28", None)
    before = {r["partner_id"]: r for r in services.rank_partners(c.id)}
    assert any(x.startswith("free tomorrow") for x in before["heizung-schmidt"]["reasons"])
    from app.partners.technicians import _interval
    from app.config import now
    from datetime import timedelta
    with get_session() as s:
        for t in s.exec(__import__("sqlmodel").select(Technician).where(Technician.partner_id == "heizung-schmidt")).all():
            busy = list(t.busy)
            for d in range(1, 4):
                busy.append({**_interval((now() + timedelta(days=d)).date(), 0, 23), "reason": "booked"})
            t.busy = busy
            s.add(t)
        s.commit()
    after = {r["partner_id"]: r for r in services.rank_partners(c.id)}
    assert any("fully booked" in x for x in after["heizung-schmidt"]["reasons"])
    assert after["heizung-schmidt"]["score"] < before["heizung-schmidt"]["score"]
