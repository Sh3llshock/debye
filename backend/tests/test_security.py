"""Portal auth (app.auth): signed expiring tokens, role and ownership checks, protected files and stream.

Requests here set the Authorization header explicitly ("" = no token), so the conftest helper that
adds a role token by URL path stays out of the way.
"""
import time

import pytest

NONE = {"Authorization": ""}


def bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def demo(client):
    r = client.post("/demo/scenarios")
    assert r.status_code == 200, r.text
    return {c["scenario"]: c for c in r.json()["cases"]}


def tok(role, sub, pid=None, ttl=None):
    from app import auth

    return auth.make_token(role, sub, pid, ttl)


# ------------------------------------------------------------------ tokens
def test_token_signed_and_expiring(client, monkeypatch):
    from app import auth

    good = auth.make_token("staff", "c_401")
    assert auth.read_token(good).role == "staff"
    body, sig = good.split(".")
    assert auth.read_token(body + "." + sig[:-2] + "AA") is None  # tampered signature
    forged = auth._b64(b'{"exp":9999999999,"role":"staff","sub":"c_401"}') + "." + sig
    assert auth.read_token(forged) is None  # payload changed, old signature
    expired = auth.make_token("staff", "c_401", ttl=-5)
    assert auth.read_token(expired) is None
    # the secret comes from TENANT_TOKEN_SECRET when set
    monkeypatch.setenv("TENANT_TOKEN_SECRET", "another-secret")
    assert auth.read_token(good) is None
    assert client.get("/api/staff/cases", headers=bearer(good)).status_code == 401


def test_login_roles(client):
    def login(who, **kw):
        return client.post("/api/auth/login", json={"login": who, "password": "x", **kw})

    staff = login("anna.becker@example.com").json()
    assert staff["role"] == "staff" and staff["to"] == "/staff"
    partner = login("jobs@heizung-schmidt.example").json()
    assert partner["role"] == "partner" and partner["pid"] == "heizung-schmidt"
    tech = login("tech_ali").json()
    assert tech["role"] == "tech" and tech["pid"] == "heizung-schmidt"
    tenant = login("+49 0000 000001").json()
    assert tenant["role"] == "tenant" and tenant["sub"] == "c_202"
    assert login("nobody@example.com").status_code == 404
    assert client.post("/api/auth/login", json={"login": "anna.becker@example.com", "password": ""}).status_code == 400
    me = client.get("/api/auth/me", headers=bearer(partner["token"])).json()
    assert me == {"role": "partner", "sub": "heizung-schmidt", "pid": "heizung-schmidt"}


# ------------------------------------------------------------------ staff
def test_staff_api_needs_staff(client, demo):
    case_id = next(iter(demo.values()))["case_id"]
    assert client.get("/api/staff/cases", headers=NONE).status_code == 401
    assert client.post(f"/api/staff/cases/{case_id}/approve", headers=NONE).status_code == 401
    assert client.post(f"/api/staff/cases/{case_id}/reject", headers=NONE, json={"reason": "x"}).status_code == 401
    for other in (tok("partner", "heizung-schmidt", "heizung-schmidt"), tok("tenant", "c_202"), tok("tech", "tech_ali")):
        assert client.get("/api/staff/cases", headers=bearer(other)).status_code == 403
        assert client.post(f"/api/staff/cases/{case_id}/approve", headers=bearer(other)).status_code == 403
    assert client.get("/api/partners", headers=bearer(tok("partner", "heizung-schmidt", "heizung-schmidt"))).status_code == 403
    assert client.get("/api/staff/cases", headers=bearer(tok("staff", "c_401"))).status_code == 200


# ------------------------------------------------------------------ partner / technician ownership
def test_partner_only_own_jobs(client, demo):
    schmidt = tok("partner", "heizung-schmidt", "heizung-schmidt")
    wagner = tok("partner", "waerme-wagner", "waerme-wagner")
    jobs = client.get("/api/partner/heizung-schmidt/jobs", headers=bearer(schmidt)).json()
    assert jobs, "scenarios give Heizung Schmidt jobs"
    cid = jobs[0]["case_id"]
    assert client.get("/api/partner/heizung-schmidt/jobs", headers=NONE).status_code == 401
    # another partner can't list, open or act on Schmidt's jobs, not even through its own URL
    assert client.get("/api/partner/heizung-schmidt/jobs", headers=bearer(wagner)).status_code == 403
    assert client.get(f"/api/partner/heizung-schmidt/jobs/{cid}", headers=bearer(wagner)).status_code == 403
    for action in ("accept", "decline"):
        assert client.post(f"/api/partner/heizung-schmidt/jobs/{cid}/{action}", headers=bearer(wagner)).status_code == 403
    assert client.post(f"/api/partner/waerme-wagner/jobs/{cid}/accept", headers=bearer(wagner)).status_code == 404
    # a tenant token is no partner token
    assert client.get("/api/partner/heizung-schmidt/jobs", headers=bearer(tok("tenant", "c_202"))).status_code == 403
    assert client.get(f"/api/partner/heizung-schmidt/jobs/{cid}", headers=bearer(schmidt)).status_code == 200


def test_technician_only_self_or_own_company(client, demo):
    assert client.get("/api/tech/tech_ali/jobs", headers=NONE).status_code == 401
    assert client.get("/api/tech/tech_ali/jobs", headers=bearer(tok("tech", "tech_ali"))).status_code == 200
    assert client.get("/api/tech/tech_ali/jobs", headers=bearer(tok("tech", "tech_jana"))).status_code == 403
    assert client.get("/api/tech/tech_ali/jobs",
                      headers=bearer(tok("partner", "heizung-schmidt", "heizung-schmidt"))).status_code == 200
    assert client.get("/api/tech/tech_ali/jobs",
                      headers=bearer(tok("partner", "elektro-klein", "elektro-klein"))).status_code == 403
    assert client.post("/api/tech/tech_ali/jobs/case_0001/confirm",
                       headers=bearer(tok("tech", "tech_marco"))).status_code == 403


# ------------------------------------------------------------------ files
def _a_document(client):
    from sqlmodel import select

    from app.db import get_session
    from app.models import Case, Document

    with get_session() as s:
        for d in s.exec(select(Document)).all():
            c = s.get(Case, d.case_id) if d.case_id else None
            if c and c.partner_id:
                return d, c
    return None, None


def test_files_need_signed_link_or_access(client, demo):
    from app import auth

    d, case = _a_document(client)
    assert d is not None, "scenarios attach documents to partner cases"
    assert d.id.startswith("doc_") and len(d.id) == 20 and not d.id[4:].isdigit()  # random, not doc_0001
    assert client.get(f"/files/{d.id}", headers=NONE).status_code == 404
    assert client.get(auth.file_url(d.id), headers=NONE).status_code == 200
    exp = int(time.time()) + 600
    assert client.get(f"/files/{d.id}?exp={exp}&sig=wrong", headers=NONE).status_code == 404
    old = int(time.time()) - 5
    assert client.get(f"/files/{d.id}?exp={old}&sig={auth.file_sig(d.id, old)}", headers=NONE).status_code == 404
    # with a token: staff and the case's partner yes, another partner no
    assert client.get(f"/files/{d.id}", headers=bearer(tok("staff", "c_401"))).status_code == 200
    assert client.get(f"/files/{d.id}", headers=bearer(tok("partner", case.partner_id, case.partner_id))).status_code == 200
    other = "elektro-klein" if case.partner_id != "elektro-klein" else "heizung-schmidt"
    assert client.get(f"/files/{d.id}", headers=bearer(tok("partner", other, other))).status_code == 404
    # the API hands out signed links
    detail = client.get(f"/api/staff/cases/{case.id}", headers=bearer(tok("staff", "c_401"))).json()
    urls = [x["url"] for x in detail["documents"]]
    assert urls and all("sig=" in u for u in urls)


# ------------------------------------------------------------------ stream and web chat socket
def test_stream_needs_token(client):
    assert client.get("/api/stream", headers=NONE).status_code == 401


def test_stream_filter():
    from app.auth import Principal, can_see_event

    staff, tenant = Principal("staff", "c_401"), Principal("tenant", "c_202")
    partner = Principal("partner", "heizung-schmidt", "heizung-schmidt")
    mine = {"type": "message.in", "case_id": None, "event": {"contact_id": "c_202"}}
    theirs = {"type": "message.in", "case_id": None, "event": {"contact_id": "c_203"}}
    assert can_see_event(staff, theirs)
    assert can_see_event(tenant, mine) and not can_see_event(tenant, theirs)
    assert not can_see_event(partner, mine)  # partners never get tenants' chat lines
    assert can_see_event(partner, {"type": "demo.reset", "case_id": None, "event": {}})


def test_webchat_socket_needs_own_tenant_token(client):
    from starlette.websockets import WebSocketDisconnect

    for url in ("/ws/chat/c_202", f"/ws/chat/c_202?token={tok('tenant', 'c_203')}",
                f"/ws/chat/c_202?token={tok('staff', 'c_401')}"):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(url) as ws:
                ws.receive_text()
    assert client.get("/chat/<script>").status_code == 404


def test_tenant_token_old_format_rejected(client):
    """Tokens from before this change (unsigned expiry) no longer work."""
    import base64

    old = base64.urlsafe_b64encode(b"c_202.0123456789abcdef0123456789abcdef").decode().rstrip("=")
    assert client.get("/api/tenant/me", headers=bearer(old)).status_code == 401
