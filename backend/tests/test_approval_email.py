"""Staff approval email: tokens, one-click links, content, never sending without a key (sender stubbed)."""
import time

import pytest

from app import email_links, notify, notify_email, rules, services
from app.config import settings

DIAG = {"cause_id": "ignition_failure", "label": "Ignition failure", "confidence": 0.86,
        "reasoning": "F.28 on the display and the gas stove works, so gas supply is fine.",
        "questions_asked": [{"question": "What does the boiler display show?", "answer": "F.28"},
                            {"question": "Does the gas stove work?", "answer": "yes"}],
        "outcome": "technician", "trade": "heating"}


@pytest.fixture()
def mail(monkeypatch):
    """Email on, sender stubbed (records calls), background thread run inline."""
    sent = []
    monkeypatch.setattr(settings, "approval_email_enabled", True)
    monkeypatch.setattr(settings, "agentmail_api_key", "test-key")
    monkeypatch.setattr(settings, "agentmail_inbox", "sender@example.test")
    monkeypatch.setattr(settings, "staff_approval_email", "pm@example.test")
    monkeypatch.setattr(settings, "public_base_url", "https://debye.example.test")
    monkeypatch.setattr(notify_email, "_spawn", lambda fn: fn())
    monkeypatch.setattr(notify_email, "SENDER",
                        lambda to, subject, text, html: sent.append(
                            {"to": to, "subject": subject, "text": text, "html": html}) or {"message_id": "m1"})

    async def quiet(*a, **k):
        return None
    monkeypatch.setattr(notify, "notify_tenant", quiet)
    return sent


def _pending_case():
    luka = services.get_contact_by_phone("490000000001")
    boiler = services.get_unit_context(luka.unit_id)["assets"][0]
    case = services.open_case(luka.id, "repair.heating", "urgent", "Heizung kalt", "alles kalt",
                              "F.28", boiler["id"], trade="heating", diagnosis=DIAG)
    services.log_message(luka.id, case.id, "whatsapp", "in", "Meine Heizung ist kalt, das Display zeigt F.28")
    services.record_consent(luka.id, "heizung-schmidt", case.id, ["name", "address"], "repair", "whatsapp")
    with pytest.raises(rules.RuleViolation):
        services.dispatch_job(case.id, "heizung-schmidt")
    return case.id


def _token(url: str) -> str:
    return url.rsplit("/a/", 1)[1]


def _kinds(client, cid):
    return [e["kind"] for e in client.get(f"/api/staff/cases/{cid}").json()["events"]]


# --------------------------------------------------------------------------- tokens

def test_token_roundtrip_expiry_tamper():
    t = email_links.make_token("K-1", "confirm", "heizung-schmidt")
    d = email_links.verify_token(t)
    assert (d["c"], d["a"], d["p"]) == ("K-1", "confirm", "heizung-schmidt")
    old = email_links.make_token("K-1", "confirm", now=time.time() - 49 * 3600)
    with pytest.raises(email_links.TokenError) as e:
        email_links.verify_token(old)
    assert e.value.reason == "expired"
    body, sig = t.split(".")
    other_body = email_links.make_token("K-2", "confirm", "heizung-schmidt").split(".")[0]
    for bad in (f"{other_body}.{sig}", f"{body}.{sig[:-2]}xx", "garbage", ""):
        with pytest.raises(email_links.TokenError) as e:
            email_links.verify_token(bad)
        assert e.value.reason == "invalid"


# --------------------------------------------------------------------------- sending + content

def test_email_sent_on_approval_pending_with_reasoning_and_links(client, mail):
    cid = _pending_case()
    assert len(mail) == 1
    m = mail[0]
    assert m["to"] == "pm@example.test"
    assert m["subject"].startswith("Approve: heating technician for Luka, Musterstraße 12 4B – F.28")
    for part in (m["text"], m["html"]):
        assert "Meine Heizung ist kalt" in part           # tenant quote
        assert "Ignition failure" in part and "86%" in part  # diagnosis + confidence
        assert "Does the gas stove work?" in part         # questions + answers
        assert "Heizung Schmidt GmbH" in part             # partner
        assert "framework agreement" in part               # ranking reason
        assert "Photo: no" in part
        assert "address" in part                           # consented data
    for action in ("confirm", "reject", "info"):
        assert m["text"].count("https://debye.example.test/a/") == 3
        assert any(email_links.verify_token(_token(u))["a"] == action
                   for u in m["text"].split() if "/a/" in u)
    assert "Confirm" in m["html"] and "More information" in m["html"]
    ev = [e for e in client.get(f"/api/staff/cases/{cid}").json()["events"] if e["kind"] == "staff.email_sent"]
    assert ev and ev[0]["summary"] == "Approval email sent to pm@example.test"
    with pytest.raises(rules.RuleViolation):  # retry while pending → no second email
        services.dispatch_job(cid, "heizung-schmidt")
    assert len(mail) == 1


def test_no_send_without_key(client, mail, monkeypatch):
    monkeypatch.setattr(settings, "approval_email_enabled", None)
    monkeypatch.setattr(settings, "agentmail_api_key", None)
    cid = _pending_case()
    assert mail == [] and "staff.email_failed" not in _kinds(client, cid)  # off by default without a key
    monkeypatch.setattr(settings, "approval_email_enabled", True)  # forced on, still no key → failed event
    assert notify_email.send_approval_email(cid)["ok"] is False
    assert mail == [] and "staff.email_failed" in _kinds(client, cid)


def test_send_error_never_breaks_flow(client, mail, monkeypatch):
    def boom(*a):
        raise RuntimeError("AgentMail HTTP 500")
    monkeypatch.setattr(notify_email, "SENDER", boom)
    cid = _pending_case()
    assert services.get_case(cid).status == "approval_pending"
    assert "staff.email_failed" in _kinds(client, cid)


def test_disabled_setting(client, mail, monkeypatch):
    monkeypatch.setattr(settings, "approval_email_enabled", False)
    _pending_case()
    assert mail == []


# --------------------------------------------------------------------------- one-click actions

def _links(mail):
    return {email_links.verify_token(_token(u))["a"]: _token(u) for u in mail[-1]["text"].split() if "/a/" in u}


def test_confirm_by_link_approves_once(client, mail):
    cid = _pending_case()
    t = _links(mail)["confirm"]
    page = client.get(f"/a/{t}")
    assert page.status_code == 200 and "<form" in page.text and "Heizung Schmidt GmbH" in page.text
    assert services.get_case(cid).status == "approval_pending"  # GET alone never approves
    r = client.post(f"/api/email-actions/{t}/confirm")
    assert r.status_code == 200 and "Heizung Schmidt GmbH is being booked" in r.text
    d = client.get(f"/api/staff/cases/{cid}").json()
    assert d["status"] == "requested" and d["partner"]["partner_id"] == "heizung-schmidt"
    kinds = [e["kind"] for e in d["events"]]
    assert "approval.granted" in kinds and "staff.email_approved" in kinds and kinds.count("job.sent") == 1
    again = client.post(f"/api/email-actions/{t}/confirm")  # idempotent
    assert "Already approved" in again.text
    assert _kinds(client, cid).count("job.sent") == 1
    assert client.post(f"/api/email-actions/{_links(mail)['reject']}/reject").text.count("Already approved") >= 1


def test_reject_by_link_with_reason(client, mail):
    cid = _pending_case()
    t = _links(mail)["reject"]
    assert "textarea" in client.get(f"/a/{t}").text
    r = client.post(f"/api/email-actions/{t}/reject", data={"reason": "Caretaker checks it first"})
    assert r.status_code == 200 and "will not be contacted" in r.text
    d = client.get(f"/api/staff/cases/{cid}").json()
    assert d["status"] == "rejected" and d["approval"]["reason"] == "Caretaker checks it first"
    ev = next(e for e in d["events"] if e["kind"] == "staff.email_rejected")
    assert ev["summary"] == "Rejected by email: Caretaker checks it first"
    assert "Already decided" in client.post(f"/api/email-actions/{t}/reject").text
    assert client.get("/api/partner/heizung-schmidt/jobs").json() == []


def test_info_link_and_bad_tokens(client, mail):
    cid = _pending_case()
    links = _links(mail)
    r = client.get(f"/a/{links['info']}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(f"/staff/cases/{cid}?t=")
    # a token for one action can't be used for another
    assert client.post(f"/api/email-actions/{links['info']}/confirm").status_code == 400
    old = email_links.make_token(cid, "confirm", "heizung-schmidt", now=time.time() - 49 * 3600)
    r = client.get(f"/a/{old}")
    assert r.status_code == 410 and "expired" in r.text and "/staff/cases" in r.text
    assert client.post(f"/api/email-actions/x.y/confirm").status_code == 400
    assert services.get_case(cid).status == "approval_pending"


def test_outdated_email_after_redispatch(client, mail):
    cid = _pending_case()
    stale = _links(mail)["confirm"]
    from app.db import get_session
    from app.models import Case
    with get_session() as s:
        c = s.get(Case, cid)
        c.data = {**c.data, "pending_partner_id": "other-partner"}
        s.add(c)
        s.commit()
    r = client.post(f"/api/email-actions/{stale}/confirm")
    assert r.status_code == 409 and "outdated" in r.text
    assert services.get_case(cid).status == "approval_pending"
