"""Staff approval email: the moment a case enters approval_pending (services.dispatch_job, also on
redispatch), Debye emails the property manager a briefing with one-click Confirm / Reject / More info
links (app.email_links). Sent through AgentMail (POST /v0/inboxes/{inbox}/messages/send).

Never blocks or breaks the flow: it runs in a background thread, and a missing key or a send error
is logged and recorded as a "staff.email_failed" event. Staff can always decide on the staff page.
APPROVAL_EMAIL_ENABLED=0 turns it off; unset = on when AGENTMAIL_API_KEY is set.
"""
from __future__ import annotations

import html
import logging
import re
import threading
from urllib.parse import quote

import httpx

from .config import settings
from .events import record_event

log = logging.getLogger("debye.notify_email")

TRADE_PEOPLE = {"heating": "heating technician", "plumbing": "plumber", "electrical": "electrician",
                "hot_water": "heating technician", "radiator": "heating technician",
                "locksmith": "locksmith", "glazing": "glazier", "roofing": "roofer"}
FIELD_LABELS = {"name": "name", "address": "address", "phone": "phone number", "phone_e164": "phone number",
                "access": "access details (key safe / intercom)", "email": "email", "unit": "unit",
                "photos": "photos", "error_code": "error code", "access_details": "access details (key safe / intercom)"}
_TAP = re.compile(r"^[a-z][a-z0-9_]*\s*=\s*\S+$")  # a button tap logged as "q_scope = everywhere"
_QA_ID = re.compile(r"\b(q_[a-z0-9_]+)=([a-z0-9_]+)")


def _human_reasoning(text: str) -> str:
    """'Decisive answer: q_scope=everywhere' → 'Decisive answer: cold or lukewarm everywhere'."""
    from .services import diagnosis_kb
    kb = diagnosis_kb()["questions"]

    def sub(m):
        ans = (kb.get(m.group(1)) or {}).get("answers") or {}
        return str(ans.get(m.group(2)) or m.group(2).replace("_", " "))
    return _QA_ID.sub(sub, text or "")


def _clean_report(text: str) -> str | None:
    t = (text or "").strip()
    if not t or _TAP.match(t):
        return None
    if len(t.split()) <= 3 and not re.search(r"\d", t):  # "Yes, go ahead": a button, not a report
        return None
    if t.startswith("🎤"):  # transcribed voice note
        t = "(voice note) " + t[1:].strip()
    return t


def enabled() -> bool:
    if settings.approval_email_enabled is not None:
        return bool(settings.approval_email_enabled)
    return bool(settings.agentmail_api_key)


def _spawn(fn) -> None:  # tests replace this to run inline
    threading.Thread(target=fn, name="approval-email", daemon=True).start()


def on_approval_pending(case_id: str) -> None:
    """Hook from services.dispatch_job. Returns at once; the email goes out in the background."""
    if not enabled():
        return
    _spawn(lambda: send_approval_email(case_id))


# --------------------------------------------------------------------------- content

def _unit_label(unit_id: str | None) -> str:
    if not unit_id:
        return ""
    u = unit_id.split("_", 1)[1] if "_" in unit_id else unit_id
    return u.upper()


def _eur(x) -> str | None:
    return f"€{float(x):.0f}" if isinstance(x, (int, float)) else None


def briefing(case_id: str) -> dict:
    """Everything the email shows, as plain data (also used by the tests)."""
    from sqlmodel import select

    from . import rules, services
    from .db import get_session
    from .models import Case
    from .staff_api import case_detail

    with get_session() as s:
        c = s.get(Case, case_id)
        if c is None:
            raise services.NotFound(case_id)
        d = case_detail(s, c)
        pid = (c.data or {}).get("pending_partner_id") or (d["approval"].get("partner") or {}).get("partner_id")
        prices = rules.partner_prices(s, pid) if pid else None
    diag = d.get("diagnosis") or {}
    tenant = (d.get("reporters") or [{}])[0]
    tenant_name = tenant.get("name") or "the tenant"
    address = (d.get("address") or "").split(",")[0].strip()
    unit = _unit_label(d.get("unit_id"))
    place = " ".join(x for x in (address, unit) if x)
    trade = d.get("trade") or diag.get("trade")
    who = TRADE_PEOPLE.get(trade or "", f"{trade} technician" if trade else "technician")
    asset = d.get("asset") or {}
    code = asset.get("error_code") or d.get("error_code")
    code_label = asset.get("error_label") or d.get("error_label")
    short = services._ERROR_SHORT_EN.get(services._norm_code(code)) if code else None
    problem = (f"{code} {short}" if code and short else
               f"{code} {code_label[:1].lower() + code_label[1:]}" if code and code_label else
               code or diag.get("label") or d.get("title") or "repair")
    ranking = d.get("ranking") or []
    top = next((r for r in ranking if r.get("partner_id") == pid), ranking[0] if ranking else {})
    card = d["approval"]
    partner_name = (card.get("partner") or {}).get("name") or top.get("name") or pid or "the partner"
    consents = [k for k in d.get("consents") or [] if k["partner_id"] == pid and not k.get("revoked_at")]
    shared = sorted({f for k in consents for f in (k.get("data_shared") or [])})
    photos = [x for x in d.get("documents") or [] if (x.get("mime") or "").startswith("image/")]
    tenant_id = tenant.get("contact_id")
    reports = [r for r in (_clean_report(m.get("text")) for m in d.get("messages") or []
                           if m["direction"] == "in" and (not tenant_id or m.get("contact_id") == tenant_id))
               if r][:3]
    if not reports and d.get("summary"):
        reports = [d["summary"]]
    est = d.get("estimated_cost_eur")
    if est is None:
        est = diag.get("estimated_cost_eur")
    outcome = diag.get("outcome")
    why_trade = {
        "technician": "The cause needs a qualified technician: it is not something the tenant can fix "
                      "with a reset or the caretaker can handle.",
        "emergency": "This is a safety issue: it needs a professional right away.",
        "utility": "The utility company has to look at it.",
    }.get(outcome or "", "Debye did not find a self-help or caretaker fix for this.")
    slot = card.get("suggested_slot") or {}
    tech = card.get("suggested_technician") or {}
    redispatch = (d.get("events") and [e for e in d["events"] if e["kind"] == "partner.redispatched"]) or []
    return {
        "case_id": case_id, "title": d.get("title"), "priority": d.get("priority") or "normal",
        "tenant_name": tenant_name, "place": place, "address": d.get("address"), "unit": unit,
        "who": who, "problem": problem, "reports": reports,
        "diagnosis": {"label": diag.get("label"), "confidence": diag.get("confidence"),
                      "reasoning": _human_reasoning(diag.get("reasoning")),
                      "qa": [{"question": q.get("question"), "answer": q.get("answer") or "not answered"}
                             for q in diag.get("questions_asked") or []],
                      "outcome": outcome},
        "evidence": {"error_code": code, "error_label": code_label, "photos": len(photos),
                     "asset": " ".join(x for x in (asset.get("make"), asset.get("model")) if x) or None},
        "why_trade": why_trade,
        "partner": {"id": pid, "name": partner_name, "reasons": top.get("reasons") or [],
                    "score": top.get("score"),
                    "others": [r["name"] for r in ranking if r.get("partner_id") != pid][:2],
                    "redispatched_from": (redispatch[-1]["data"] or {}).get("declined_partner_name")
                    if redispatch else None},
        "technician": tech.get("name"), "slot": slot.get("label"),
        "estimate": _eur(est), "cost_cap": _eur((prices or {}).get("auto_approve_limit_eur")),
        "prices": (f"{_eur(prices['callout_fee_eur'])} callout, {_eur(prices['hourly_eur'])}/h"
                   if prices and prices.get("callout_fee_eur") is not None and prices.get("hourly_eur") is not None
                   else None),
        "rule": card.get("rule"),
        "shared": [FIELD_LABELS.get(f, f) for f in shared],
        "subject": f"Approve: {who} for {tenant_name}" + (f", {place}" if place else "") + f" – {problem}",
    }


def _next_steps(b: dict) -> list[str]:
    p = b["partner"]["name"]
    steps = [f"Debye sends the job to {p}" + (" with only the data the tenant agreed to share." if b["shared"]
                                               else ".")]
    if b["technician"] and b["slot"]:
        steps.append(f"{b['technician']} is proposed for {b['slot']}; the tenant confirms the slot on WhatsApp.")
    else:
        steps.append(f"{p} proposes appointment slots; the tenant picks one on WhatsApp.")
    steps.append("The technician confirms, does the repair and uploads a photo and the invoice.")
    steps.append("Debye checks the invoice against the estimate and the agreed prices, then closes the case.")
    return steps


def render(case_id: str, links: dict) -> dict:
    """{"subject", "text", "html"}"""
    b = briefing(case_id)
    dg, ev, pa = b["diagnosis"], b["evidence"], b["partner"]
    conf = f"{round(dg['confidence'] * 100)}%" if isinstance(dg.get("confidence"), (int, float)) else None
    evidence = []
    if ev["error_code"]:
        evidence.append(f"Error code {ev['error_code']}" + (f" ({ev['error_label']})" if ev["error_label"] else ""))
    if ev["asset"]:
        evidence.append(f"Appliance: {ev['asset']}")
    evidence.append(f"Photo: {'yes, ' + str(ev['photos']) if ev['photos'] else 'no'}")
    partner_why = list(pa["reasons"])
    if pa["redispatched_from"]:
        partner_why.append(f"{pa['redispatched_from']} declined, so this is the next-best partner")
    cost = [x for x in (f"Estimate {b['estimate']}" if b["estimate"] else None,
                        f"cost cap {b['cost_cap']} (framework agreement)" if b["cost_cap"] else None,
                        b["prices"]) if x]
    steps = _next_steps(b)
    head = f"{b['tenant_name']} · {b['place'] or b['address'] or ''} · priority {b['priority']}"

    # ---- plain text
    t = [f"Debye wants to book {pa['name']} ({b['who']}). Please confirm.", "", head, ""]
    t += ["WHAT THE TENANT REPORTED"] + [f'  "{r}"' for r in b["reports"]] + [""]
    t += ["DIAGNOSIS", f"  {dg['label'] or b['problem']}" + (f" (confidence {conf})" if conf else "")]
    if dg["reasoning"]:
        t.append(f"  {dg['reasoning']}")
    for qa in dg["qa"]:
        t.append(f"  Q: {qa['question']}  A: {qa.get('answer') or '-'}")
    t += ["  Evidence: " + "; ".join(evidence), f"  Why a craftsman: {b['why_trade']}", ""]
    t += ["PARTNER", f"  {pa['name']}" + (f": {', '.join(partner_why)}" if partner_why else "")]
    if pa["others"]:
        t.append(f"  Also ranked: {', '.join(pa['others'])}")
    if cost:
        t.append("  Cost: " + "; ".join(cost))
    t.append("  Tenant agreed to share: " + (", ".join(b["shared"]) if b["shared"] else "no personal data"))
    t += ["", "IF YOU CONFIRM"] + [f"  {i}. {s}" for i, s in enumerate(steps, 1)] + [""]
    t += [f"Confirm: {links['confirm']}", f"Don't do it: {links['reject']}",
          f"More information: {links['info']}", "",
          f"Links are valid for {settings.email_link_ttl_hours:g} hours. Case {case_id}."]

    # ---- HTML (inline styles: email clients ignore <style>)
    e = html.escape
    wine, ink, body, muted, line, tint = "#6B1F33", "#2B1018", "#5A4744", "#8E807A", "#EBE3DC", "#F5EBED"

    def section(title: str, inner: str) -> str:
        return (f"<tr><td style='padding:18px 28px 0'><div style='font:600 12px/1.4 Arial,sans-serif;"
                f"color:{wine};letter-spacing:.04em;margin-bottom:6px'>{e(title)}</div>{inner}</td></tr>")

    def para(x: str, color: str = body) -> str:
        return f"<p style='margin:0 0 8px;font:15px/1.5 Arial,sans-serif;color:{color}'>{x}</p>"

    def ul(items: list[str], ordered: bool = False) -> str:
        tag = "ol" if ordered else "ul"
        lis = "".join(f"<li style='margin:0 0 4px'>{i}</li>" for i in items)
        return f"<{tag} style='margin:0 0 8px;padding-left:20px;font:15px/1.5 Arial,sans-serif;color:{body}'>{lis}</{tag}>"

    quotes = "".join(f"<div style='border-left:3px solid {wine};background:{tint};padding:8px 12px;"
                     f"margin:0 0 6px;font:italic 15px/1.5 Arial,sans-serif;color:{ink}'>&ldquo;{e(r)}&rdquo;</div>"
                     for r in b["reports"]) or para("(no messages)")
    qa_rows = "".join(f"<tr><td style='padding:4px 10px 4px 0;font:14px/1.4 Arial,sans-serif;color:{body};"
                      f"vertical-align:top'>{e(q['question'])}</td><td style='padding:4px 0;font:600 14px/1.4 "
                      f"Arial,sans-serif;color:{ink};vertical-align:top;white-space:nowrap'>{e(str(q.get('answer') or '-'))}"
                      f"</td></tr>" for q in dg["qa"])
    diag_html = para(f"<b style='color:{ink}'>{e(dg['label'] or b['problem'])}</b>"
                     + (f" &middot; confidence {conf}" if conf else ""))
    if dg["reasoning"]:
        diag_html += para(e(dg["reasoning"]))
    if qa_rows:
        diag_html += (f"<table role='presentation' cellpadding='0' cellspacing='0' style='margin:0 0 8px;"
                      f"border-top:1px solid {line};width:100%'>{qa_rows}</table>")
    diag_html += ul([e(x) for x in evidence]) + para(f"<b style='color:{ink}'>Why a craftsman:</b> {e(b['why_trade'])}")
    partner_html = para(f"<b style='color:{ink}'>{e(pa['name'])}</b>")
    if partner_why:
        partner_html += ul([e(x) for x in partner_why])
    if pa["others"]:
        partner_html += para(f"Also ranked: {e(', '.join(pa['others']))}", muted)
    if cost:
        partner_html += para("<b style='color:%s'>Cost:</b> %s" % (ink, e("; ".join(cost))))
    partner_html += para(f"<b style='color:{ink}'>Tenant agreed to share:</b> "
                         + e(", ".join(b["shared"]) if b["shared"] else "no personal data"))

    def button(label: str, href: str, primary: bool) -> str:
        bg, fg = (wine, "#ffffff") if primary else ("#EFE8DF", ink)
        return (f"<td style='padding:0 8px 8px 0'><a href='{e(href)}' style='display:inline-block;background:{bg};"
                f"color:{fg};text-decoration:none;font:600 15px/1 Arial,sans-serif;padding:13px 18px;"
                f"border-radius:10px'>{label}</a></td>")

    buttons = (f"<table role='presentation' cellpadding='0' cellspacing='0'><tr>"
               + button("&#128077; Confirm", links["confirm"], True)
               + button("&#128078; Don&rsquo;t do it", links["reject"], False)
               + button("&#8505;&#65039; More information", links["info"], False) + "</tr></table>")
    h = (f"<!doctype html><html><body style='margin:0;background:#FAF8F5'>"
         f"<div style='display:none;max-height:0;overflow:hidden'>{e(pa['name'])} for {e(b['problem'])}"
         f" &middot; {e(b['estimate'] or '')}</div>"
         f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='background:#FAF8F5'>"
         f"<tr><td align='center' style='padding:24px 12px'>"
         f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='max-width:600px;"
         f"background:#FDFCFA;border:1px solid {line};border-radius:14px'>"
         f"<tr><td style='padding:24px 28px 0'><div style='font:700 14px/1 Arial,sans-serif;color:{wine}'>"
         f"Debye &middot; reltix</div>"
         f"<h1 style='margin:14px 0 6px;font:700 22px/1.3 Arial,sans-serif;color:{ink}'>Book {e(pa['name'])} "
         f"for {e(b['tenant_name'])}?</h1>"
         f"<p style='margin:0;font:14px/1.5 Arial,sans-serif;color:{muted}'>{e(head)} &middot; "
         f"{e(b['problem'])}</p>"
         f"<div style='margin:18px 0 0'>{buttons}</div></td></tr>"
         + section("WHAT THE TENANT REPORTED", quotes)
         + section("DIAGNOSIS", diag_html)
         + section("WHY THIS PARTNER", partner_html)
         + section("IF YOU CONFIRM", ul([e(s) for s in steps], ordered=True))
         + f"<tr><td style='padding:14px 28px 4px'>{buttons}</td></tr>"
         f"<tr><td style='padding:8px 28px 24px;font:12px/1.5 Arial,sans-serif;color:{muted}'>"
         f"Links work without login for {settings.email_link_ttl_hours:g} hours and only for case "
         f"{e(case_id)}. You can also decide on the staff page.</td></tr>"
         "</table></td></tr></table></body></html>")
    return {"subject": b["subject"], "text": "\n".join(t), "html": h}


# --------------------------------------------------------------------------- sending

def _post_agentmail(to: str, subject: str, text: str, html_body: str) -> dict:
    url = f"{settings.agentmail_base_url.rstrip('/')}/inboxes/{quote(settings.agentmail_inbox or '', safe='')}/messages/send"
    r = httpx.post(url, headers={"Authorization": f"Bearer {settings.agentmail_api_key}"},
                   json={"to": [to], "subject": subject, "text": text, "html": html_body,
                         "labels": ["debye-approval"]}, timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"AgentMail HTTP {r.status_code}: {r.text[:200]}")
    return r.json() if r.content else {}


SENDER = _post_agentmail  # tests replace this


def send_approval_email(case_id: str) -> dict:
    """Build + send. Never raises; returns {"ok", ...} and records staff.email_sent / staff.email_failed."""
    to = settings.staff_approval_email
    try:
        if not settings.agentmail_api_key or not settings.agentmail_inbox or not to:
            raise RuntimeError("email not configured (AGENTMAIL_API_KEY / AGENTMAIL_INBOX / STAFF_APPROVAL_EMAIL)")
        from . import email_links, services
        case = services.get_case(case_id)
        pid = (case.data or {}).get("pending_partner_id") if case else None
        links = email_links.links(case_id, pid)
        msg = render(case_id, links)
        res = SENDER(to, msg["subject"], msg["text"], msg["html"])
    except Exception as exc:  # never break the approval flow
        log.warning("approval email for %s failed: %s", case_id, exc)
        try:
            record_event(case_id, "system", "staff.email_failed",
                         "Approval email not sent – staff can approve on this page", {"error": str(exc)[:300]})
        except Exception:
            log.exception("could not record staff.email_failed")
        return {"ok": False, "error": str(exc)}
    record_event(case_id, "system", "staff.email_sent", f"Approval email sent to {to}",
                 {"to": to, "subject": msg["subject"], "message_id": (res or {}).get("message_id")})
    return {"ok": True, "message_id": (res or {}).get("message_id"), "subject": msg["subject"]}
