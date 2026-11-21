"""Partners on WhatsApp: the sign-up handshake and a whole job run by chat replies (partners/wa_partner.py)."""
import asyncio
import shutil
from pathlib import Path

import pytest

from app import notify, rules, services
from app.channels import base
from app.channels.base import InboundMessage, Media
from app.db import get_session
from app.models import Case, Contact, Partner, WhatsAppLink
from app.partners import wa_partner

DEMO = Path(__file__).resolve().parents[2] / "data" / "demo"
PDF = DEMO / "invoice_RE-2026-1187.pdf"
PARTNER_PHONE = "+4917000000099"


class Recorder(base.Channel):
    """Stands in for the WhatsApp line: records what Debye sends."""
    name = "whatsapp"

    def __init__(self):
        self.sent: list[dict] = []

    async def send_text(self, to, text):
        self.sent.append({"to": to, "text": text, "options": []})
        return f"out{len(self.sent)}"

    async def send_buttons(self, to, text, options):
        self.sent.append({"to": to, "text": text, "options": [(o.id, o.title) for o in options]})
        return f"out{len(self.sent)}"

    async def send_list(self, to, text, button_label, rows, section_title="Optionen"):
        return await self.send_buttons(to, text, rows)

    async def send_media(self, to, kind, path, caption=None, mime=None):
        self.sent.append({"to": to, "text": caption or f"[{kind}]", "options": []})
        return f"out{len(self.sent)}"

    async def download_media(self, media):
        return media.local_path

    def to(self, phone):
        return [m for m in self.sent if m["to"] == phone]


@pytest.fixture()
def wa(client, monkeypatch):
    rec = Recorder()
    monkeypatch.setitem(base._channels, "whatsapp", rec)
    monkeypatch.setattr(base, "_last_channel", {})
    monkeypatch.setenv("DEBYE_WHATSAPP_NUMBER", "+4930123456")
    tenant_msgs: list = []

    async def spy(case_id, event, data):
        tenant_msgs.append((event, data))

    monkeypatch.setattr(notify, "notify_tenant", spy)
    rec.tenant_msgs = tenant_msgs
    return rec


def _inbound(text=None, button=None, phone=PARTNER_PHONE, media=None):
    from app import router
    msg = InboundMessage(channel="whatsapp", from_phone=phone, wa_message_id=f"in-{text or button}",
                         text=text, button_id=button, button_title=button and "tap", media=media or [],
                         profile_name="Tom")
    asyncio.run(router.handle_inbound(msg))


def _link(link_id):
    with get_session() as s:
        return s.get(WhatsAppLink, link_id)


# ------------------------------------------------------------------ handshake

def test_handshake_code_then_test_button_verifies_the_number(wa):
    start = wa_partner.start("+49 170 0000099", "Heizung Neu GmbH")
    assert start["code"].startswith("DEBYE-") and start["status"] == "pending"
    assert start["wa_link"].startswith("https://wa.me/4930123456?text=DEBYE-")

    _inbound(f"{start['code']} Hallo Debye, bitte verbinden.")
    link = _link(start["id"])
    assert link.status == "replied" and link.phone_e164 == PARTNER_PHONE and link.received_at
    reply = wa.to(PARTNER_PHONE)[-1]
    assert reply["options"] == [(f"wa_link_test:{start['id']}", "Test bestätigen")]

    _inbound(button=f"wa_link_test:{start['id']}")
    view = wa_partner.status(start["id"])
    assert view["status"] == "verified"
    assert [bool(st["at"]) for st in view["steps"]] == [True, True, True]
    assert "Verbunden" in wa.to(PARTNER_PHONE)[-1]["text"]


def test_number_that_sends_the_code_wins_over_the_typed_one(wa):
    start = wa_partner.start("+4915111111111", "Heizung Neu GmbH")
    _inbound(start["code"])
    view = wa_partner.status(start["id"])
    assert view["phone_e164"] == PARTNER_PHONE and view["number_changed"] is True


def test_expired_or_unknown_code_is_refused(wa):
    start = wa_partner.start(PARTNER_PHONE, "X")
    with get_session() as s:
        link = s.get(WhatsAppLink, start["id"])
        link.expires_at = "2000-01-01T00:00:00+01:00"
        s.add(link)
        s.commit()
    _inbound(start["code"])
    assert _link(start["id"]).status == "pending"
    assert "abgelaufen" in wa.to(PARTNER_PHONE)[-1]["text"]
    _inbound("DEBYE-ZZZZZZ")
    assert "unbekannt" in wa.to(PARTNER_PHONE)[-1]["text"]


def _manifest_for_join(pid="heizung-neu"):
    m = services.get_partner_manifest("heizung-schmidt").model_dump(mode="json", exclude_none=True)
    m.update(partner_id=pid, name="Heizung Neu GmbH",
             transport={"type": "conversational", "channel": "whatsapp", "address": "+490"})
    m.pop("onboarding", None)
    return m


def test_onboarding_needs_a_verified_whatsapp_link(wa, client):
    r = client.post("/api/partners/onboard", json={"manifest": _manifest_for_join()})
    assert r.status_code == 422 and "WhatsApp" in r.json()["detail"]["message"]

    start = client.post("/api/partners/onboard/whatsapp/start",
                        json={"phone": PARTNER_PHONE, "company": "Heizung Neu GmbH"}).json()
    _inbound(start["code"])
    _inbound(button=f"wa_link_test:{start['id']}")
    assert client.get(f"/api/partners/onboard/whatsapp/{start['id']}").json()["status"] == "verified"

    r = client.post("/api/partners/onboard", json={"manifest": _manifest_for_join(),
                                                   "whatsapp_link_id": start["id"]})
    assert r.status_code == 200, r.text
    tr = r.json()["manifest"]["transport"]
    assert tr["address"] == PARTNER_PHONE and tr["verified_at"] and tr["opt_in"]["message_id"]
    with get_session() as s:
        c = s.exec(base_select(Contact).where(Contact.phone_e164 == PARTNER_PHONE)).first()
        assert c.role == "partner_staff" and c.partner_id == "heizung-neu" and c.whatsapp_opt_in
        checks = services.partner_precheck(s, s.get(Partner, "heizung-neu"))
    assert next(c for c in checks if c["id"] == "whatsapp")["status"] == "pass"

    # no env var needed: after a reset the partner file alone brings the WhatsApp contact back
    from app.seed import seed
    try:
        seed(reset=True)
        with get_session() as s:
            c = s.exec(base_select(Contact).where(Contact.phone_e164 == PARTNER_PHONE)).first()
            assert c.role == "partner_staff" and c.partner_id == "heizung-neu"
        assert wa_partner.partner_for_phone(PARTNER_PHONE) == "heizung-neu"
    finally:
        Path(wa_partner.__file__).parents[3].joinpath("partners", "heizung-neu.json").unlink(missing_ok=True)


def base_select(model):
    from sqlmodel import select
    return select(model)


# ------------------------------------------------------------------ jobs

@pytest.fixture()
def wa_partner_job(wa, monkeypatch):
    """Heizung Schmidt on WhatsApp (PARTNER_WHATSAPP_DEMO) with an approved job for Luka's boiler."""
    from app.seed import seed
    monkeypatch.setenv("PARTNER_WHATSAPP_DEMO", PARTNER_PHONE)
    seed(reset=True)
    luka = services.get_contact_by_phone("+490000000001")
    boiler = services.get_unit_context(luka.unit_id)["assets"][0]
    case = services.open_case(luka.id, "repair.heating", "urgent", "Heizung kalt", "alles kalt", "F.28", boiler["id"])
    services.record_consent(luka.id, "heizung-schmidt", case.id, ["address", "unit_floor", "asset", "error_code"],
                            "repair", "whatsapp")
    with pytest.raises(rules.RuleViolation):
        services.dispatch_job(case.id, "heizung-schmidt")
    services.approve_case(case.id, staff_name="Anna Becker")  # → dispatch_job → WhatsApp offer
    return case.id, luka


def test_job_offer_goes_out_on_whatsapp_with_consented_fields_only(wa_partner_job, wa):
    cid, _ = wa_partner_job
    offer = wa.to(PARTNER_PHONE)[0]
    assert "Neuer Auftrag" in offer["text"] and "F.28" in offer["text"]
    assert "IBAN" not in offer["text"] and "Miete" not in offer["text"] and "+490000000001" not in offer["text"]
    ids = [o[0] for o in offer["options"]]
    assert ids == [f"wa_job_slot:{cid}:0", f"wa_job_slot:{cid}:1", f"wa_job_decline:{cid}"]
    order = services.get_case(cid).data["partner_order"]
    assert order["transport"] == "whatsapp" and order["status"] == "requested"
    assert "tenant_phone" not in order["context_keys"]


def test_whole_job_by_whatsapp_replies(wa_partner_job, wa):
    from app.agent import flow
    cid, luka = wa_partner_job

    _inbound(button=f"wa_job_slot:{cid}:0")  # tap "Morgen 8–10"
    case = services.get_case(cid)
    assert case.status == "slots_proposed" and len(case.data["proposed_slots"]) == 1
    assert [e for e, _ in wa.tenant_msgs][:2] == ["job_accepted", "slots_proposed"]
    assert "angenommen" in wa.to(PARTNER_PHONE)[-1]["text"]

    asyncio.run(flow.on_slot(luka, cid, 1))  # tenant picks it
    case = services.get_case(cid)
    if case.status == "awaiting_technician":
        ask = wa.to(PARTNER_PHONE)[-1]
        assert ask["options"] == [(f"wa_job_confirm:{cid}", "Bestätigen")]
        _inbound("Ja passt")
        assert services.get_case(cid).status == "scheduled"
        assert "technician_confirmed" in [e for e, _ in wa.tenant_msgs]
    assert "Gebucht" in wa.to(PARTNER_PHONE)[-1]["text"]

    pdf = Path(services.get_case(cid).id + ".pdf")
    tmp = Path(wa_partner.__file__).parents[2] / "storage" / pdf.name
    tmp.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(PDF, tmp)
    _inbound("Erledigt, Zündelektrode getauscht",
             media=[Media("m1", "application/pdf", "rechnung.pdf", local_path=str(tmp))])
    case = services.get_case(cid)
    assert case.status in ("completed", "invoiced", "awaiting_tenant_confirmation", "closed"), case.status
    assert case.data.get("invoice")
    assert "Rechnung erhalten" in wa.to(PARTNER_PHONE)[-1]["text"]
    kinds = [e.kind for e in _events(cid)]
    assert "partner.whatsapp" in kinds and "order.sent" in kinds


def test_decline_in_words_goes_to_the_next_partner(wa_partner_job, wa):
    cid, _ = wa_partner_job
    _inbound("Nein, diese Woche keine Zeit")
    case = services.get_case(cid)
    assert "heizung-schmidt" in (case.data.get("declined_by") or [])
    assert case.data["redispatch"]["declined_partner_id"] == "heizung-schmidt"
    assert "nächsten Partner" in wa.to(PARTNER_PHONE)[-1]["text"]


def test_typed_time_is_understood(wa_partner_job, wa):
    cid, _ = wa_partner_job
    _inbound("Ja, morgen 14-16 oder übermorgen 9:30–11")
    slots = services.get_case(cid).data["proposed_slots"]
    starts = [x["start"][11:16] for x in slots]
    assert slots and set(starts) <= {"14:00", "09:30"}  # times a technician is actually free
    assert wa_partner.parse_slots("Ja, morgen 14-16 oder übermorgen 9:30–11")[1]["start"][11:16] == "09:30"


def _events(cid):
    from sqlmodel import select
    from app.models import CaseEvent
    with get_session() as s:
        return s.exec(select(CaseEvent).where(CaseEvent.case_id == cid)).all()


# ------------------------------------------------------------------ reply parsing

@pytest.mark.parametrize("text,intent", [
    ("Ja, morgen 8–10", "accept"), ("nein leider nicht", "decline"), ("erledigt", "done"),
    ("ok", "accept"), ("Wie hoch ist der Kostenrahmen?", "question"), ("hmm", "unclear"),
])
def test_interpret(client, text, intent):
    assert wa_partner.interpret(text, "requested")["intent"] == intent


def test_yes_confirms_when_waiting_for_the_partner(client):
    assert wa_partner.interpret("passt", "awaiting_technician")["intent"] == "confirm"
