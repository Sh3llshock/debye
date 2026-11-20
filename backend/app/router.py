"""Inbound message → contact → case → deterministic handler or Debye agent (technical-plan §6).

Button and list ids (interfaces §3.6) are handled in code. Free text, voice
notes and photos go to the agent. Messages from one contact that arrive close
together (voice note + photo) are batched into one agent turn.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import defaultdict
from pathlib import Path

from app.agent import _backend as be
from app.agent import flow, loop
from app.agent import state as st
from app.channels.base import InboundMessage, channel_for, get_channel

log = logging.getLogger("debye.router")

DEBOUNCE_SECONDS = float(os.getenv("ROUTER_DEBOUNCE", "1.5"))

_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_buffers: dict[str, list[tuple[str | None, list[str]]]] = defaultdict(list)
_draining: set[str] = set()

BUTTON_RE = re.compile(r"^(?P<kind>[a-z_]+?)(?:_(?P<n>\d+))?:(?P<case>[\w-]+)$")


async def handle_inbound(msg: InboundMessage) -> None:
    contact = be.get_contact_by_phone(msg.from_phone)
    ch = get_channel(msg.channel)
    if contact is None:
        log.info("unknown sender %s", msg.from_phone)
        await ch.send_text(
            msg.from_phone,
            "Hallo! Diese Nummer ist bei reltix noch nicht registriert. Bitte wende dich an deine Hausverwaltung.",
        )
        return
    cid = be.attr(contact, "id")
    conv = st.conversation(cid)

    # ---- media: download, transcribe voice, keep photos
    text = msg.text
    images: list[str] = []
    media_paths: list[str] = []
    transcript_failed = False
    for m in msg.media:
        try:
            path = await ch.download_media(m)
        except Exception:
            log.exception("media download failed")
            continue
        media_paths.append(path)
        if m.kind == "audio":
            from app import media as media_mod

            spoken = await media_mod.transcribe(path)
            if spoken:
                text = f"{text}\n{spoken}" if text else spoken
                text = text.strip()
            else:
                transcript_failed = True
        elif m.kind == "image":
            images.append(path)
            if conv.case_id:
                _attach(conv.case_id, "photo", path, m.mime)
            else:
                conv.photos.append(path)
        elif conv.case_id:
            _attach(conv.case_id, "document", path, m.mime)

    shown = text if not msg.button_id else (msg.button_title or msg.button_id)
    await be.log_message(
        cid, conv.case_id, msg.channel, "in", shown, msg.wa_message_id, media_paths, be.attr(contact, "name")
    )

    role = be.attr(contact, "role")
    if role not in (None, "tenant", "owner"):
        await channel_for(msg.from_phone).send_text(
            msg.from_phone, "Hallo! Aufträge und Termine findest du auf der Partnerseite von reltix."
        )
        return

    if msg.button_id:
        async with _locks[cid]:
            if await handle_button(contact, msg.button_id):
                return
        text = msg.button_title or msg.button_id  # unknown id: let the agent read the title

    if not text and not images:
        if transcript_failed:
            from app.agent import outbound

            await outbound.text(
                contact, conv.case_id, "Sorry, ich konnte die Sprachnachricht nicht abspielen. Schreibst du mir kurz?"
            )
        return

    _buffers[cid].append((text, images))
    if cid in _draining:
        return  # the running drain picks this message up
    _draining.add(cid)
    try:
        await _drain(contact)
    finally:
        _draining.discard(cid)


async def _drain(contact) -> None:
    cid = be.attr(contact, "id")
    while _buffers[cid]:
        if DEBOUNCE_SECONDS > 0:
            await asyncio.sleep(DEBOUNCE_SECONDS)
        batch, _buffers[cid] = _buffers[cid], []
        text = "\n".join(t for t, _ in batch if t) or None
        images = [p for _, imgs in batch for p in imgs]
        async with _locks[cid]:
            await loop.run_tenant_turn(contact, text, images)


def _attach(case_id: str, kind: str, path: str, mime: str) -> None:
    try:
        be.attach_document(case_id, kind, Path(path).name, mime, path, None)
    except Exception:
        log.exception("attach_document failed")


async def handle_button(contact, button_id: str) -> bool:
    """Handles §3.6 ids in code. Returns False for ids it does not know."""
    m = BUTTON_RE.match(button_id or "")
    if not m:
        return False
    kind, n, case_id = m.group("kind"), m.group("n"), m.group("case")
    conv = st.conversation(be.attr(contact, "id"))
    if case_id == "new" or not case_id:
        case_id = conv.case_id
    if case_id and not conv.case_id:
        conv.case_id = case_id
    try:
        if kind in ("cold_all", "cold_some") or (kind == "cold" and n is None):
            if not case_id:
                said = " ".join(conv.tenant_texts[-3:]) or "Heizung kalt"
                res = await flow.ensure_case(contact, summary="Heizung kalt", symptoms=said[:500])
                case_id = res["case_id"]
                if res["duplicate"]:
                    await flow.send_duplicate_notice(contact, case_id)
                    return True
            await flow.on_cold(contact, case_id, kind == "cold_all")
        elif kind in ("consent_yes", "consent_no"):
            await flow.on_consent(contact, case_id, kind == "consent_yes")
        elif kind == "slot" and n is not None:
            await flow.on_slot(contact, case_id, int(n))
        elif kind == "slot_none":
            await flow.on_slot_none(contact, case_id)
        elif kind in ("fixed_yes", "fixed_no"):
            await flow.on_fixed(contact, case_id, kind == "fixed_yes")
        else:
            return False
    except Exception:
        log.exception("button %s failed", button_id)
        from app.agent import outbound

        await outbound.text(contact, case_id, "Danke! Ich kümmere mich darum und melde mich gleich.")
    return True
