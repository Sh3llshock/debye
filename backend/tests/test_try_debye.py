"""/tryDebye: register a phone as a demo tenant; it survives a demo reset."""
from app import services, try_api


def test_register_and_survive_reset(client, tmp_path, monkeypatch):
    monkeypatch.setattr(try_api, "signups_path", lambda: tmp_path / "try.local.json")
    r = client.post("/api/try/register", json={"name": "Anna", "phone": "+49 151 2345 6789", "consent": True})
    assert r.status_code == 200, r.text
    assert "wa.me/31682886557" in r.json()["wa_link"]
    c = services.get_contact_by_phone("+4915123456789")
    assert c and c.role == "tenant" and c.unit_id == try_api.TRY_UNIT_ID and c.name == "Anna"
    client.post("/demo/reset")
    assert services.get_contact_by_phone("+4915123456789") is not None


def test_register_validation(client, tmp_path, monkeypatch):
    monkeypatch.setattr(try_api, "signups_path", lambda: tmp_path / "try.local.json")
    assert client.post("/api/try/register", json={"name": "A", "phone": "0151 234", "consent": True}).status_code == 422
    assert client.post("/api/try/register", json={"name": "A", "phone": "+4915123456789"}).status_code == 422
    assert client.post("/api/try/register", json={"name": "", "phone": "+4915123456789", "consent": True}).status_code == 422
    assert try_api.normalize("0049 151-2345 6789") == "+4915123456789"
