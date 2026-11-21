"""One-click staff links from the approval email: signed, expiring, single-case tokens.

Token = base64url(json {c: case_id, a: action, p: partner_id, exp}) + "." + base64url(HMAC-SHA256).
Secret: EMAIL_LINK_SECRET, else random per process (links then die on restart, which is fine).
Actions: confirm | reject | info. Confirm and reject are idempotent: the case state decides,
so a second click (or an outdated email after a redispatch) shows a friendly page, never a second job.

Routes (no login):
  GET  /a/{token}                       landing page (confirm auto-submits, reject asks for a reason,
                                        info redirects to /staff/cases/<id>)
  POST /api/email-actions/{token}/confirm
  POST /api/email-actions/{token}/reject   (form field: reason)
Confirm is a POST so link scanners that prefetch GET links (Outlook, Gmail) cannot approve a job.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import logging
import secrets
import time

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from . import notify, rules, services
from .config import settings
from .events import record_event

log = logging.getLogger("debye.email_links")

ACTIONS = ("confirm", "reject", "info")
_PROCESS_SECRET = secrets.token_bytes(32)


class TokenError(Exception):
    def __init__(self, reason: str):  # "invalid" | "expired"
        super().__init__(reason)
        self.reason = reason


def _secret() -> bytes:
    return settings.email_link_secret.encode() if settings.email_link_secret else _PROCESS_SECRET


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(case_id: str, action: str, partner_id: str | None = None,
               ttl_hours: float | None = None, now: float | None = None) -> str:
    if action not in ACTIONS:
        raise ValueError(action)
    ttl = settings.email_link_ttl_hours if ttl_hours is None else ttl_hours
    exp = int((now if now is not None else time.time()) + ttl * 3600)
    body = _b64(json.dumps({"c": case_id, "a": action, "p": partner_id, "exp": exp},
                           separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_token(token: str, now: float | None = None) -> dict:
    """{"c", "a", "p", "exp"} or TokenError("invalid" | "expired")."""
    try:
        body, sig = token.split(".", 1)
        want = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, want):
            raise TokenError("invalid")
        data = json.loads(_unb64(body))
    except TokenError:
        raise
    except Exception:
        raise TokenError("invalid")
    if not isinstance(data, dict) or data.get("a") not in ACTIONS or not data.get("c"):
        raise TokenError("invalid")
    if int(data.get("exp", 0)) < (now if now is not None else time.time()):
        raise TokenError("expired")
    return data


def links(case_id: str, partner_id: str | None) -> dict:
    base = settings.public_base_url.rstrip("/")
    return {a: f"{base}/a/{make_token(case_id, a, partner_id)}" for a in ACTIONS}


def staff_case_url(case_id: str, token: str | None = None) -> str:
    return f"{settings.public_base_url.rstrip('/')}/staff/cases/{case_id}" + (f"?t={token}" if token else "")


# --------------------------------------------------------------------------- pages

_CSS = """
body{margin:0;background:#FAF8F5;color:#2B1018;font:16px/1.5 -apple-system,'Segoe UI',Roboto,Arial,sans-serif}
.wrap{max-width:480px;margin:0 auto;padding:48px 16px}
.card{background:#FDFCFA;border:1px solid rgba(74,20,36,.10);border-radius:14px;padding:28px 24px}
.brand{color:#6B1F33;font-weight:700;letter-spacing:.02em;margin-bottom:20px}
h1{font-size:22px;line-height:1.3;margin:0 0 10px}
p{color:#5A4744;margin:0 0 14px}
.ok{color:#2F7D4F}.warn{color:#B04A12}
a.btn,button{display:inline-block;border:0;border-radius:10px;padding:12px 18px;font:600 15px/1 inherit;
  cursor:pointer;text-decoration:none;background:#6B1F33;color:#fff}
a.sec{background:#EFE8DF;color:#2B1018}
textarea{width:100%;box-sizing:border-box;min-height:90px;border:1px solid #E2D8CB;border-radius:10px;
  padding:10px;font:inherit;margin:4px 0 14px;background:#fff}
label{font-weight:600;font-size:14px}
"""


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)} · Debye</title><style>{_CSS}</style></head>"
        f"<body><div class='wrap'><div class='card'><div class='brand'>Debye · reltix</div>"
        f"{body}</div></div></body></html>", status_code=status)


def _staff_link(case_id: str | None) -> str:
    url = staff_case_url(case_id) if case_id else f"{settings.public_base_url.rstrip('/')}/staff/cases"
    return f"<p><a class='btn sec' href='{html.escape(url)}'>Open the staff page</a></p>"


def _token_problem(reason: str) -> HTMLResponse:
    if reason == "expired":
        return _page("Link expired", "<h1>This link has expired</h1><p>Approval links are valid for "
                     f"{settings.email_link_ttl_hours:g} hours. You can still decide on the staff page.</p>"
                     + _staff_link(None), 410)
    return _page("Link not valid", "<h1>This link is not valid</h1><p>It may be incomplete or from an "
                 "older server. You can still decide on the staff page.</p>" + _staff_link(None), 400)


def _partner_name(partner_id: str | None) -> str:
    m = services.get_partner_manifest(partner_id) if partner_id else None
    return (m.name if m else None) or partner_id or "the partner"


def _state_check(tok: dict):
    """None if the case is still waiting for this email's decision, else a friendly page."""
    case = services.get_case(tok["c"])
    if case is None:
        return _page("Case not found", "<h1>Case not found</h1><p>The case may have been removed "
                     "(e.g. a demo reset).</p>" + _staff_link(None), 404)
    appr = (case.data or {}).get("approval") or {}
    pending = (case.data or {}).get("pending_partner_id")
    if case.status in ("approval_pending", "awaiting_approval"):
        if tok.get("p") and pending and pending != tok["p"]:
            return _page("Outdated email", f"<h1>This email is outdated</h1><p>The job now waits for "
                         f"approval for {html.escape(_partner_name(pending))}. A newer email was sent; "
                         "you can also decide on the staff page.</p>" + _staff_link(case.id), 409)
        return None
    if case.status == "rejected" or appr.get("rejected"):
        who = appr.get("rejected_by") or "staff"
        return _page("Already rejected", f"<h1>Already decided</h1><p>{html.escape(who)} rejected this job. "
                     "Nothing was sent to the partner.</p>" + _staff_link(case.id))
    if appr.get("granted"):
        who = appr.get("granted_by") or "staff"
        return _page("Already approved", f"<h1 class='ok'>Already approved</h1><p>{html.escape(who)} "
                     f"approved this job. {html.escape(_partner_name(case.partner_id or tok.get('p')))} "
                     "has been asked.</p>" + _staff_link(case.id))
    return _page("No longer waiting", f"<h1>Nothing to decide</h1><p>This case is no longer waiting for "
                 f"approval (status: {html.escape(case.status)}).</p>" + _staff_link(case.id))


router = APIRouter(tags=["email-actions"])


@router.get("/api/email-actions/preview/{case_id}", include_in_schema=False)
def preview(case_id: str, format: str = "html"):
    """DEMO_MODE only: what the approval email for this case looks like (links are dead '#')."""
    from fastapi import HTTPException
    from fastapi.responses import PlainTextResponse

    from . import notify_email
    if not settings.demo_mode:
        raise HTTPException(404, "not found")
    try:
        msg = notify_email.render(case_id, {a: "#" for a in ACTIONS})
    except services.NotFound:
        raise HTTPException(404, f"case {case_id} not found")
    if format == "text":
        return PlainTextResponse(f"Subject: {msg['subject']}\n\n{msg['text']}")
    return HTMLResponse(msg["html"])


@router.get("/a/{token}", include_in_schema=False)
def landing(token: str):
    try:
        tok = verify_token(token)
    except TokenError as e:
        return _token_problem(e.reason)
    if tok["a"] == "info":
        return RedirectResponse(f"/staff/cases/{tok['c']}?t={token}", status_code=303)
    problem = _state_check(tok)
    if problem:
        return problem
    action = f"/api/email-actions/{html.escape(token)}/{tok['a']}"
    partner = html.escape(_partner_name(tok.get("p")))
    if tok["a"] == "confirm":
        # auto-submits in a browser (one click for the PM); prefetching scanners don't run JS
        return _page("Approve job", f"<h1>Approve the job for {partner}?</h1>"
                     f"<form id='f' method='post' action='{action}'><p>Approving…</p>"
                     f"<button type='submit'>Approve and book {partner}</button></form>"
                     "<script>document.getElementById('f').submit()</script>")
    return _page("Reject job", f"<h1>Don't send {partner}</h1><p>The partner will not be contacted. "
                 "Debye tells the tenant that the property manager takes over.</p>"
                 f"<form method='post' action='{action}'><label for='r'>Reason (optional)</label>"
                 "<textarea id='r' name='reason' maxlength='500' "
                 "placeholder='e.g. caretaker checks it tomorrow'></textarea>"
                 "<button type='submit'>Reject the job</button></form>")


def _verify_for(token: str, action: str):
    try:
        tok = verify_token(token)
    except TokenError as e:
        return None, _token_problem(e.reason)
    if tok["a"] != action:
        return None, _token_problem("invalid")
    return tok, _state_check(tok)


@router.post("/api/email-actions/{token}/confirm", include_in_schema=False)
async def confirm(token: str):
    tok, problem = _verify_for(token, "confirm")
    if problem:
        return problem
    case_id = tok["c"]
    try:
        result = services.approve_case(case_id, actor="staff")
    except rules.RuleViolation as rv:
        return _page("Could not approve", f"<h1 class='warn'>Could not approve</h1><p>{html.escape(rv.message)}</p>"
                     + _staff_link(case_id), 409)
    record_event(case_id, "staff", "staff.email_approved", "Approved by email",
                 {"partner_id": tok.get("p"), "partner_name": result.get("partner_name")})
    await notify.notify_tenant(case_id, "approval_granted",
                               {"partner_name": result.get("partner_name"),
                                "dispatched": result.get("dispatched")})
    offer = services.auto_offer_slots(case_id)  # times from the technician's calendar → tenant
    if offer:
        await notify.notify_tenant(case_id, "slots_proposed", offer)
    name = html.escape(result.get("partner_name") or _partner_name(tok.get("p")))
    return _page("Approved", f"<h1 class='ok'>Approved. {name} is being booked.</h1>"
                 "<p>Debye sends the job now and tells the tenant on WhatsApp. You'll see the "
                 "technician's confirmation on the staff page.</p>" + _staff_link(case_id))


@router.post("/api/email-actions/{token}/reject", include_in_schema=False)
async def reject(token: str, reason: str = Form("")):
    tok, problem = _verify_for(token, "reject")
    if problem:
        return problem
    case_id = tok["c"]
    reason = (reason or "").strip()[:500]
    try:
        result = services.reject_case(case_id, reason, actor="staff")
    except rules.RuleViolation as rv:
        return _page("Could not reject", f"<h1 class='warn'>Could not reject</h1><p>{html.escape(rv.message)}</p>"
                     + _staff_link(case_id), 409)
    record_event(case_id, "staff", "staff.email_rejected",
                 "Rejected by email" + (f": {reason}" if reason else ""),
                 {"partner_id": tok.get("p"), "partner_name": result.get("partner_name"), "reason": reason})
    await notify.notify_tenant(case_id, "approval_rejected",
                               {"partner_name": result.get("partner_name"), "reason": reason})
    name = html.escape(result.get("partner_name") or _partner_name(tok.get("p")))
    return _page("Rejected", f"<h1>Rejected. {name} will not be contacted.</h1>"
                 "<p>Debye lets the tenant know that the property manager takes over.</p>"
                 + _staff_link(case_id))
