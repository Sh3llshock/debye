"""Golden path against backend-core's real app (DB, services, partner API), stubbed Claude, fake send."""
from pathlib import Path

import pytest
from agent_stubs import text, tool_use

REPO = Path(__file__).resolve().parents[3]
PHOTO = REPO / "data" / "demo" / "boiler_display_F28.jpg"
INVOICE = REPO / "data" / "demo" / "invoice_RE-2026-1187.pdf"
LUKA, JONAS = "490000000001", "490000000002"
_n = 0


def wa(from_, **msg):
    global _n
    _n += 1
    m = {"from": from_, "id": f"wamid.real.{_n}", "timestamp": "1", **msg}
    return {"entry": [{"changes": [{"value": {"messages": [m]}}]}]}


def tap(from_, id_, title="t", kind="button_reply"):
    return wa(from_, type="interactive", interactive={"type": kind, kind: {"id": id_, "title": title}})


@pytest.fixture
def real(monkeypatch):
    from fastapi.testclient import TestClient

    from app import router as msg_router
    from app.agent import state
    from app.channels import whatsapp
    from app.main import app
    from app.seed import seed

    monkeypatch.setattr(msg_router, "DEBOUNCE_SECONDS", 0)
    with TestClient(app) as c:
        seed(reset=True)
        state.reset_all()
        whatsapp.clear_outbox()
        whatsapp._seen.clear()
        yield c


def last(c, to=None):
    msgs = c.get("/webhooks/whatsapp/_outbox").json()["messages"]
    if to:
        msgs = [m for m in msgs if m["to"] == "+" + to]
    return msgs[-1]["payload"]


def ids(p):
    it = p["interactive"]
    if it["type"] == "button":
        return [b["reply"]["id"] for b in it["action"]["buttons"]]
    return [r["id"] for s in it["action"]["sections"] for r in s["rows"]]


@pytest.mark.skipif(not PHOTO.exists(), reason="demo assets missing")
def test_golden_path_real_backend(real, claude, monkeypatch):
    from app import media

    async def fake_transcribe(path, language="de"):
        return "Hallo, bei mir ist die Heizung komplett kalt seit heute Morgen."

    monkeypatch.setattr(media, "transcribe", fake_transcribe)
    claude([
        [tool_use("open_case", summary="Heizung kalt, Fehler F.28", symptoms="komplett kalt seit heute Morgen",
                  error_code="F.28", priority="urgent")],
        [tool_use("ask_buttons", text="Der Kessel zeigt F.28. Sind alle Heizkörper kalt?",
                  options=[{"id": "cold_all:case_0001", "title": "All cold"},
                           {"id": "cold_some:case_0001", "title": "Just one room"}])],
        [text("ok")],
        RuntimeError("Claude down for the neighbour"),
    ])
    # simulator-style upload → sim-xxxx media ids
    up = real.post("/demo/sim-media", files={"file": ("display.jpg", PHOTO.read_bytes(), "image/jpeg")}).json()
    media_id = up.get("media_id") or up.get("id")
    real.post("/webhooks/whatsapp", json=wa(LUKA, type="image", image={"id": media_id, "mime_type": "image/jpeg",
                                                                        "caption": "Heizung kalt, siehe Display"}))
    p = last(real)
    case_id = ids(p)[0].split(":")[1]
    assert ids(p) == [f"cold_all:{case_id}", f"cold_some:{case_id}"]

    detail = real.get(f"/api/staff/cases/{case_id}").json()
    assert any(d["kind"] == "photo" for d in detail["documents"])  # orphan photo claimed by the case
    assert any(m["direction"] == "in" for m in detail["messages"])

    real.post("/webhooks/whatsapp", json=tap(LUKA, f"cold_all:{case_id}", "All cold"))
    assert ids(last(real)) == [f"consent_yes:{case_id}", f"consent_no:{case_id}"]
    real.post("/webhooks/whatsapp", json=tap(LUKA, f"consent_yes:{case_id}", "Yes, go ahead"))
    # APPROVAL_POLICY=always: reltix staff approve every job before the partner is contacted
    assert real.get(f"/api/staff/cases/{case_id}").json()["status"] == "approval_pending"
    assert real.post(f"/api/staff/cases/{case_id}/approve").status_code == 200
    detail = real.get(f"/api/staff/cases/{case_id}").json()
    assert detail["consents"] and detail["partner"]["partner_id"]
    partner = detail["partner"]["partner_id"]

    # neighbour reports while Claude is down → linked, no second case
    real.post("/webhooks/whatsapp", json=wa(JONAS, type="text", text={"body": "Bei uns ist es auch kalt"}))
    assert "already reported" in last(real, JONAS)["text"]["body"]
    assert len(real.get("/api/staff/cases").json()) == 1

    # partner page: accept, propose slots → resident gets a list
    assert real.post(f"/api/partner/{partner}/jobs/{case_id}/accept").status_code == 200
    # technician flow: the dispatcher picks a technician and proposes from that technician's free time
    techs = real.get(f"/api/partner/{partner}/technicians").json()
    tech = techs[0]
    r = real.post(f"/api/partner/{partner}/jobs/{case_id}/slots",
                  json={"tech_id": tech["tech_id"], "slots": tech["free_slots"][:2]})
    assert r.status_code == 200, r.text
    p = last(real, LUKA)
    assert p["interactive"]["type"] == "list"
    assert ids(p)[:2] == [f"slot_1:{case_id}", f"slot_2:{case_id}"]

    real.post("/webhooks/whatsapp", json=tap(LUKA, f"slot_1:{case_id}", "Morgen", kind="list_reply"))
    assert real.get(f"/api/staff/cases/{case_id}").json()["status"] == "awaiting_technician"
    r = real.post(f"/api/tech/{tech['tech_id']}/jobs/{case_id}/confirm")
    assert r.status_code == 200, r.text
    assert real.get(f"/api/staff/cases/{case_id}").json()["status"] == "scheduled"
    assert tech["name"] in last(real, LUKA)["text"]["body"]  # tenant told who is coming
    assert "Update" in last(real, JONAS)["text"]["body"]  # neighbour told once the technician confirmed

    # partner completes with photo + invoice → "warm again?" → yes → closed
    r = real.post(f"/api/partner/{partner}/jobs/{case_id}/complete", data={"notes": "Zündelektrode getauscht"},
                  files={"invoice": ("RE-2026-1187.pdf", INVOICE.read_bytes(), "application/pdf")})
    assert r.status_code == 200, r.text
    assert ids(last(real, LUKA)) == [f"fixed_yes:{case_id}", f"fixed_no:{case_id}"]
    real.post("/webhooks/whatsapp", json=tap(LUKA, f"fixed_yes:{case_id}", "Yes, all warm"))
    detail = real.get(f"/api/staff/cases/{case_id}").json()
    assert detail["status"] == "closed"
    assert detail["zero_forms"]["tenant_inputs"]

    outbox = real.get("/webhooks/whatsapp/_outbox").json()["messages"]
    texts = [m["payload"]["text"]["body"] for m in outbox if m["payload"]["type"] == "text"]
    assert not any("on it and I'll get back to you shortly" in t for t in texts), texts  # no filler after taps
    bodies = [m["payload"]["interactive"]["body"]["text"] for m in outbox if m["payload"]["type"] == "interactive"]
    assert all(len(b) <= 1024 for b in bodies)
    consent = next(b for b in bodies if "share your name" in b or "deinen Namen" in b)
    # the question names exactly the consent-required fields of the chosen partner's manifest, and the
    # record stores the same fields (photos only because the tenant sent one), channel and case purpose
    de = "deinen Namen" in consent
    words = {"name": "Namen" if de else "name", "phone": "Telefonnummer" if de else "phone number",
             "address": "Adresse" if de else "address", "photos": "Fotos" if de else "photos",
             "unit_floor": "Stockwerk" if de else "floor"}
    from app import rules
    from app.db import get_session
    from app.models import Consent
    from sqlmodel import select

    with get_session() as s:
        rec = s.exec(select(Consent).where(Consent.case_id == case_id)).one()

    assert rec.channel == "whatsapp" and rec.purpose.startswith("On-site repair visit")
    for f, word in words.items():
        assert (word in consent) == (f in rec.data_shared), (f, consent, rec.data_shared)
    assert "unit_floor" not in rec.data_shared  # not consent-required in heizung-schmidt's manifest


def test_one_room_cold_tip_then_caretaker_no_installer(real, claude):
    """'Just one room' is the radiator, not the boiler: valve/bleeding tip, then the caretaker. No consent
    question, no partner, no job."""
    claude([
        [tool_use("open_case", summary="Heizung kalt im Schlafzimmer", symptoms="ein Raum kalt", error_code=None, priority="normal")],
        [tool_use("ask_buttons", text="Sind alle Heizkörper kalt oder nur einer?",
                  options=[{"id": "cold_all:case_0001", "title": "All cold"},
                           {"id": "cold_some:case_0001", "title": "Just one room"}])],
        [text("ok")],
    ] + [RuntimeError("down")] * 4)
    real.post("/webhooks/whatsapp", json=wa(LUKA, type="text", text={"body": "the bedroom radiator is cold"}))
    real.post("/webhooks/whatsapp", json=tap(LUKA, "cold_some:case_0001", "Just one room"))
    p = last(real, LUKA)
    assert ids(p) == ["oneroom_ok:case_0001", "oneroom_no:case_0001"]
    assert "thermostat" in p["interactive"]["body"]["text"].lower() or "Thermostat" in p["interactive"]["body"]["text"]
    real.post("/webhooks/whatsapp", json=tap(LUKA, "oneroom_no:case_0001", "Still cold"))
    body = last(real, LUKA)["text"]["body"]
    assert "caretaker" in body or "Hausmeister" in body
    detail = real.get("/api/staff/cases/case_0001").json()
    kinds = [e["kind"] for e in detail.get("events", [])]
    assert "caretaker.notified" in kinds and "job.sent" not in kinds and "consent.recorded" not in kinds
    assert not detail.get("partner_id")


def test_llm_context_is_minimised(real):
    """No phone, email, street address, lease or rent goes to the model each turn."""
    import json

    from app.agent import _backend as be
    from app.agent import flow, loop, state

    contact = be.get_contact_by_phone("+" + LUKA)
    conv = state.conversation(be.attr(contact, "id"))
    content = loop.build_user_content(contact, conv, "my heating is cold", [])
    blob = json.dumps(content, ensure_ascii=False)
    full = flow.unit_context_for(contact)
    tenant, lease, prop = full.get("tenant") or {}, full.get("lease") or {}, full.get("property") or {}
    for secret in (be.attr(contact, "phone_e164"), tenant.get("email"), prop.get("address"),
                   *(str(v) for k, v in (lease.get("data") or {}).items() if "rent" in k and v)):
        if secret:
            assert str(secret) not in blob, secret
    assert (lease.get("data") or {}).get("rent_cold_eur")  # the seed has a rent, so the check is real
    assert '"lease"' not in blob and '"tenant"' not in blob and "rent_cold" not in blob
    assert "Luka" in blob and "gas_boiler" in blob  # first name and the boiler stay


def test_boiler_error_writes_tenant_first(real, claude):
    """centrix asset.error_reported → Debye messages the tenant first, code known; 'heating off' goes on to
    the company and consent, 'hot water off' to the diagnosis; a second report doesn't message again."""
    claude([RuntimeError("down")] * 6)
    r = real.post("/demo/trigger/boiler_error", json={"unit_id": "unit_4b", "code": "F28"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["messaged"] and res["code"] == "F.28"
    p = last(real, LUKA)
    body = p["interactive"]["body"]["text"]
    assert "boiler reported a fault (ignition failed, F.28)" in body and "heating or hot water off" in body
    cid = res["case_id"]
    assert ids(p) == [f"aerr_heat:{cid}", f"aerr_water:{cid}", f"aerr_fine:{cid}"]
    detail = real.get(f"/api/staff/cases/{cid}").json()
    assert detail["error_code"] == "F.28"
    assert "asset.error_reported" in [e["kind"] for e in detail.get("events", [])]
    again = real.post("/api/centrix/events", json={"type": "asset.error_reported", "unit_id": "unit_4b",
                                                   "code": "F.28"}).json()
    assert again["duplicate"] and not again["messaged"]
    real.post("/webhooks/whatsapp", json=tap(LUKA, f"aerr_heat:{cid}", "Heating is off"))
    consent = last(real, LUKA)["interactive"]["body"]["text"]
    assert "Is it okay if I share" in consent and "photos" not in consent  # no photos sent


def test_consent_prompt_sent_once_per_turn(real, claude):
    """Two paths reaching the consent question in one turn send it once (simulate.py report turn)."""
    import asyncio

    from app.agent import _backend as be
    from app.agent import flow, state

    claude([RuntimeError("down")] * 4)
    real.post("/webhooks/whatsapp", json=wa(LUKA, type="text", text={"body": "my heating is completely cold"}))
    contact = be.get_contact_by_phone("+" + LUKA)
    conv = state.conversation(be.attr(contact, "id"))
    cid = conv.case_id or asyncio.run(flow.ensure_case(contact, summary="cold", symptoms="cold"))["case_id"]
    asyncio.run(flow.request_consent(contact, cid))
    asyncio.run(flow.request_consent(contact, cid))
    msgs = real.get("/webhooks/whatsapp/_outbox").json()["messages"]
    asks = [m for m in msgs if m["payload"]["type"] == "interactive"
            and any(b["reply"]["id"].startswith("consent_yes") for b in m["payload"]["interactive"]["action"].get("buttons", []))]
    assert len(asks) == 1
