"""Tenant web portal channel ("web"): login, send, Debye's reply, case created, chips, isolation.

Runs against the real app (DB, services), stubbed LLM, fake-send WhatsApp: nothing leaves the machine.
"""
from pathlib import Path

import pytest
from agent_stubs import text, tool_use

REPO = Path(__file__).resolve().parents[3]
PHOTO = REPO / "data" / "demo" / "boiler_display_F28.jpg"


@pytest.fixture
def web(monkeypatch):
    from fastapi.testclient import TestClient

    from app import router as msg_router
    from app.agent import state
    from app.channels import base, web as web_ch, whatsapp
    from app.main import app
    from app.seed import seed

    monkeypatch.setattr(msg_router, "DEBOUNCE_SECONDS", 0)
    monkeypatch.delenv("WEB_MIRROR_WHATSAPP", raising=False)
    with TestClient(app) as c:
        seed(reset=True)
        state.reset_all()
        whatsapp.clear_outbox()
        whatsapp._seen.clear()
        base._last_channel.clear()
        web_ch.frames.clear()
        yield c


def login(c, who="+49 0000 000001"):
    r = c.post("/api/tenant/login", json={"login": who, "password": "anything"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def outbox(c):
    return c.get("/webhooks/whatsapp/_outbox").json()["messages"]


def test_login_by_phone_or_email(web):
    r = web.post("/api/tenant/login", json={"login": "+49 0000 000001", "password": "x"})
    assert r.status_code == 200
    assert r.json()["contact"]["contact_id"] == "c_202"
    assert r.json()["contact"]["first_name"] == "Luka"
    r = web.post("/api/tenant/login", json={"login": "LUKA@example.com", "password": "x"})
    assert r.json()["contact"]["contact_id"] == "c_202"
    r = web.post("/api/tenant/login", json={"login": "0049 0000000002", "password": "x"})
    assert r.json()["contact"]["contact_id"] == "c_203"


def test_login_errors_and_auth(web):
    assert web.post("/api/tenant/login", json={"login": "nobody@example.com", "password": "x"}).status_code == 404
    assert web.post("/api/tenant/login", json={"login": "luka@example.com", "password": ""}).status_code == 400
    # partner staff are not tenants
    assert web.post("/api/tenant/login", json={"login": "+490000000003", "password": "x"}).status_code == 404
    assert web.get("/api/tenant/me").status_code == 401
    assert web.get("/api/tenant/me", headers={"Authorization": "Bearer forged"}).status_code == 401


def test_me_has_home(web):
    h = login(web)
    me = web.get("/api/tenant/me", headers=h).json()
    assert me["contact"]["name"] == "Luka"
    assert me["home"]["unit_id"] == "unit_4b"
    assert "Musterstra" in me["home"]["address"]
    assert any(a["make"] == "Vaillant" for a in me["home"]["assets"])
    assert me["conversation"]["case_id"] is None


def test_send_reply_case_and_chips(web, claude):
    claude([
        [tool_use("open_case", summary="Heating cold, F.28", symptoms="heating completely cold since this morning",
                  error_code="F.28", priority="urgent")],
        [tool_use("ask_buttons", text="Your boiler shows F.28. Are all radiators cold?",
                  options=[{"id": "cold_all:case_0001", "title": "All cold"},
                           {"id": "cold_some:case_0001", "title": "Just one room"}])],
        [text("ok")],
    ])
    h = login(web)
    r = web.post("/api/tenant/messages?wait=1", data={"text": "My heating is completely cold, display says F.28"},
                 headers=h)
    assert r.status_code == 200, r.text

    cases = web.get("/api/tenant/cases", headers=h).json()
    assert len(cases) == 1
    case_id = cases[0]["case_id"]
    me = web.get("/api/tenant/me", headers=h).json()
    assert me["conversation"]["case_id"] == case_id

    hist = web.get("/api/tenant/messages", headers=h).json()
    assert hist["case_id"] == case_id and hist["current"]
    msgs = hist["messages"]
    assert msgs[0]["direction"] == "in" and msgs[0]["channel"] == "web"
    assert "heating is completely cold" in msgs[0]["text"]
    outs = [m for m in msgs if m["direction"] == "out"]
    assert outs and all(m["channel"] == "web" for m in outs)
    q = next(m for m in outs if m["options"])
    assert q["text"] == "Your boiler shows F.28. Are all radiators cold?"  # no "[All cold]" suffix
    assert [o["id"] for o in q["options"]] == ["cold_all:case_0001", "cold_some:case_0001"]
    assert hist["pending"]["options"][0]["title"] == "All cold"

    # the same history is reachable by case id, and the case detail is tenant-safe
    assert web.get(f"/api/tenant/messages?case_id={case_id}", headers=h).json()["messages"] == msgs
    detail = web.get(f"/api/tenant/cases/{case_id}", headers=h).json()
    assert detail["error_code"] == "F.28" and detail["first_channel"] == "web"
    assert "ranking" not in detail and "consents" not in detail

    # nothing went to WhatsApp
    assert outbox(web) == []

    # tapping a chip goes through the same button handler as WhatsApp
    n_before = len(msgs)
    r = web.post("/api/tenant/messages?wait=1", data={"button_id": "cold_all:case_0001", "button_title": "All cold"},
                 headers=h)
    assert r.status_code == 200
    msgs = web.get("/api/tenant/messages", headers=h).json()["messages"]
    assert len(msgs) > n_before + 1
    assert msgs[n_before]["direction"] == "in" and msgs[n_before]["text"] == "All cold"
    assert outbox(web) == []


def test_other_tenant_cannot_read_case(web, claude):
    claude([[tool_use("open_case", summary="Heating cold", symptoms="cold", priority="urgent")], [text("ok")]])
    h = login(web)
    web.post("/api/tenant/messages?wait=1", data={"text": "Heating is cold everywhere"}, headers=h)
    case_id = web.get("/api/tenant/cases", headers=h).json()[0]["case_id"]
    jonas = login(web, "jonas@example.com")
    assert web.get(f"/api/tenant/cases/{case_id}", headers=jonas).status_code == 404
    assert web.get(f"/api/tenant/messages?case_id={case_id}", headers=jonas).status_code == 404
    assert web.get("/api/tenant/cases", headers=jonas).json() == []


@pytest.mark.skipif(not PHOTO.exists(), reason="demo assets missing")
def test_photo_upload(web, claude):
    claude([[text("Thanks for the photo.")]])
    h = login(web)
    r = web.post("/api/tenant/messages?wait=1", data={"text": "this is my boiler"},
                 files={"file": ("display.jpg", PHOTO.read_bytes(), "image/jpeg")}, headers=h)
    assert r.status_code == 200, r.text
    msgs = web.get("/api/tenant/messages", headers=h).json()["messages"]
    first = msgs[0]
    assert first["direction"] == "in" and first["media"] and first["media"][0]["mime"] == "image/jpeg"
    assert web.get(first["media"][0]["url"]).status_code == 200
    # wrong file types are refused
    r = web.post("/api/tenant/messages", files={"file": ("x.exe", b"MZ", "application/x-msdownload")}, headers=h)
    assert r.status_code == 415


def test_empty_message_refused(web):
    h = login(web)
    assert web.post("/api/tenant/messages", data={}, headers=h).status_code == 400


def test_updates_follow_last_channel(web, claude):
    """Once the tenant wrote on the web, later updates (staff/partner via notify) go to the web too."""
    import asyncio

    from app.agent import _backend as be
    from app.agent import outbound

    claude([[text("ok")]])
    h = login(web)
    web.post("/api/tenant/messages?wait=1", data={"text": "hello"}, headers=h)
    from app.agent import state

    case_id = state.conversation("c_202").case_id
    asyncio.run(outbound.text(be.get_contact("c_202"), case_id, "Update from your property manager."))
    msgs = web.get("/api/tenant/messages", headers=h).json()["messages"]
    assert msgs[-1]["text"] == "Update from your property manager." and msgs[-1]["channel"] == "web"
    assert outbox(web) == []


def test_chip_after_restart_lands_in_its_case(web, claude):
    """Agent state is in memory; after a restart a chip tap must still be logged under its case."""
    from app.agent import state

    claude([
        [tool_use("open_case", summary="Heating cold, F.28", symptoms="cold", error_code="F.28", priority="urgent")],
        [tool_use("ask_buttons", text="Are all radiators cold?",
                  options=[{"id": "cold_all:case_0001", "title": "All cold"},
                           {"id": "cold_some:case_0001", "title": "Just one room"}])],
        [text("ok")],
    ])
    h = login(web)
    web.post("/api/tenant/messages?wait=1", data={"text": "My heating is cold, display says F.28"}, headers=h)
    case_id = web.get("/api/tenant/cases", headers=h).json()[0]["case_id"]
    state.reset_all()  # = backend restart

    hist = web.get(f"/api/tenant/messages?case_id={case_id}", headers=h).json()
    assert hist["current"] and [o["title"] for o in hist["pending"]["options"]] == ["All cold", "Just one room"]
    web.post("/api/tenant/messages?wait=1", data={"button_id": f"cold_all:{case_id}", "button_title": "All cold"},
             headers=h)
    msgs = web.get(f"/api/tenant/messages?case_id={case_id}", headers=h).json()["messages"]
    assert any(m["direction"] == "in" and m["text"] == "All cold" for m in msgs)


def test_diagnosis_chips_never_repeat_a_question(web, claude):
    """Tenant-portal report: after 'No' to the hot-water-use chip Debye asked an almost identical
    follow-up. KB v2 asks one merged question; every question is asked at most once, also via chips."""
    claude([RuntimeError("down")] * 20)  # model down: the code policy drives the questions
    h = login(web)
    web.post("/api/tenant/messages?wait=1", data={"text": "My shower is cold"}, headers=h)
    truth = {"q_scope": "everywhere", "q_hot_water_use": "no", "q_radiators": "no", "q_wait_result": "stays_cold",
             "q_switch_check": "all_on", "q_display": "normal"}
    asked = []
    for _ in range(6):
        pending = web.get("/api/tenant/messages", headers=h).json().get("pending") or {}
        diag = [o for o in pending.get("options") or [] if o["id"].startswith("diag:")]
        if not diag:
            break
        qid = diag[0]["id"].split(":")[1]
        asked.append(qid)
        key = truth.get(qid) or diag[0]["id"].split(":")[2]
        chip = next(o for o in diag if o["id"] == f"diag:{qid}:{key}")
        web.post("/api/tenant/messages?wait=1", data={"button_id": chip["id"], "button_title": chip["title"]},
                 headers=h)
    assert asked and len(asked) == len(set(asked)) and len(asked) <= 3
    outs = [m["text"] for m in web.get("/api/tenant/messages", headers=h).json()["messages"] if m["direction"] == "out"]
    assert sum("use hot water" in t or "running at the same time" in t for t in outs) <= 1  # one merged question
    assert outbox(web) == []
