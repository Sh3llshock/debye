"""Media helpers (interfaces §3.5): voice-note transcription and invoice extraction."""
from __future__ import annotations

import base64
import logging
import os
import time
from pathlib import Path

from pydantic import BaseModel, Field

log = logging.getLogger("debye.media")

MODEL = "claude-opus-5-5"


# ---------------------------------------------------------------- transcription (OpenAI, event sponsor)
EU_OPENAI_BASE_URL = "https://eu.api.openai.com/v1"
TRANSCRIBE_MODELS = ("gpt-4o-transcribe", "gpt-4o-mini-transcribe", "whisper-1")  # all offered on the EU host


def openai_base_url() -> str:
    """OPENAI_BASE_URL from env/.env; default EU, because our OpenAI project is EU-region only."""
    return os.getenv("OPENAI_BASE_URL") or EU_OPENAI_BASE_URL

DEMO_TRANSCRIPT = "Hi, the heating has been cold since this morning."


def _demo_mode() -> bool:
    from app.channels.base import demo_mode

    return demo_mode()


async def _transcribe_local(path: str, language: str | None = None) -> str:
    """LLM_PROVIDER=ollama: faster-whisper on the CPU (WHISPER_MODEL, default base)."""
    import asyncio

    from app import local_llm

    t0 = time.perf_counter()
    try:
        text = await asyncio.to_thread(local_llm.transcribe_sync, path, language)
    except Exception:
        log.exception("local transcription (faster-whisper) failed")
        text = ""
    log.info("transcribed %s locally in %.2fs", Path(path).name, time.perf_counter() - t0)
    return text or (DEMO_TRANSCRIPT if _demo_mode() else "")


async def transcribe(path: str, language: str | None = None) -> str:
    """Voice note → text. Without a key or on failure: a canned line in DEMO_MODE, else ""."""
    from app import local_llm

    if local_llm.enabled():
        return await _transcribe_local(path, language)
    if not os.getenv("OPENAI_API_KEY"):
        log.warning("OPENAI_API_KEY not set; %s", "using demo transcript" if _demo_mode() else "no transcript")
        return DEMO_TRANSCRIPT if _demo_mode() else ""
    from openai import AsyncOpenAI

    audio = Path(path).read_bytes()
    base_url = openai_base_url()
    for model in TRANSCRIBE_MODELS:
        for _attempt in range(2):
            client = AsyncOpenAI(timeout=20, base_url=base_url)
            t0 = time.perf_counter()
            try:
                result = await client.audio.transcriptions.create(
                    model=model,
                    file=(Path(path).name, audio),
                    prompt="A tenant reports a problem with the heating in their flat.",
                    **({"language": language} if language else {}),  # None: auto-detect (English by default, any language works)
                )
            except Exception as exc:
                # EU-resident OpenAI projects must use the EU endpoint; switch once and remember.
                if "geography" in str(exc).lower() and base_url != EU_OPENAI_BASE_URL:
                    log.warning("OpenAI project is EU-region only; retrying on %s", EU_OPENAI_BASE_URL)
                    base_url = EU_OPENAI_BASE_URL
                    continue
                log.exception("transcription with %s failed", model)
                break
            text = (getattr(result, "text", None) or "").strip()
            log.info("transcribed %s with %s in %.2fs", Path(path).name, model, time.perf_counter() - t0)
            if text:
                return text
            break
    return DEMO_TRANSCRIPT if _demo_mode() else ""


# ---------------------------------------------------------------- voice reply (ElevenLabs, event sponsor, optional)
ELEVENLABS_DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"  # premade English voice ("Rachel"); ELEVENLABS_VOICE_ID overrides
ELEVENLABS_MODEL = "eleven_multilingual_v2"


async def speak(text: str) -> str | None:
    """Text → WhatsApp voice note (ogg/opus) via ElevenLabs. None if no key or anything fails (no-op)."""
    key = os.getenv("ELEVENLABS_API_KEY")
    if not key:
        return None
    import shutil
    import subprocess
    import uuid

    import httpx

    voice = os.getenv("ELEVENLABS_VOICE_ID") or ELEVENLABS_DEFAULT_VOICE
    from app.channels.base import storage_dir

    out_dir = storage_dir() / "tts"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"debye_{uuid.uuid4().hex[:10]}.ogg"
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
                params={"output_format": "opus_48000_64"},
                headers={"xi-api-key": key, "accept": "audio/ogg"},
                json={"text": text, "model_id": ELEVENLABS_MODEL, "language_code": os.getenv("ELEVENLABS_LANGUAGE", "en")},
            )
        if r.status_code >= 400:
            log.warning("ElevenLabs TTS failed: %s %s", r.status_code, r.text[:200])
            return None
        audio = r.content
        if audio[:4] == b"OggS":
            dest.write_bytes(audio)
        else:  # not an ogg container (e.g. mp3): convert for WhatsApp voice notes if ffmpeg is there
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                log.warning("ElevenLabs returned non-ogg audio and ffmpeg is missing; skipping voice reply")
                return None
            raw = dest.with_suffix(".bin")
            raw.write_bytes(audio)
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(raw), "-c:a", "libopus", "-b:a", "48k",
                            str(dest)], check=True, timeout=20)
            raw.unlink(missing_ok=True)
        log.info("ElevenLabs voice reply in %.2fs (%d bytes)", time.perf_counter() - t0, dest.stat().st_size)
        return str(dest)
    except Exception:
        log.exception("ElevenLabs TTS failed")
        return None


# ---------------------------------------------------------------- invoice extraction (Claude structured output)
class LineItem(BaseModel):
    desc: str
    qty: float
    unit_price: float


class Invoice(BaseModel):
    invoice_number: str
    date: str = Field(description="ISO date YYYY-MM-DD")
    net_eur: float
    vat_eur: float
    gross_eur: float
    line_items: list[LineItem]
    labour_hours: float = Field(description="Total labour hours billed; 0 if none")


FALLBACK_INVOICE = {  # matches data/demo/invoice_RE-2026-1187.pdf
    "invoice_number": "RE-2026-1187",
    "date": "2026-11-21",
    "net_eur": 199.5,
    "vat_eur": 37.91,
    "gross_eur": 237.41,
    "line_items": [
        {"desc": "Anfahrtspauschale (Rahmenvertrag)", "qty": 1, "unit_price": 89.0},
        {"desc": "Arbeitszeit Heizungstechniker, Std.", "qty": 1, "unit_price": 72.0},
        {"desc": "Zündelektrode Vaillant ecoTEC plus (0020107800)", "qty": 1, "unit_price": 38.5},
    ],
    "labour_hours": 1.0,
    "_source": "fallback",
}


INVOICE_PROMPT = (
    "Extract this German tradesman invoice. Amounts in EUR as numbers (net, VAT, gross). "
    "One line item per invoice line."
)


async def extract_invoice(path: str) -> dict:
    """Invoice PDF (or image) → fields, with the provider from LLM_PROVIDER (default openai).
    Falls back to the demo invoice (RE-2026-1187, gross 237.41) on any error or without a key."""
    provider = (os.getenv("LLM_PROVIDER") or "openai").strip().lower()
    if provider == "anthropic":
        return await _extract_invoice_anthropic(path)
    if provider == "ollama":
        return await _extract_invoice_local(path)
    return await _extract_invoice_openai(path)


# JSON schema for Ollama's structured output (inlined, no $refs)
INVOICE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "invoice_number": {"type": "string"},
        "date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
        "net_eur": {"type": "number"},
        "vat_eur": {"type": "number"},
        "gross_eur": {"type": "number"},
        "line_items": {"type": "array", "items": {
            "type": "object",
            "properties": {"desc": {"type": "string"}, "qty": {"type": "number"}, "unit_price": {"type": "number"}},
            "required": ["desc", "qty", "unit_price"]}},
        "labour_hours": {"type": "number", "description": "Total labour hours billed; 0 if none"},
    },
    "required": ["invoice_number", "date", "net_eur", "vat_eur", "gross_eur", "line_items", "labour_hours"],
}


LOCAL_INVOICE_PROMPT = INVOICE_PROMPT + (
    " date as YYYY-MM-DD. labour_hours is the quantity of the labour line (Arbeitszeit / Std. / hours), "
    "not an amount of money; 0 if there is no labour line."
)
_LABOUR_WORDS = ("arbeitszeit", "arbeitsstunde", "std", "stunde", "labour", "labor", "hour")


def tidy_invoice(d: dict) -> dict:
    """Small models get the shape right but slip on details: German dates, money as labour hours."""
    import re

    m = re.fullmatch(r"\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*", str(d.get("date") or ""))
    if m:
        d["date"] = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    items = d.get("line_items") or []
    labour = sum(float(li.get("qty") or 0) for li in items
                 if any(w in str(li.get("desc", "")).lower() for w in _LABOUR_WORDS))
    hours = d.get("labour_hours")
    money = {d.get("net_eur"), d.get("vat_eur"), d.get("gross_eur")}
    if hours is None or hours in money or (labour and abs(float(hours) - labour) > 0.01):
        d["labour_hours"] = labour
    return d


def pdf_text(path: str) -> str:
    from pypdf import PdfReader

    return "\n".join((page.extract_text() or "") for page in PdfReader(path).pages).strip()


async def _extract_invoice_local(path: str) -> dict:
    """LLM_PROVIDER=ollama: PDF → text (pypdf) → local model with a JSON schema.
    Photos of invoices go to the model as an image (qwen3.5 is vision-capable)."""
    import json

    from app import local_llm

    try:
        suffix = Path(path).suffix.lower()
        if suffix == ".pdf":
            text = pdf_text(path)
            if not text:
                log.warning("invoice PDF has no text layer; using fallback")
                return dict(FALLBACK_INVOICE)
            content: list | str = f"{INVOICE_PROMPT}\n\nInvoice text:\n{text[:6000]}"
        else:
            data = base64.standard_b64encode(Path(path).read_bytes()).decode()
            mime = {".png": "image/png", ".webp": "image/webp"}.get(suffix, "image/jpeg")
            content = [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}},
                       {"type": "text", "text": LOCAL_INVOICE_PROMPT}]
        extra = local_llm.extra_params()
        extra["temperature"] = 0
        client = local_llm.client(timeout=120)
        t0 = time.perf_counter()
        r = await client.chat.completions.create(
            model=local_llm.model(),
            messages=[{"role": "user", "content": content}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": "invoice", "schema": INVOICE_JSON_SCHEMA}},
            **extra,
        )
        inv = Invoice.model_validate(tidy_invoice(json.loads(r.choices[0].message.content or "{}")))
        log.info("invoice extracted locally in %.2fs", time.perf_counter() - t0)
        return inv.model_dump()
    except Exception:
        log.exception("local invoice extraction failed; using fallback")
        return dict(FALLBACK_INVOICE)


async def _extract_invoice_openai(path: str) -> dict:
    if not os.getenv("OPENAI_API_KEY"):
        log.warning("OPENAI_API_KEY not set; returning fallback invoice")
        return dict(FALLBACK_INVOICE)
    try:
        from openai import AsyncOpenAI

        data = base64.standard_b64encode(Path(path).read_bytes()).decode()
        suffix = Path(path).suffix.lower()
        if suffix == ".pdf":  # gpt-6-luna reads PDFs directly (verified), no page rendering needed
            part = {"type": "file", "file": {"filename": Path(path).name,
                                             "file_data": f"data:application/pdf;base64,{data}"}}
        else:
            mime = {".png": "image/png", ".webp": "image/webp"}.get(suffix, "image/jpeg")
            part = {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}
        extra = {}
        effort = os.getenv("OPENAI_INVOICE_REASONING_EFFORT", "low")
        if effort:
            extra["reasoning_effort"] = effort
        client = AsyncOpenAI(base_url=openai_base_url(), timeout=60, max_retries=1)
        t0 = time.perf_counter()
        response = await client.chat.completions.parse(
            model=os.getenv("OPENAI_CHAT_MODEL") or "gpt-6-luna",
            messages=[{"role": "user", "content": [part, {"type": "text", "text": INVOICE_PROMPT}]}],
            response_format=Invoice,
            **extra,
        )
        msg = response.choices[0].message
        if getattr(msg, "refusal", None) or msg.parsed is None:
            log.warning("invoice extraction gave no result (refusal=%r)", getattr(msg, "refusal", None))
            return dict(FALLBACK_INVOICE)
        log.info("invoice extracted in %.2fs", time.perf_counter() - t0)
        return msg.parsed.model_dump()
    except Exception:
        log.exception("invoice extraction failed; using fallback")
        return dict(FALLBACK_INVOICE)


async def _extract_invoice_anthropic(path: str) -> dict:
    if not os.getenv("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY not set; returning fallback invoice")
        return dict(FALLBACK_INVOICE)
    try:
        import anthropic

        data = base64.standard_b64encode(Path(path).read_bytes()).decode()
        suffix = Path(path).suffix.lower()
        if suffix == ".pdf":
            block = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}
        else:
            mime = {".png": "image/png", ".webp": "image/webp"}.get(suffix, "image/jpeg")
            block = {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}}
        client = anthropic.AsyncAnthropic(timeout=60)
        response = await client.messages.parse(
            model=MODEL,
            max_tokens=4000,
            output_config={"effort": "medium"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        block,
                        {"type": "text", "text": INVOICE_PROMPT},
                    ],
                }
            ],
            output_format=Invoice,
        )
        if response.stop_reason == "refusal" or response.parsed_output is None:
            log.warning("invoice extraction stopped: %s", response.stop_reason)
            return dict(FALLBACK_INVOICE)
        return response.parsed_output.model_dump()
    except Exception:
        log.exception("invoice extraction failed; using fallback")
        return dict(FALLBACK_INVOICE)
