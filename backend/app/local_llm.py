"""Fully local mode (LLM_PROVIDER=ollama): an open-source model served by Ollama on this machine.

Ollama exposes an OpenAI-compatible API (http://localhost:11434/v1), so the agent reuses the
OpenAI tool-calling loop with a different base URL and model. No cloud key is needed and no
resident data leaves the machine. Voice notes are transcribed with faster-whisper (also local).

  OLLAMA_BASE_URL   default http://localhost:11434/v1
  OLLAMA_MODEL      default debye-local = qwen3.5:2b (tools + vision) with num_ctx 8192 (ollama/Modelfile)
  OLLAMA_THINK      default off ("none"); set to "low"/"medium"/"high" to let the model think
  WHISPER_MODEL     default base (faster-whisper: tiny / base / small ...)
"""
from __future__ import annotations

import os

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "debye-local"  # qwen3.5:2b with an 8k context, built by ollama/Modelfile
DEFAULT_WHISPER = "base"
# CPU inference is slower than the cloud model: the per-turn budget is raised from 20 s to 120 s
# (measured on an Intel Core 5 120U without GPU: 25-90 s per turn, see README "Running fully local").
DEFAULT_TURN_TIMEOUT = 120.0


def provider() -> str:
    return (os.getenv("LLM_PROVIDER") or "openai").strip().lower()


def enabled() -> bool:
    return provider() == "ollama"


def base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL") or DEFAULT_BASE_URL


def model() -> str:
    return os.getenv("OLLAMA_MODEL") or DEFAULT_MODEL


def reasoning_effort() -> str | None:
    """Ollama maps reasoning_effort "none" to think=false (thinking models like qwen3.5)."""
    v = os.getenv("OLLAMA_THINK")
    return "none" if v is None else (v or None)


def client(timeout: float, max_retries: int = 0):
    from openai import AsyncOpenAI

    return AsyncOpenAI(base_url=base_url(), api_key="ollama", timeout=timeout, max_retries=max_retries)


def extra_params() -> dict:
    """Sampling for reliable tool calls: the model's own defaults (temperature 1) are tuned for chat."""
    extra: dict = {"temperature": float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))}
    effort = reasoning_effort()
    if effort:
        extra["reasoning_effort"] = effort
    return extra


# Photos: vision tokens grow with resolution and CPU prefill runs ~35 tokens/s, so boiler photos are
# downscaled before they go to the local model (an F.28 on the display stays readable at 512 px).
MAX_IMAGE_SIDE = int(os.getenv("OLLAMA_MAX_IMAGE_SIDE", "512"))


def shrink_image(data: bytes) -> tuple[bytes, str] | None:
    """JPEG bytes no larger than MAX_IMAGE_SIDE on the long side; None if Pillow can't read it."""
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(data))
        img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=85)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return None


async def warmup() -> None:
    """Loads the model and caches the system prompt + tools prefix (first CPU prefill ~60 s), and
    loads faster-whisper, so the first resident message doesn't hit the turn timeout."""
    import asyncio
    import logging
    import time

    from app.agent.openai_loop import TOOLS
    from app.agent.prompts import LOCAL_SYSTEM

    log = logging.getLogger("debye.local_llm")
    t0 = time.perf_counter()
    try:
        await client(timeout=300).chat.completions.create(
            model=model(),
            messages=[{"role": "system", "content": LOCAL_SYSTEM}, {"role": "user", "content": "warm-up, ignore"}],
            tools=TOOLS, max_tokens=1, **extra_params(),
        )
        log.info("local model %s warm in %.1fs", model(), time.perf_counter() - t0)
    except Exception as exc:
        log.warning("local model warm-up failed (%s); is Ollama running with %s pulled?", exc, model())
    try:
        await asyncio.to_thread(_whisper_model)
    except Exception as exc:
        log.warning("faster-whisper not available (%s); voice notes use the demo transcript", exc)


# ---------------------------------------------------------------- local speech-to-text
_whisper = None


def _whisper_model():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel

        _whisper = WhisperModel(os.getenv("WHISPER_MODEL") or DEFAULT_WHISPER, device="cpu", compute_type="int8")
    return _whisper


def transcribe_sync(path: str, language: str | None = None) -> str:
    segments, _info = _whisper_model().transcribe(
        path,
        language=language,
        beam_size=1,
        initial_prompt="A tenant reports a problem with the heating in their flat.",
    )
    return " ".join(s.text.strip() for s in segments).strip()
