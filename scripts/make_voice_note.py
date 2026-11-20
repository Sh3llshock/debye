"""Generate the English demo voice note with OpenAI TTS (ogg/opus, the format WhatsApp voice notes use).

    python scripts/make_voice_note.py            # writes data/demo/voice_note_hot_water_en.ogg

Needs OPENAI_API_KEY (and optionally OPENAI_BASE_URL, e.g. the EU endpoint) in the environment or .env.
One TTS call; run it only when the text changes.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "demo" / "voice_note_hot_water_en.ogg"
TEXT = "Hi, there's no hot water in the shower since this morning, and something is blinking on the boiler."
MODEL = "gpt-4o-mini-tts"
VOICE = "coral"
INSTRUCTIONS = "A tenant leaving a short, slightly annoyed but friendly WhatsApp voice note. Natural pace."


def load_env() -> None:
    for f in (ROOT / ".env", ROOT / "backend" / ".env"):
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and v and not os.environ.get(k):
                        os.environ[k] = v
        except OSError:
            pass


def main() -> None:
    load_env()
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY missing")
    from openai import OpenAI

    client = OpenAI(base_url=os.getenv("OPENAI_BASE_URL") or None, timeout=60)
    with client.audio.speech.with_streaming_response.create(
        model=MODEL, voice=VOICE, input=TEXT, instructions=INSTRUCTIONS, response_format="opus",
    ) as resp:
        resp.stream_to_file(OUT)
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
