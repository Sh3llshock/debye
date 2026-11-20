"""LLM_PROVIDER=ollama: local model through Ollama's OpenAI-compatible API (no network in these tests)."""
import asyncio
from types import SimpleNamespace


def _resp(content=None, tool_calls=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls, refusal=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def create(self, **kw):
        self.calls.append(kw)
        return self.responses.pop(0)


def test_settings_and_timeout(monkeypatch):
    from app import local_llm
    from app.agent import loop

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("AGENT_TIMEOUT", raising=False)
    assert local_llm.enabled()
    assert local_llm.base_url() == "http://localhost:11434/v1"
    assert local_llm.model() == "debye-local"
    assert local_llm.extra_params()["reasoning_effort"] == "none"
    assert loop.turn_timeout() == 120.0
    monkeypatch.setenv("AGENT_TIMEOUT", "30")
    assert loop.turn_timeout() == 30.0
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("AGENT_TIMEOUT")
    assert loop.turn_timeout() == 20.0


def test_trim_history_starts_at_user():
    from app.agent.openai_loop import trim_history

    msgs = []
    for i in range(10):
        msgs += [{"role": "user", "content": f"u{i}"},
                 {"role": "assistant", "content": None, "tool_calls": [{"id": f"t{i}"}]},
                 {"role": "tool", "tool_call_id": f"t{i}", "content": "{}"}]
    out = trim_history(msgs, keep=8)
    assert out[0]["role"] == "user" and len(out) <= 8
    assert out[-1] is msgs[-1]


def test_local_loop_uses_ollama_model_and_delivers_plain_text(monkeypatch):
    """A small model answering in plain text (no tool call) still reaches the resident."""
    from app.agent import openai_loop
    from app.agent.tools import TurnContext

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1:8b")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    fake = FakeCompletions([_resp(content="Oh no, I'm on it!")])
    openai_loop.set_client(SimpleNamespace(chat=SimpleNamespace(completions=fake)))
    sent = []

    async def fake_execute(block, ctx):
        sent.append((block.name, block.input))
        ctx.sent += 1
        return {"content": "{}"}

    monkeypatch.setattr(openai_loop, "execute", fake_execute)
    ctx = TurnContext(contact=None, conv=SimpleNamespace())
    try:
        asyncio.run(openai_loop.run_loop([{"role": "user", "content": "cold shower"}], ctx, 5))
    finally:
        openai_loop.set_client(None)
    assert fake.calls[0]["model"] == "llama3.1:8b"
    assert fake.calls[0]["reasoning_effort"] == "none"
    assert sent == [("reply", {"text": "Oh no, I'm on it!"})]


def test_choice_model_match_runs_locally_without_openai_key(monkeypatch):
    from app import local_llm
    from app.agent import choice
    from app.channels.base import Option

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    fake = FakeCompletions([_resp(content='{"choice": "cold_some:C1"}')])
    monkeypatch.setattr(local_llm, "client", lambda timeout, max_retries=0: SimpleNamespace(
        chat=SimpleNamespace(completions=fake)))
    opts = [Option("cold_all:C1", "All cold"), Option("cold_some:C1", "Just one room")]
    got = asyncio.run(choice.model_match("only the shower is cold", opts, "Are all radiators cold?"))
    assert got.id == "cold_some:C1"
    assert fake.calls[0]["model"] == local_llm.model()


def test_local_invoice_from_pdf_text(monkeypatch, tmp_path):
    from app import local_llm, media

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setattr(media, "pdf_text", lambda p: "Rechnung RE-1 ... Brutto 119,00")
    fake = FakeCompletions([_resp(content='{"invoice_number": "RE-1", "date": "2026-11-21", "net_eur": 100, '
                                          '"vat_eur": 19, "gross_eur": 119, "line_items": [{"desc": "Arbeit", '
                                          '"qty": 1, "unit_price": 100}], "labour_hours": 1}')])
    monkeypatch.setattr(local_llm, "client", lambda timeout, max_retries=0: SimpleNamespace(
        chat=SimpleNamespace(completions=fake)))
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    inv = asyncio.run(media.extract_invoice(str(pdf)))
    assert (inv["invoice_number"], inv["gross_eur"]) == ("RE-1", 119)
    assert "Brutto 119,00" in fake.calls[0]["messages"][0]["content"]


def test_local_invoice_falls_back_when_ollama_is_down(monkeypatch, tmp_path):
    from app import local_llm, media

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setattr(media, "pdf_text", lambda p: "some text")

    def broken(timeout, max_retries=0):
        raise ConnectionError("ollama not running")

    monkeypatch.setattr(local_llm, "client", broken)
    assert asyncio.run(media.extract_invoice(str(tmp_path / "x.pdf")))["gross_eur"] == 237.41


def test_local_transcription_falls_back_to_demo_line(monkeypatch, tmp_path):
    from app import local_llm, media
    from app.config import settings

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "demo_mode", True)

    def broken(path, language=None):
        raise RuntimeError("faster-whisper missing")

    monkeypatch.setattr(local_llm, "transcribe_sync", broken)
    assert asyncio.run(media.transcribe(str(tmp_path / "x.ogg"))) == media.DEMO_TRANSCRIPT
    monkeypatch.setattr(local_llm, "transcribe_sync", lambda p, language=None: "Die Dusche ist kalt.")
    assert asyncio.run(media.transcribe(str(tmp_path / "x.ogg"))) == "Die Dusche ist kalt."


def test_local_follow_up_duplicate_and_new_case(monkeypatch):
    import json as _json

    from app.agent import flow, openai_loop
    from app.agent.tools import TurnContext

    sent = []

    async def dup(contact, cid):
        sent.append(("dup", cid))

    async def cold(contact, cid, prefix=""):
        sent.append(("cold", cid, prefix))

    monkeypatch.setattr(flow, "send_duplicate_notice", dup)
    monkeypatch.setattr(flow, "ask_cold", cold)
    ctx = TurnContext(contact=None, conv=SimpleNamespace(tenant_texts=["no hot water"], error_code=None))
    done = [("open_case", {"priority": "urgent"}, _json.dumps({"case_id": "C1", "duplicate": True}))]
    assert asyncio.run(openai_loop.local_follow_up(done, ctx)) and sent == [("dup", "C1")]
    sent.clear()
    done = [("open_case", {"priority": "urgent", "error_code": "F.28"}, _json.dumps(
        {"case_id": "C2", "duplicate": False, "explain_error_code": "text-sentence",
         "explain_error_code_if_from_photo": "photo-sentence"}))]
    assert asyncio.run(openai_loop.local_follow_up(done, ctx))
    assert sent == [("cold", "C2", "Oh no 😕 photo-sentence I'm on it.")]
    sent.clear()
    done = [("open_case", {"priority": "emergency"}, _json.dumps({"case_id": "C3", "duplicate": False}))]
    assert not asyncio.run(openai_loop.local_follow_up(done, ctx)) and sent == []


def test_repair_call_opens_case_before_triage():
    from app.agent.openai_loop import repair_call
    from app.agent.tools import TurnContext

    ctx = TurnContext(contact=None, conv=SimpleNamespace(case_id=None, tenant_texts=["no hot water"]))
    args = {"text": "?", "options": [{"id": "cold_all:x", "title": "All cold"}]}
    name, new = repair_call("ask_buttons", args, ctx)
    assert name == "open_case" and new["symptoms"] == "no hot water"
    ctx.conv.case_id = "C1"
    assert repair_call("ask_buttons", args, ctx) == ("ask_buttons", args)
