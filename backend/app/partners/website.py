"""Website autofill for partner onboarding (POST /api/partners/onboard/from-website).

A partner types their website; we fetch it (plus /impressum and /kontakt, where German companies
publish address, VAT id and chamber number), strip it to text and ask the LLM for the join-form fields
as strict JSON. Trades and brands are limited to the values in onboarding.schema(). Nothing is saved:
the form is pre-filled and the partner reviews everything before submitting.

SSRF guard: only http/https, every hop of a redirect is re-checked, and hosts that resolve to private,
loopback, link-local or reserved addresses are refused. Pages are capped at ~500 KB and 10 s.
"""
from __future__ import annotations

import html
import ipaddress
import logging
import os
import re
import socket
import time
from typing import Literal, Optional
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel, Field

from . import onboarding

log = logging.getLogger("debye.website")

TIMEOUT_S = 10.0
MAX_BYTES = 500_000
MAX_REDIRECTS = 5
MAX_TEXT_PER_PAGE = 12_000
SUBPAGES = ("/impressum", "/kontakt")
USER_AGENT = "DebyePartnerOnboarding/0.1 (+website autofill; fetches only the URL a partner entered)"

TRADE_IDS = tuple(onboarding.TRADES)
BRAND_IDS = tuple(sorted({b for t in onboarding.TRADES.values() for b in t["brands"]}))
TradeId = Literal[TRADE_IDS]  # type: ignore[valid-type]
BrandId = Literal[BRAND_IDS]  # type: ignore[valid-type]

STR_FIELDS = ("name", "street", "postcode", "city", "phone", "email", "vat_id", "hwk_no")


class BlockedUrl(ValueError):
    """The URL is not allowed (bad scheme, private address, unresolvable host)."""


# ---------------------------------------------------------------- SSRF guard + fetch
def _resolve(host: str) -> list[str]:
    """All addresses a host resolves to (monkeypatched in tests; no live DNS there)."""
    return sorted({ai[4][0] for ai in socket.getaddrinfo(host, None)})


def _ip_blocked(ip: str) -> bool:
    a = ipaddress.ip_address(ip.split("%")[0])
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped
    return (a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast
            or a.is_unspecified or not a.is_global)


def normalize_url(raw: str) -> str:
    url = (raw or "").strip()
    if not url:
        raise BlockedUrl("Enter your website address")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    return url


def check_url(url: str) -> str:
    """Raises BlockedUrl unless the URL is http(s) on a public host. Returns the URL."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise BlockedUrl("Only http and https websites can be read")
    host = (parts.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise BlockedUrl("That doesn't look like a website address")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise BlockedUrl("Local addresses can't be read")
    try:
        ips = [host] if _is_ip(host) else _resolve(host)
    except (socket.gaierror, UnicodeError, OSError):
        raise BlockedUrl(f"Couldn't find {host}") from None
    if not ips or any(_ip_blocked(ip) for ip in ips):
        raise BlockedUrl("Private or local network addresses can't be read")
    return url


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


_transport: httpx.AsyncBaseTransport | None = None  # tests plug in an httpx.MockTransport


async def fetch(url: str) -> tuple[str, str]:
    """GET with manual redirects (each hop re-checked). Returns (final_url, html). Raises on failure."""
    async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False, transport=_transport,
                                 headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.5"}) as client:
        for _hop in range(MAX_REDIRECTS + 1):
            check_url(url)
            async with client.stream("GET", url) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    continue
                if r.status_code >= 400:
                    raise httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
                ctype = r.headers.get("content-type", "")
                if ctype and "html" not in ctype and "text" not in ctype:
                    raise ValueError(f"not a web page ({ctype})")
                body = bytearray()
                async for chunk in r.aiter_bytes():
                    body += chunk
                    if len(body) >= MAX_BYTES:
                        break
                enc = r.encoding or "utf-8"
                return url, bytes(body[:MAX_BYTES]).decode(enc, errors="replace")
        raise ValueError("too many redirects")


def html_to_text(doc: str) -> str:
    """Readable text from HTML; mailto:/tel: links are kept because the address is often only in the href."""
    links = re.findall(r'href=["\'](mailto:[^"\'?]+|tel:[^"\']+)', doc, flags=re.I)
    doc = re.sub(r"(?is)<(script|style|noscript|svg|template)\b.*?</\1>", " ", doc)
    doc = re.sub(r"(?s)<!--.*?-->", " ", doc)
    doc = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h[1-6]|section|footer|address)>", "\n", doc)
    doc = re.sub(r"(?s)<[^>]+>", " ", doc)
    text = html.unescape(doc)
    text = re.sub(r"[ \t\r\f\v ]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    if links:
        text += "\nLinks: " + " ".join(dict.fromkeys(links))
    return text


async def fetch_site(url: str) -> list[dict]:
    """The page the partner entered plus /impressum and /kontakt on the same host.
    Returns [{url, text}] for every page that loaded. BlockedUrl propagates for the entered URL."""
    check_url(url)
    parts = urlsplit(url)
    root = f"{parts.scheme}://{parts.netloc}"
    candidates = [url] + [root + p for p in SUBPAGES if urlsplit(url).path.rstrip("/") != p]
    pages, seen = [], set()
    for u in candidates:
        try:
            final, doc = await fetch(u)
        except BlockedUrl as e:
            log.info("website autofill: %s blocked (%s)", u, e)
            continue
        except Exception as e:  # 404 impressum, timeouts, TLS errors … just skip that page
            log.info("website autofill: %s not loaded (%s)", u, e)
            continue
        if final in seen:
            continue
        seen.add(final)
        pages.append({"url": final, "text": html_to_text(doc)[:MAX_TEXT_PER_PAGE]})
    return pages


# ---------------------------------------------------------------- LLM extraction (strict JSON)
class StrField(BaseModel):
    value: Optional[str] = Field(description="Exactly as on the website; null if not stated")
    confidence: float = Field(description="0..1")
    source_snippet: str = Field(description="Short verbatim quote (max ~120 chars) where it was found; '' if null")


class TradesField(BaseModel):
    value: list[TradeId]
    confidence: float
    source_snippet: str


class BrandsField(BaseModel):
    value: list[BrandId]
    confidence: float
    source_snippet: str


class AreaField(BaseModel):
    postcodes: list[str] = Field(description="5-digit German postcodes named as the service area; [] if none")
    base_postcode: Optional[str] = Field(description="Postcode the radius is around (usually the company's)")
    radius_km: Optional[int] = Field(description="Radius in km if the site states one, else null")
    confidence: float
    source_snippet: str


class Extraction(BaseModel):
    name: StrField = Field(description="Company name incl. legal form, e.g. 'Heizung Müller GmbH'")
    street: StrField = Field(description="Street and house number")
    postcode: StrField
    city: StrField
    phone: StrField
    email: StrField
    vat_id: StrField = Field(description="USt-IdNr., e.g. DE123456789")
    hwk_no: StrField = Field(description="Handwerkskammer / Handwerksrolle registration number")
    trades: TradesField
    brands: BrandsField
    service_area: AreaField


SYSTEM_PROMPT = (
    "You read a German tradesperson's website (home page, Impressum, Kontakt) and fill a partner sign-up form. "
    "Only use facts stated in the text; never guess. Use null and confidence 0 for anything not stated. "
    "trades: only from this list, mapped from the services they describe: {trades}. "
    "brands: only manufacturers from this list that they say they install, service or are certified for: {brands}. "
    "service_area: postcodes or a radius only if the site states its area; otherwise base_postcode = the "
    "company postcode and radius_km null. source_snippet: a short verbatim quote from the text."
)


def _llm_provider() -> str:
    return (os.getenv("LLM_PROVIDER") or "openai").strip().lower()


def _prompt_text(pages: list[dict]) -> str:
    return "\n\n".join(f"=== {p['url']} ===\n{p['text']}" for p in pages)


async def llm_extract(pages: list[dict]) -> tuple[dict | None, str | None]:
    """→ (raw Extraction dict, None) or (None, reason). Never raises."""
    system = SYSTEM_PROMPT.format(trades=", ".join(TRADE_IDS), brands=", ".join(BRAND_IDS))
    text = _prompt_text(pages)
    try:
        if _llm_provider() == "anthropic":
            if not os.getenv("ANTHROPIC_API_KEY"):
                return None, "no_key"
            import anthropic

            from app.media import MODEL

            client = anthropic.AsyncAnthropic(timeout=30)
            r = await client.messages.parse(model=MODEL, max_tokens=3000, system=system,
                                            messages=[{"role": "user", "content": text}], output_format=Extraction)
            if r.stop_reason == "refusal" or r.parsed_output is None:
                return None, "no_result"
            return r.parsed_output.model_dump(), None
        if not os.getenv("OPENAI_API_KEY"):
            return None, "no_key"
        from openai import AsyncOpenAI

        from app.media import openai_base_url

        extra = {}
        effort = os.getenv("OPENAI_ONBOARD_REASONING_EFFORT", "low")
        if effort:
            extra["reasoning_effort"] = effort
        client = AsyncOpenAI(base_url=openai_base_url(), timeout=30, max_retries=1)
        t0 = time.perf_counter()
        r = await client.chat.completions.parse(
            model=os.getenv("OPENAI_CHAT_MODEL") or "gpt-6-luna",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
            response_format=Extraction, **extra)
        msg = r.choices[0].message
        if getattr(msg, "refusal", None) or msg.parsed is None:
            return None, "no_result"
        log.info("website autofill extracted in %.2fs", time.perf_counter() - t0)
        return msg.parsed.model_dump(), None
    except Exception:
        log.exception("website autofill extraction failed")
        return None, "error"


# ---------------------------------------------------------------- clean-up + manifest draft
def _conf(x) -> float:
    try:
        return round(max(0.0, min(1.0, float(x))), 2)
    except (TypeError, ValueError):
        return 0.0


def _snip(s) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s[:160]


_CHECKS = {
    "postcode": lambda v: re.fullmatch(r"\d{5}", v),
    "email": lambda v: re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v),
    "vat_id": lambda v: re.fullmatch(r"[A-Z]{2}[A-Z0-9]{8,12}", v),
    "phone": lambda v: len(re.sub(r"\D", "", v)) >= 6,
}


def clean(raw: dict) -> dict:
    """Extraction → {key: {value, confidence, source_snippet}} with only plausible, allowed values."""
    fields: dict[str, dict] = {}
    for k in STR_FIELDS:
        f = raw.get(k) or {}
        v = f.get("value")
        if not isinstance(v, str) or not v.strip():
            continue
        v = re.sub(r"\s+", " ", v).strip()
        if k == "vat_id":
            v = v.replace(" ", "").upper()
        if k == "email":
            v = v.removeprefix("mailto:")
        if k in _CHECKS and not _CHECKS[k](v):
            continue
        fields[k] = {"value": v, "confidence": _conf(f.get("confidence")), "source_snippet": _snip(f.get("source_snippet"))}
    for k, allowed in (("trades", TRADE_IDS), ("brands", BRAND_IDS)):
        f = raw.get(k) or {}
        vals = [x for x in dict.fromkeys(f.get("value") or []) if x in allowed]
        if vals:
            fields[k] = {"value": vals, "confidence": _conf(f.get("confidence")), "source_snippet": _snip(f.get("source_snippet"))}
    a = raw.get("service_area") or {}
    pcs = [p for p in dict.fromkeys(str(x).strip() for x in a.get("postcodes") or []) if re.fullmatch(r"\d{5}", p)]
    base = str(a.get("base_postcode") or "").strip() or (fields.get("postcode") or {}).get("value", "")
    radius = a.get("radius_km") if isinstance(a.get("radius_km"), int) and 0 < a["radius_km"] <= 300 else None
    area: dict = {}
    if pcs:
        area["postcodes"] = pcs
    elif re.fullmatch(r"\d{5}", base or ""):
        area["base_postcode"] = base
        if radius:
            area["radius_km"] = radius
    if area:
        fields["service_area"] = {"value": area, "confidence": _conf(a.get("confidence")), "source_snippet": _snip(a.get("source_snippet"))}
    return fields


def manifest_draft(fields: dict) -> dict | None:
    name = (fields.get("name") or {}).get("value")
    if not name:
        return None
    area = (fields.get("service_area") or {}).get("value") or {}
    form = {"name": name, "trades": (fields.get("trades") or {}).get("value") or ["heating"],
            "brands": (fields.get("brands") or {}).get("value") or []}
    if area.get("postcodes"):
        form["postcodes"] = area["postcodes"]
    elif area.get("base_postcode"):
        form["base_postcode"] = area["base_postcode"]
        form["radius_km"] = area.get("radius_km") or 15
    return onboarding.build_manifest(form)


MESSAGES = {
    "no_key": "Website autofill isn't switched on here. Please fill in the form.",
    "no_pages": "We couldn't open that website. Check the address or fill in the form.",
    "no_result": "We couldn't read your details from the website. Please fill in the form.",
    "error": "We couldn't read your details from the website. Please fill in the form.",
    "empty": "We didn't find your company details on the website. Please fill in the form.",
}


async def autofill(raw_url: str) -> dict:
    """The whole flow. BlockedUrl propagates (→ 400); everything else degrades to {fields: {}, message}."""
    url = check_url(normalize_url(raw_url))
    pages = await fetch_site(url)
    sources = [p["url"] for p in pages]
    if not pages:
        return {"fields": {}, "manifest_draft": None, "sources": [], "message": MESSAGES["no_pages"]}
    raw, why = await llm_extract(pages)
    if raw is None:
        return {"fields": {}, "manifest_draft": None, "sources": sources, "message": MESSAGES[why or "error"]}
    try:
        fields = clean(raw)
        draft = manifest_draft(fields)
    except Exception:
        log.exception("website autofill clean-up failed")
        return {"fields": {}, "manifest_draft": None, "sources": sources, "message": MESSAGES["error"]}
    out = {"fields": fields, "manifest_draft": draft, "sources": sources}
    if not fields:
        out["message"] = MESSAGES["empty"]
    log.info("website autofill: %d field(s) from %s", len(fields), ", ".join(sources))
    return out
