"""The one place where agent-whatsapp code touches backend-core.

Everything goes through here so a renamed service function is a one-line fix,
and tests can monkeypatch a single module. Functions that are not (yet) in
interfaces.md §3.3 degrade gracefully instead of crashing the webhook.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any

log = logging.getLogger("debye.backend")


def _services():
    from app import services  # backend-core

    return services


def _call(name: str, *args, **kwargs):
    fn = getattr(_services(), name, None)
    if fn is None:
        raise AttributeError(f"services.{name} missing")
    return fn(*args, **kwargs)


async def _maybe_await(v):
    return await v if inspect.isawaitable(v) else v


def as_dict(obj: Any) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return {k: v for k, v in vars(obj).items() if not k.startswith("_")}


def attr(obj: Any, name: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


# ---------------------------------------------------------------- contracts §3.3
def get_contact_by_phone(phone: str):
    return _call("get_contact_by_phone", phone)


def get_unit_context(unit_id: str) -> dict:
    try:
        return _call("get_unit_context", unit_id) or {}
    except Exception:
        log.exception("get_unit_context failed")
        return {}


def find_open_case_for_asset(asset_id: str):
    return _call("find_open_case_for_asset", asset_id)


def open_case(**kw):
    return _call("open_case", **kw)


def link_contact_to_case(case_id: str, contact_id: str, relation: str) -> None:
    _call("link_contact_to_case", case_id, contact_id, relation)


def attach_document(case_id, kind, filename, mime, path, extracted=None):
    return _call("attach_document", case_id, kind, filename, mime, path, extracted)


def record_consent(contact_id, partner_id, case_id, fields, purpose, channel):
    return _call("record_consent", contact_id, partner_id, case_id, fields, purpose, channel)


def rank_partners(case_id: str) -> list[dict]:
    return _call("rank_partners", case_id) or []


def dispatch_job(case_id: str, partner_id: str) -> dict:
    return _call("dispatch_job", case_id, partner_id)


def confirm_slot(case_id: str, slot_index: int) -> dict:
    return _call("confirm_slot", case_id, slot_index)


def tenant_confirms_fixed(case_id: str, fixed: bool) -> dict:
    return _call("tenant_confirms_fixed", case_id, fixed)


def set_case_error_code(case_id: str, error_code: str) -> None:
    """Writes the display code onto an open case and records it on the timeline."""
    svc = _services()
    fn = getattr(svc, "set_case_error_code", None)
    if fn is not None:  # it only writes the field; the timeline event below is recorded here (once)
        fn(case_id, error_code)
    else:
        _set_error_code_directly(case_id, error_code)
    from .error_codes import timeline_summary

    record_event(case_id, "debye", "triage.error_code", timeline_summary(error_code), {"error_code": error_code})


def _set_error_code_directly(case_id: str, error_code: str) -> None:
    try:  # until backend-core ships set_case_error_code
        from app import db, models

        with db.get_session() as s:
            case = s.get(models.Case, case_id)
            if case is not None and getattr(case, "error_code", None) != error_code:
                case.error_code = error_code
                s.add(case)
                s.commit()
    except Exception:
        log.exception("set_case_error_code fallback failed")


def add_tenant_input(case_id: str | None, label: str) -> None:
    """Zero-forms counter on the staff page."""
    if not case_id:
        return
    try:
        _call("add_tenant_input", case_id, label)
    except Exception:
        log.exception("add_tenant_input failed")


def rule_violation_code(exc: Exception) -> str | None:
    """Returns 'consent_missing' / 'approval_required' if exc is a rules.RuleViolation."""
    try:
        from app.rules import RuleViolation
    except Exception:
        RuleViolation = None
    if RuleViolation is not None and isinstance(exc, RuleViolation):
        return getattr(exc, "code", None) or (exc.args[0] if exc.args else None)
    if type(exc).__name__ == "RuleViolation":
        return getattr(exc, "code", None) or (exc.args[0] if exc.args else None)
    return None


# ---------------------------------------------------------------- events §3.2
def record_event(case_id: str | None, actor: str, kind: str, summary: str, data: dict | None = None) -> None:
    if not case_id:
        return
    try:
        from app import events

        events.record_event(case_id, actor, kind, summary, data)
    except Exception:
        log.exception("record_event failed (%s)", kind)


async def publish(type_: str, case_id: str | None, payload: dict) -> None:
    try:
        from app import events

        await _maybe_await(events.publish(type_, case_id, payload))
    except Exception:
        log.exception("publish failed (%s)", type_)


# ---------------------------------------------------------------- asked for, not yet in §3.3
async def log_message(
    contact_id: str | None,
    case_id: str | None,
    channel: str,
    direction: str,
    text: str | None,
    wa_message_id: str | None = None,
    media_ids: list[str] | None = None,
    contact_name: str | None = None,
) -> None:
    """Persists a message row and publishes message.in / message.out for the dashboards."""
    svc = None
    try:
        svc = _services()
    except Exception:
        pass
    fn = getattr(svc, "log_message", None) if svc else None
    if fn is not None:
        try:
            await _maybe_await(
                fn(
                    contact_id=contact_id,
                    case_id=case_id,
                    channel=channel,
                    direction=direction,
                    text=text,
                    wa_message_id=wa_message_id,
                    media_ids=media_ids or [],
                )
            )
            return
        except Exception:
            log.exception("services.log_message failed; publishing only")
    await publish(
        f"message.{direction}",
        case_id,
        {
            "direction": direction,
            "contact_id": contact_id,
            "contact": contact_name,
            "channel": channel,
            "text": text,
            "media": media_ids or [],
        },
    )


def get_case_contacts(case_id: str) -> list:
    svc = _services()
    fn = getattr(svc, "get_case_contacts", None)
    if fn is not None:
        return list(fn(case_id) or [])
    # fallback: query the tables directly (names per technical-plan §3)
    try:
        from sqlmodel import select

        from app import db, models

        Contact = getattr(models, "Contact")
        CaseContact = getattr(models, "CaseContact")
        with db.get_session() as s:
            rows = s.exec(select(CaseContact).where(CaseContact.case_id == case_id)).all()
            ids = [r.contact_id for r in rows]
            if not ids:
                Case = getattr(models, "Case")
                case = s.get(Case, case_id)
                ids = [case.reporter_contact_id] if case else []
            return [s.get(Contact, i) for i in ids if s.get(Contact, i)]
    except Exception:
        log.exception("get_case_contacts fallback failed")
        return []


def get_contact(contact_id: str):
    svc = _services()
    fn = getattr(svc, "get_contact", None)
    if fn is not None:
        return fn(contact_id)
    try:
        from app import db, models

        with db.get_session() as s:
            return s.get(models.Contact, contact_id)
    except Exception:
        log.exception("get_contact fallback failed")
        return None
