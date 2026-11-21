"""Feature 5: website autofill on partner onboarding. No live web: a saved HTML fixture behind an
httpx.MockTransport, a stubbed resolver and a stubbed LLM."""
from pathlib import Path

import httpx
import pytest

from app.partners import onboarding, website

FIX = Path(__file__).parent / "fixtures"
HOME = (FIX / "website_heizung_mueller.html").read_text(encoding="utf-8")
IMPRESSUM = (FIX / "website_heizung_mueller_impressum.html").read_text(encoding="utf-8")


def _site(request: httpx.Request) -> httpx.Response:
    path = request.url.path.rstrip("/") or "/"
    pages = {"/": HOME, "/impressum": IMPRESSUM}
    if path in pages:
        return httpx.Response(200, text=pages[path], headers={"content-type": "text/html; charset=utf-8"})
    return httpx.Response(404, text="not found")


@pytest.fixture()
def fake_web(monkeypatch):
    monkeypatch.setattr(website, "_resolve", lambda host: ["93.184.216.34"])  # a public address
    monkeypatch.setattr(website, "_transport", httpx.MockTransport(_site))


def _str(value, snippet=""):
    return {"value": value, "confidence": 0.9, "source_snippet": snippet or value}


LLM_ANSWER = {
    "name": _str("Heizung Müller GmbH"),
    "street": _str("Jülicher Str. 120"),
    "postcode": _str("52070"),
    "city": _str("Aachen"),
    "phone": _str("0241 000 0199"),
    "email": _str("mailto:info@heizung-mueller.example"),
    "vat_id": _str("DE 123456789"),
    "hwk_no": _str("HWK-AC 12345"),
    "trades": {"value": ["heating", "plumbing", "solar"], "confidence": 0.8, "source_snippet": "Gasthermen"},
    "brands": {"value": ["Vaillant", "Buderus", "Grohe", "Acme"], "confidence": 0.9, "source_snippet": "Vaillant und Buderus"},
    "service_area": {"postcodes": [], "base_postcode": "52070", "radius_km": 20, "confidence": 0.7,
                     "source_snippet": "im Umkreis von 20 km"},
}


def test_ssrf_guard_rejects_local_and_private(client):
    for url in ("http://localhost:8000/api/partners", "http://127.0.0.1/", "localhost", "http://10.1.2.3/",
                "http://169.254.169.254/latest/meta-data", "http://[::1]/", "file:///etc/passwd",
                "ftp://example.com/", "http://debye.localhost/"):
        r = client.post("/api/partners/onboard/from-website", json={"url": url})
        assert r.status_code == 400, (url, r.text)


def test_redirect_to_private_address_is_not_followed(client, monkeypatch):
    monkeypatch.setattr(website, "_resolve", lambda host: ["93.184.216.34"])
    monkeypatch.setattr(website, "_transport", httpx.MockTransport(
        lambda req: httpx.Response(302, headers={"location": "http://127.0.0.1:8000/admin"})))

    async def never(pages):  # pragma: no cover - must not be reached
        raise AssertionError("LLM called without pages")
    monkeypatch.setattr(website, "llm_extract", never)
    out = client.post("/api/partners/onboard/from-website", json={"url": "https://heizung-mueller.example"}).json()
    assert out["fields"] == {} and out["message"]


def test_autofill_from_fixture(client, fake_web, monkeypatch):
    seen = {}

    async def stub(pages):
        seen["urls"] = [p["url"] for p in pages]
        seen["text"] = website._prompt_text(pages)
        return LLM_ANSWER, None
    monkeypatch.setattr(website, "llm_extract", stub)
    before = len(client.get("/api/partners").json())

    r = client.post("/api/partners/onboard/from-website", json={"url": "heizung-mueller.example"})
    assert r.status_code == 200, r.text
    out = r.json()

    # home + impressum fetched (kontakt 404 skipped); HTML stripped, mailto kept, scripts gone
    assert seen["urls"] == ["https://heizung-mueller.example", "https://heizung-mueller.example/impressum"]
    assert "DE123456789" in seen["text"] and "mailto:info@heizung-mueller.example" in seen["text"]
    assert "dataLayer" not in seen["text"] and "<p>" not in seen["text"] and "Heizung & Sanitär" in seen["text"]
    assert out["sources"] == seen["urls"]

    f = out["fields"]
    assert f["name"]["value"] == "Heizung Müller GmbH" and f["name"]["confidence"] == 0.9
    assert f["email"]["value"] == "info@heizung-mueller.example"
    assert f["vat_id"]["value"] == "DE123456789"
    assert f["trades"]["value"] == ["heating", "plumbing"]  # "solar" isn't in the schema
    assert f["brands"]["value"] == ["Vaillant", "Buderus", "Grohe"]  # "Acme" isn't either
    assert f["service_area"]["value"] == {"base_postcode": "52070", "radius_km": 20}
    assert all({"value", "confidence", "source_snippet"} <= set(v) for v in f.values())

    m = out["manifest_draft"]
    assert m["name"] == "Heizung Müller GmbH" and m["capabilities"]["trades"] == ["heating", "plumbing"]
    assert m["service_area"] == {"base_postcode": "52070", "radius_km": 20}
    _, checks = onboarding.validate(m)
    assert onboarding.is_valid(checks), [c for c in checks if not c["ok"]]

    # nothing is saved until the partner submits
    assert len(client.get("/api/partners").json()) == before


def test_without_key_returns_empty_fields(client, fake_web, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    out = client.post("/api/partners/onboard/from-website", json={"url": "https://heizung-mueller.example"}).json()
    assert out["fields"] == {} and "fill in the form" in out["message"]


def test_llm_error_and_garbage_degrade(client, fake_web, monkeypatch):
    async def broken(pages):
        return None, "error"
    monkeypatch.setattr(website, "llm_extract", broken)
    out = client.post("/api/partners/onboard/from-website", json={"url": "https://heizung-mueller.example"}).json()
    assert out["fields"] == {} and out["message"]

    async def garbage(pages):
        return {"name": {"value": None}, "postcode": {"value": "ABC"}, "trades": {"value": ["teleport"]}}, None
    monkeypatch.setattr(website, "llm_extract", garbage)
    out = client.post("/api/partners/onboard/from-website", json={"url": "https://heizung-mueller.example"}).json()
    assert out["fields"] == {} and out["manifest_draft"] is None and out["message"]
