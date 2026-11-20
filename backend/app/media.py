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
_openai_base_url: str | None = os.getenv("OPENAI_BASE_URL") or None  # None = SDK default

DEMO_TRANSCRIPT = "Hi, die Heizung ist kalt seit heute Morgen."


def _demo_mode() -> bool:
    from app.channels.base import demo_mode

    return demo_mode()


async def transcribe(path: str, language: str = "de") -> str:
    """Voice note → text. Without a key or on failure: a canned line in DEMO_MODE, else ""."""
    if not os.getenv("OPENAI_API_KEY"):
        log.warning("OPENAI_API_KEY not set; %s", "using demo transcript" if _demo_mode() else "no transcript")
        return DEMO_TRANSCRIPT if _demo_mode() else ""
    global _openai_base_url
    from openai import AsyncOpenAI

    audio = Path(path).read_bytes()
    for model in ("gpt-4o-transcribe", "whisper-1"):
        for _attempt in range(2):
            client = AsyncOpenAI(timeout=20, base_url=_openai_base_url)
            t0 = time.perf_counter()
            try:
                result = await client.audio.transcriptions.create(
                    model=model,
                    file=(Path(path).name, audio),
                    language=language,
                    prompt="Mieterin meldet ein Problem mit der Heizung in ihrer Wohnung.",
                )
            except Exception as exc:
                # EU-resident OpenAI projects must use the EU endpoint; switch once and remember.
                if "geography" in str(exc).lower() and _openai_base_url != EU_OPENAI_BASE_URL:
                    log.warning("OpenAI project is region-bound; switching to %s", EU_OPENAI_BASE_URL)
                    _openai_base_url = EU_OPENAI_BASE_URL
                    continue
                log.exception("transcription with %s failed", model)
                break
            text = (getattr(result, "text", None) or "").strip()
            log.info("transcribed %s with %s in %.2fs", Path(path).name, model, time.perf_counter() - t0)
            if text:
                return text
            break
    return DEMO_TRANSCRIPT if _demo_mode() else ""


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


async def extract_invoice(path: str) -> dict:
    """Invoice PDF (or image) → fields. Falls back to the demo invoice on any error."""
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
                        {
                            "type": "text",
                            "text": "Extract this German tradesman invoice. Amounts in EUR as numbers "
                            "(net, VAT, gross). One line item per invoice line.",
                        },
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
