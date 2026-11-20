"""Default provider (OpenAI Chat Completions) with a stubbed model."""
import asyncio
import json

from agent_stubs import oa_call

LENA = "490000000001"
_n = 0


def wa_text(body, from_=LENA):
    global _n
    _n += 1
    return {"entry": [{"changes": [{"value": {"messages": [
        {"from": from_, "id": f"wamid.oa.{_n}", "type": "text", "text": {"body": body}}]}}]}]}


def button(id_, title="t"):
    global _n
    _n += 1
    return {"entry": [{"changes": [{"value": {"messages": [
        {"from": LENA, "id": f"wamid.oa.{_n}", "type": "interactive",
         "interactive": {"type": "button_reply", "button_reply": {"id": id_, "title": title}}}]}}]}]}


def outbox(client):
    return client.get("/webhooks/whatsapp/_outbox").json()["messages"]


def test_openai_triage_turn(client, svc, gpt):
    stub = gpt([
        [oa_call("open_case", summary="Heizung kalt, Fehler F.28", symptoms="komplett kalt", error_code="F.28",
                 priority="urgent")],
        [oa_call("ask_buttons", text="Am Display sehe ich F.28. Sind alle Heizkörper kalt?",
                 options=[{"id": "cold_all:case_0001", "title": "Überall kalt"},
                          {"id": "cold_some:case_0001", "title": "Nur ein Raum"}])],
        "",
    ])
    client.post("/webhooks/whatsapp", json=wa_text("Heizung kalt, F.28"))
    req = stub.requests[0]
    assert req["model"] == "gpt-6-luna" and req["reasoning_effort"] == "none" and req["tool_choice"] == "auto"
    assert req["messages"][0]["role"] == "system" and "Debye" in req["messages"][0]["content"]
    assert all(t["type"] == "function" and t["function"]["strict"] for t in req["tools"])
    assert {t["function"]["name"] for t in req["tools"]} >= {"reply", "ask_buttons", "ask_list", "open_case"}
    # tool results go back as role=tool with the call id
    second = stub.requests[1]["messages"]
    assert second[-1]["role"] == "tool" and json.loads(second[-1]["content"])["case_id"] == "case_0001"
    assert second[-2]["role"] == "assistant" and second[-2]["tool_calls"][0]["function"]["name"] == "open_case"
    last = outbox(client)[-1]["payload"]
    assert [b["reply"]["id"] for b in last["interactive"]["action"]["buttons"]] == [
        "cold_all:case_0001", "cold_some:case_0001"]
    # taps stay deterministic: no model call
    n = len(stub.requests)
    client.post("/webhooks/whatsapp", json=button("cold_all:case_0001", "Überall kalt"))
    assert len(stub.requests) == n
    assert "weitergeben" in outbox(client)[-1]["payload"]["interactive"]["body"]["text"]


def test_openai_history_carries_over(client, svc, gpt):
    stub = gpt([[oa_call("reply", text="Hallo Lena!")], "", [oa_call("reply", text="Gern!")], ""])
    client.post("/webhooks/whatsapp", json=wa_text("Hallo"))
    client.post("/webhooks/whatsapp", json=wa_text("Danke"))
    msgs = stub.requests[2]["messages"]
    roles = [m["role"] for m in msgs]
    assert roles[:5] == ["system", "user", "assistant", "tool", "assistant"] and roles[-1] == "user"


def test_openai_errors_fall_back(client, svc, gpt):
    gpt([RuntimeError("OpenAI down")])
    client.post("/webhooks/whatsapp", json=wa_text("Heizung kalt"))
    assert outbox(client)[-1]["payload"]["interactive"]["body"]["text"].endswith("kalt oder nur einer?")


def test_openai_refusal_hands_off(client, svc, gpt):
    gpt(["refusal"])
    client.post("/webhooks/whatsapp", json=wa_text("hallo"))
    assert "Hausverwaltung" in outbox(client)[-1]["payload"]["text"]["body"]


def test_openai_silent_turn_falls_back(client, svc, gpt):
    gpt(["Ich würde fragen, ob alles kalt ist."])  # plain text instead of a tool: never delivered
    client.post("/webhooks/whatsapp", json=wa_text("Heizung kalt"))
    payload = outbox(client)[-1]["payload"]
    assert payload["type"] == "interactive"  # scripted cold question, not the stray text


def test_openai_bad_tool_args_reported(client, svc, gpt):
    from types import SimpleNamespace

    bad = SimpleNamespace(id="call_bad", type="function", function=SimpleNamespace(name="reply", arguments="{not json"))
    stub = gpt([[bad], [oa_call("reply", text="Wie kann ich helfen?")], ""])
    client.post("/webhooks/whatsapp", json=wa_text("hi"))
    tool_msg = stub.requests[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["content"].startswith("Error")
    assert outbox(client)[-1]["payload"]["text"]["body"] == "Wie kann ich helfen?"


def test_provider_switch_resets_history(client, svc, gpt, monkeypatch):
    from app.agent import state

    gpt([[oa_call("reply", text="Hallo!")], ""])
    client.post("/webhooks/whatsapp", json=wa_text("Hallo"))
    conv = state.conversation("c_202")
    assert conv.history_provider == "openai" and conv.history
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from app.agent import loop

    loop.set_client(None)
    client.post("/webhooks/whatsapp", json=wa_text("Und jetzt?"))  # no key: scripted reply, fresh history
    assert conv.history_provider == "anthropic"
    assert all(isinstance(m["content"], list) for m in conv.history)


def test_invoice_openai_structured_output(monkeypatch, tmp_path):
    import openai

    from app import media

    seen = {}

    class FakeCompletions:
        async def parse(self, **kw):
            seen.update(kw)
            inv = media.Invoice(**{k: v for k, v in media.FALLBACK_INVOICE.items() if k != "_source"})
            return type("R", (), {"choices": [type("C", (), {"message": type("M", (), {
                "parsed": inv, "refusal": None})()})()]})()

    class FakeClient:
        def __init__(self, **kw):
            seen["base_url"] = kw.get("base_url")
            self.chat = type("Ch", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-key")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    pdf = tmp_path / "inv.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    out = asyncio.run(media.extract_invoice(str(pdf)))
    assert out["gross_eur"] == 237.41 and "_source" not in out
    part = seen["messages"][0]["content"][0]
    assert part["type"] == "file" and part["file"]["file_data"].startswith("data:application/pdf;base64,")
    assert seen["response_format"] is media.Invoice and seen["model"] == "gpt-6-luna"
    assert seen["base_url"] == media.EU_OPENAI_BASE_URL


def test_invoice_fallback_without_openai_key(monkeypatch, tmp_path):
    from app import media

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert asyncio.run(media.extract_invoice(str(tmp_path / "x.pdf")))["gross_eur"] == 237.41


def test_note_error_code_tool(client, svc, gpt):
    gpt([
        [oa_call("open_case", summary="Heizung kalt", symptoms="kalt", error_code=None, priority="urgent")],
        [oa_call("ask_buttons", text="Sind alle Heizkörper kalt?", options=[
            {"id": "cold_all:case_0001", "title": "Überall kalt"}, {"id": "cold_some:case_0001", "title": "Nur ein Raum"}])],
        "",
        [oa_call("note_error_code", case_id="case_0001", error_code="F.28")],
        [oa_call("reply", text="Am Display sehe ich F.28 – das habe ich im Fall notiert.")],
        "",
    ])
    client.post("/webhooks/whatsapp", json=wa_text("Heizung kalt"))
    client.post("/webhooks/whatsapp", json=wa_text("Foto vom Kessel"))
    assert ("error_code", "case_0001", "F.28") in svc.calls
    assert svc.cases["case_0001"]["error_code"] == "F.28"
