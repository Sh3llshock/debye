"""Inbound message → contact → case → deterministic handler or Debye agent (technical-plan §6).

Button and list ids (interfaces §3.6) are handled in code. Free text, voice
notes and photos go to the agent. Messages from one contact that arrive close
together (a burst of texts, voice note + photo) are batched into one turn; a message
that arrives while the model is still thinking re-plans that turn.
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

DEBOUNCE_SECONDS = float(os.getenv("ROUTER_DEBOUNCE", "2.5"))  # a burst of short messages = one turn

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
            "Hi. This number isn't registered with reltix yet. Please contact your property management.",
        )
        return
    cid = be.attr(contact, "id")
    conv = st.conversation(cid)
    conv.channel = "web" if msg.channel in ("web", "webchat") else (msg.channel or "whatsapp")

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
            conv.photos += 1
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
            msg.from_phone, "Hi. Jobs and appointments are on the reltix partner page."
        )
        return

    if msg.button_id:
        async with _locks[cid]:
            if await handle_button(contact, msg.button_id):
                return
        text = msg.button_title or msg.button_id  # unknown id: let the agent read the title

    if not text and not images:
        return

    # Everything typed/spoken goes through a short buffer: a burst of messages ("hi" / "my shower" /
    # "is cold") becomes ONE turn, and a message that arrives while the model is still thinking
    # makes the turn re-plan with all of them (never a reply to a fragment).
    _buffers[cid].append((text, images, any(m.kind == "audio" for m in msg.media)))
    if cid in _draining:
        return  # the running drain picks this message up
    _draining.add(cid)
    try:
        await _drain(contact)
    finally:
        _draining.discard(cid)


def has_pending(cid: str | None) -> bool:
    """New tenant messages are waiting (the running turn should not send; it is re-planned)."""
    return bool(cid and _buffers.get(cid))


async def _drain(contact) -> None:
    cid = be.attr(contact, "id")
    carry = None
    while _buffers[cid] or carry:
        if DEBOUNCE_SECONDS > 0:
            await asyncio.sleep(DEBOUNCE_SECONDS)
        batch, _buffers[cid] = _buffers[cid], []
        if carry:
            batch = [carry] + batch
            carry = None
        text = "\n".join(t for t, _, _ in batch if t) or None
        images = [p for _, imgs, _ in batch for p in imgs]
        had_voice = any(v for _, _, v in batch)
        async with _locks[cid]:
            interrupted = await process_text(contact, text, images)
        if interrupted:
            log.info("newer messages from %s: re-planning the turn with all of them", cid)
            carry = (text, images, had_voice)
            continue
        if had_voice:
            async with _locks[cid]:
                await flow.maybe_voice_reply(contact)


async def process_text(contact, text: str | None, images: list[str]) -> bool:
    """One merged batch of tenant text/photos. Returns True if the turn was interrupted by newer messages."""
    from app.agent import diagnosis

    cid = be.attr(contact, "id")
    conv = st.conversation(cid)
    diagnosis.update_lang(conv, text)
    if conv.diagnosis:
        conv.diagnosis["turn"] = conv.diagnosis.get("turn", 0) + 1  # one batch of tenant messages = one turn
    # Gas smell / hissing mentioned anywhere → emergency path at once (never asked proactively)
    if text and diagnosis.safety_from_text(text) == "yes" and conv.step != st.CLOSED:
        if not conv.diagnosis or conv.diagnosis.get("concluded"):
            diagnosis.start(conv, text)
        await diagnosis.conclude(contact, conv, "gas_smell", 1.0, f"Tenant mentions a gas smell: \"{text[:120]}\"")
        return False
    # "My shower is cold": start the diagnosis (no gas question; centrix first, then max 3 questions)
    if text and not conv.case_id and not conv.diagnosis and conv.step == st.NEW and diagnosis.applies(text):
        conv.tenant_texts.append(text)
        if diagnosis.FRUSTRATED_RE.search(text):  # "no hot water, just send someone"
            diagnosis.start(conv, text)
            diagnosis.facts_from_centrix(contact, conv)
            await diagnosis.extract_answers(conv, text)
            await diagnosis.escalate_now(contact, conv, text)
            return False
        return bool(await diagnosis.begin(contact, conv, text, images))
    # After a self-help tip: "it worked" closes, "didn't work" sends a technician
    d = conv.diagnosis or {}
    fixed = diagnosis.fixed_from_text(text)
    if conv.step == st.SELF_HELP and d.get("concluded") and not images:
        if fixed is not None:
            conv.pending_options = []
            await diagnosis.on_follow_up(contact, d["concluded"], fixed)
            return False
        if text and fixed is None and not diagnosis.ACK_RE.fullmatch(text.strip()) and "?" not in text:
            from app.agent import choice
            from app.channels.base import Option

            cause = d["concluded"]
            opt = await choice.match(text, [Option(f"diagfu_yes:{cause}", "Yes, it's warm again"),
                                            Option(f"diagfu_no:{cause}", "No, still cold")],
                                     "Did the tip work, is the hot water back?")
            if opt is not None:
                conv.pending_options = []
                await diagnosis.on_follow_up(contact, cause, opt.id.startswith("diagfu_yes"))
                return False
        if text and diagnosis.ACK_RE.fullmatch(text.strip()) and not d.get("acked"):
            d["acked"] = True  # "ok, will try later": nothing to diagnose, just keep the door open
            from app.agent import outbound

            await outbound.text(contact, conv.case_id, diagnosis.say(conv, "Sounds good. Tell me how it goes.",
                                                                     "Gut. Sag mir, wie es läuft."))
            return False
    if diagnosis.active(conv) and text:
        if fixed is True:  # "it works again" in the middle of the questions
            await diagnosis.resolved_by_tenant(contact, conv, text)
            return False
        if diagnosis.FRUSTRATED_RE.search(text):
            await diagnosis.extract_answers(conv, text)
            await diagnosis.escalate_now(contact, conv, text)
            return False
    # a photo of the display (or a code typed in the text) during the diagnosis answers q_display
    if (images or text) and diagnosis.active(conv) and "q_display" not in conv.diagnosis["answers"]:
        code, _src = flow.detect_error_code([text or ""], images)
        if code:
            conv.error_code = conv.error_code or code
            conv.diagnosis["answers"]["q_display"] = "code"

    # A free-text answer to the open question ("sure", "just the shower", "Saturday works") is handled
    # exactly like the tap, so consent/slots are really recorded before anything is confirmed.
    in_diagnosis = diagnosis.active(conv)
    if in_diagnosis and conv.diagnosis.get("conflict_open"):
        diagnosis.resolve_conflict_reply(conv, text)  # "no", "everything": resolved or moved on, never looped
    if in_diagnosis and text:
        await diagnosis.extract_answers(conv, text)  # evidence first; the agent then asks/concludes
    if in_diagnosis:
        settled = diagnosis.decisive_self_help(conv.diagnosis, conv.error_code)
        if settled:
            await diagnosis.conclude(contact, conv, settled, 0.85, "Decisive answer: "
                                     + ", ".join(f"{q}={k}" for q, k in conv.diagnosis["answers"].items()),
                                     force=True)
            return False
    if text and not images and conv.pending_options and not in_diagnosis:
        # (during a diagnosis the model reads the whole message and records every answer in it)
        from app.agent import choice

        opt = await choice.match(text, conv.pending_options, conv.pending_question)
        if opt is not None:
            log.info("free text %r understood as %s", text[:40], opt.id)
            if await handle_button(contact, opt.id):
                return False
    return bool(await loop.run_tenant_turn(contact, text, images))


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
        elif kind in ("oneroom_ok", "oneroom_no"):
            await flow.on_one_room(contact, case_id, kind == "oneroom_ok")
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
            be.record_event(case_id, "system", "staff.attention", f"Button {button_id} failed: staff follow up", {})
            await outbound.text(contact, case_id, "Thanks. I've flagged this for your property management; they'll pick it up and get in touch.")
    return True
