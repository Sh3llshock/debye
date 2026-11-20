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
_buffers: dict[str, list[tuple[str | None, list[str], bool]]] = defaultdict(list)
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
    doc_ids: list[str] = []
    for m in msg.media:
        try:
            path = await ch.download_media(m)
        except Exception:
            log.exception("media download failed")
            continue
        kind = {"audio": "voice_note", "image": "photo", "pdf": "document"}.get(m.kind, "document")
        doc_id = _attach(conv.case_id or "", kind, path, m.mime, m.filename)
        if doc_id:
            doc_ids.append(doc_id)
        if m.kind == "audio":
            flow.tenant_input(contact, "voice note")
            from app import media as media_mod

            spoken = await media_mod.transcribe(path)
            if spoken:
                text = f"{text}\n{spoken}" if text else spoken
                text = text.strip()
            else:
                # let the agent (or the scripted fallback) carry on; it asks back if unclear
                text = (text or "") + "\n[Sprachnachricht, konnte nicht transkribiert werden]"
                text = text.strip()
        elif m.kind == "image":
            images.append(path)
            flow.tenant_input(contact, "photo")

    shown = text if not msg.button_id else (msg.button_title or msg.button_id)
    if shown and any(m.kind == "audio" for m in msg.media):
        shown = "🎤 " + shown
    # media_ids are document ids: open_case / link_contact_to_case claim them for the case later
    await be.log_message(
        cid, conv.case_id, msg.channel, "in", shown, msg.wa_message_id, doc_ids, be.attr(contact, "name")
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
        return

    from app.agent import diagnosis

    # "My shower is cold": start the diagnosis (safety question first, asked by code)
    if (text and not conv.case_id and not conv.diagnosis and conv.step == st.NEW and diagnosis.applies(text)):
        conv.tenant_texts.append(text)
        async with _locks[cid]:
            await diagnosis.begin(contact, conv, text)
        return
    # a photo of the display (or a code typed in the text) during the diagnosis answers q_display
    if (images or text) and diagnosis.active(conv) and "q_display" not in conv.diagnosis["answers"]:
        code, _src = flow.detect_error_code([text or ""], images)
        if code:
            conv.error_code = conv.error_code or code
            conv.diagnosis["answers"]["q_display"] = "code"

    # A free-text answer to the open question ("sure", "just the shower", "Saturday works") is handled
    # exactly like the tap, so consent/slots are really recorded before anything is confirmed.
    in_diagnosis = diagnosis.active(conv) and conv.diagnosis.get("safety_done")
    if text and not images and conv.pending_options and not in_diagnosis:
        # (during a diagnosis the model reads the whole message and records every answer in it;
        #  only the safety question is mapped here, by code)
        from app.agent import choice

        opt = await choice.match(text, conv.pending_options, conv.pending_question)
        if opt is not None:
            log.info("free text %r understood as %s", text[:40], opt.id)
            async with _locks[cid]:
                if await handle_button(contact, opt.id):
                    return

    _buffers[cid].append((text, images, any(m.kind == "audio" for m in msg.media)))
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
        text = "\n".join(t for t, _, _ in batch if t) or None
        images = [p for _, imgs, _ in batch for p in imgs]
        had_voice = any(v for _, _, v in batch)
        async with _locks[cid]:
            await loop.run_tenant_turn(contact, text, images)
            if had_voice:
                await flow.maybe_voice_reply(contact)


def _attach(case_id: str, kind: str, path: str, mime: str, filename: str | None = None) -> str | None:
    try:
        doc = be.attach_document(case_id, kind, filename or Path(path).name, mime.split(";")[0], path, None)
        return be.attr(doc, "id")
    except Exception:
        log.exception("attach_document failed")
        return None


async def handle_button(contact, button_id: str) -> bool:
    """Handles §3.6 ids in code. Returns False for ids it does not know."""
    if (button_id or "").startswith(("diagfu_yes:", "diagfu_no:")):  # follow-up after a self-help tip
        from app.agent import diagnosis

        kind, _, cause_id = button_id.partition(":")
        st.conversation(be.attr(contact, "id")).pending_options = []
        try:
            await diagnosis.on_follow_up(contact, cause_id, kind == "diagfu_yes")
        except Exception:
            log.exception("diagnosis follow-up %s failed", button_id)
        return True
    if (button_id or "").startswith("diag:"):
        _, qid, key = (button_id.split(":") + ["", ""])[:3]
        from app.agent import diagnosis

        st.conversation(be.attr(contact, "id")).pending_options = []
        try:
            await diagnosis.on_answer(contact, qid, key)
        except Exception:
            log.exception("diagnosis answer %s failed", button_id)
        return True
    m = BUTTON_RE.match(button_id or "")
    if not m:
        return False
    kind, n, case_id = m.group("kind"), m.group("n"), m.group("case")
    conv = st.conversation(be.attr(contact, "id"))
    from app.agent import outbound

    conv.pending_options, conv.pending_question = [], None  # answered (a handler may ask the next one)
    sent_before = outbound.sent_count
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
        if outbound.sent_count == sent_before:  # only if the resident got no reply yet
            await outbound.text(contact, case_id, "Danke! Ich kümmere mich darum und melde mich gleich.")
    return True
