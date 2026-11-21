"""Order handover per manifest.transport (connector-spec §4).

- "portal": nothing to send; the partner works in the centrix partner page (unchanged behaviour).
- "api": POST {base_url}/orders, body signed with HMAC-SHA256 (header X-Centrix-Signature:
  sha256=<hex>) using the secret in the env var named by transport.auth.secret_env. The partner
  answers {partner_order_id, status} and reports every later state to the events webhook
  (partner_events_api.py), signed with the same secret.
- "conversational": not sent from here (WhatsApp/email job cards are planned).

Only consented required_context fields leave centrix: fields with consent_required are sent only
when the tenant agreed to share them with this partner for this case.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import timedelta

import httpx

from .. import rules
from ..config import now, now_iso
from .manifest import Manifest

log = logging.getLogger("debye.transport")

SIGNATURE_HEADER = "X-Centrix-Signature"
TIMEOUT_S = 4.0

# Tests swap this for an httpx.MockTransport-backed client.
client_factory = lambda: httpx.Client(timeout=TIMEOUT_S)  # noqa: E731


class TransportError(Exception):
    pass


# --------------------------------------------------------------------------- signing

def secret_for(manifest: Manifest | dict) -> str | None:
    t = (manifest.transport if isinstance(manifest, Manifest) else manifest.get("transport")) or {}
    env = ((t.get("auth") or {}).get("secret_env") or "").strip()
    return (os.getenv(env) or None) if env else None


def sign(raw: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def verify(raw: bytes, header: str | None, secret: str | None) -> bool:
    if not secret or not header:
        return False
    return hmac.compare_digest(sign(raw, secret), header.strip())


def order_ref(case_id: str) -> str:
    return f"ord_{case_id}"


# --------------------------------------------------------------------------- context

def _source_value(s, src: str, case, prop, unit, asset, tenant):
    from ..models import Document
    from sqlmodel import select
    src = (src or "").strip()
    if src.startswith("case.documents"):
        kind = src.split("kind=")[-1].rstrip("]") if "kind=" in src else None
        docs = s.exec(select(Document).where(Document.case_id == case.id)).all()
        return [{"kind": d.kind, "filename": d.filename, "mime": d.mime, "url": f"/files/{d.id}"}
                for d in docs if kind is None or d.kind == kind]
    obj_name, _, attr = src.partition(".")
    obj = {"property": prop, "unit": unit, "asset": asset, "tenant": tenant, "case": case}.get(obj_name)
    if obj is None:
        return None
    if not attr:
        if obj_name == "asset":
            return {"type": obj.type, "make": obj.make, "model": obj.model, "installed": obj.installed}
        return None
    attr = {"phone": "phone_e164"}.get(attr, attr) if obj_name == "tenant" else attr
    return getattr(obj, attr, None)


def build_context(s, case, manifest: Manifest, consented: set[str]) -> dict:
    """required_context → {key: value}; consent-required keys only if consented."""
    from ..models import Asset, Contact, Property, Unit
    prop = s.get(Property, case.property_id) if case.property_id else None
    unit = s.get(Unit, case.unit_id) if case.unit_id else None
    asset = s.get(Asset, case.asset_id) if case.asset_id else None
    tenant = s.get(Contact, case.reporter_contact_id) if case.reporter_contact_id else None
    out = {}
    for f in manifest.required_context:
        if f.consent_required and rules.norm_field(f.key) not in consented:
            continue
        out[f.key] = _source_value(s, f.source, case, prop, unit, asset, tenant)
    return out


def slot_hints(days_ahead: int = 1) -> list[dict]:
    """Suggested windows on the next working day (demo clock), so a partner system without a
    calendar sync can offer times centrix can book: 08–10 and 14–16."""
    d = now() + timedelta(days=days_ahead)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    out = []
    for h0, h1 in ((8, 10), (14, 16)):
        st = d.replace(hour=h0, minute=0, second=0, microsecond=0)
        en = d.replace(hour=h1, minute=0, second=0, microsecond=0)
        out.append({"start": st.isoformat(timespec="seconds"), "end": en.isoformat(timespec="seconds")})
    return out


def build_order(s, case, manifest: Manifest, offer_id: str | None = None) -> dict:
    """The POST {base_url}/orders body (connector-spec §4)."""
    from ..models import Consent
    from sqlmodel import select
    from .. import services
    consents = s.exec(select(Consent).where(Consent.case_id == case.id,
                                            Consent.partner_id == manifest.partner_id,
                                            Consent.revoked_at == None)  # noqa: E711
                      .order_by(Consent.given_at.desc())).all()
    consented = {rules.norm_field(f) for c in consents for f in c.data_shared}
    latest = consents[0] if consents else None
    body = {
        "order_ref": order_ref(case.id),
        "partner_id": manifest.partner_id,
        "case": {"case_id": case.id, "type": case.type, "title": case.title,
                 "summary": case.summary, "error_code": case.error_code},
        "trade": services.case_trade(case),
        "priority": case.priority,
        "cost_cap_eur": case.estimated_cost_eur,
        "context": build_context(s, case, manifest, consented),
        "consent": ({"data_shared": sorted(consented), "given_at": latest.given_at,
                     "channel": latest.channel, "purpose": latest.purpose} if latest else None),
        "events_webhook": f"/api/partners/{manifest.partner_id}/events",
        "sent_at": now_iso(),
    }
    if manifest.kind == "deliver":
        body["slot_hints"] = slot_hints()
    if offer_id:
        body["offer_id"] = offer_id
    return body


# --------------------------------------------------------------------------- send

def post_order(manifest: Manifest, body: dict) -> dict:
    """Signed POST; returns the partner's JSON answer. Raises TransportError."""
    t = manifest.transport or {}
    base = (t.get("base_url") or "").rstrip("/")
    if not base:
        raise TransportError("transport.base_url missing")
    secret = secret_for(manifest)
    if not secret:
        env = (t.get("auth") or {}).get("secret_env") or "?"
        raise TransportError(f"secret {env} not set")
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json", SIGNATURE_HEADER: sign(raw, secret)}
    try:
        with client_factory() as c:
            r = c.post(f"{base}/orders", content=raw, headers=headers)
    except httpx.HTTPError as e:
        raise TransportError(f"{base} unreachable ({type(e).__name__})") from e
    if r.status_code >= 300:
        raise TransportError(f"{base}/orders answered {r.status_code}")
    try:
        return r.json() if r.content else {}
    except ValueError:
        return {}


def send_order(manifest: Manifest | dict, case_id: str, offer_id: str | None = None) -> dict | None:
    """Hand the order to the partner per transport.type. Never raises: a failed API handover is
    recorded on the case (job.send_failed) so staff see it; the case stays with the partner.
    Returns the stored partner_order for "api", None for portal/conversational."""
    from ..db import get_session
    from ..events import record_event
    from ..models import Case
    m = manifest if isinstance(manifest, Manifest) else Manifest.model_validate(manifest)
    ttype = (m.transport or {}).get("type")
    if ttype != "api":
        return None  # portal: the partner page shows the job; conversational: planned
    with get_session() as s:
        case = s.get(Case, case_id)
        body = build_order(s, case, m, offer_id)
    initial = "offered" if m.kind == "sell" else "requested"
    order = {"order_ref": body["order_ref"], "partner_order_id": None, "status": initial,
             "transport": "api", "sent_at": body["sent_at"], "context_keys": sorted(body["context"])}
    try:
        answer = post_order(m, body)
        order["partner_order_id"] = answer.get("partner_order_id")
        error = None
    except TransportError as e:
        error = str(e)
        order["error"] = error
        log.warning("order %s to %s failed: %s", body["order_ref"], m.partner_id, error)
    with get_session() as s:
        case = s.get(Case, case_id)
        case.data = {**(case.data or {}), "partner_order": order}
        case.updated_at = now_iso()
        s.add(case)
        s.commit()
    if error:
        record_event(case_id, "system", "job.send_failed",
                     f"Order to {m.name} not delivered: {error}",
                     {"partner_id": m.partner_id, "order_ref": order["order_ref"], "error": error})
    else:
        record_event(case_id, "system", "order.sent",
                     f"Order {order['order_ref']} sent to {m.name} via API"
                     + (f" (their ref {order['partner_order_id']})" if order["partner_order_id"] else ""),
                     {"partner_id": m.partner_id, "order_ref": order["order_ref"],
                      "partner_order_id": order["partner_order_id"],
                      "context_keys": order["context_keys"]})
    return order
