"""Send helpers: every outbound message goes through here, so it is logged and
published as message.out no matter who sent it (agent tool, router, notify)."""
from __future__ import annotations

import logging

from app.channels.base import Option, channel_for

from . import _backend as be

log = logging.getLogger("debye.outbound")


def _who(contact):
    return be.attr(contact, "id"), be.attr(contact, "phone_e164"), be.attr(contact, "name")


async def text(contact, case_id: str | None, body: str) -> str | None:
    cid, phone, name = _who(contact)
    ch = channel_for(phone)
    mid = await ch.send_text(phone, body)
    await be.log_message(cid, case_id, ch.name, "out", body, mid, contact_name=name)
    return mid


async def buttons(contact, case_id: str | None, body: str, options: list[Option]) -> str | None:
    cid, phone, name = _who(contact)
    ch = channel_for(phone)
    mid = await ch.send_buttons(phone, body, options)
    shown = body + "\n" + " · ".join(f"[{o.title}]" for o in options[:3])
    await be.log_message(cid, case_id, ch.name, "out", shown, mid, contact_name=name)
    return mid


async def list_(
    contact, case_id: str | None, body: str, button_label: str, rows: list[Option], section_title: str = "Optionen"
) -> str | None:
    cid, phone, name = _who(contact)
    ch = channel_for(phone)
    mid = await ch.send_list(phone, body, button_label, rows, section_title)
    shown = body + "\n" + "\n".join(f"• {r.title}" for r in rows[:10])
    await be.log_message(cid, case_id, ch.name, "out", shown, mid, contact_name=name)
    return mid


async def media(contact, case_id: str | None, kind: str, path: str, caption: str | None = None) -> str | None:
    cid, phone, name = _who(contact)
    ch = channel_for(phone)
    mid = await ch.send_media(phone, kind, path, caption)
    await be.log_message(cid, case_id, ch.name, "out", caption or f"[{kind}]", mid, [path], contact_name=name)
    return mid
