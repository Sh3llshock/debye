"""Create or update the ElevenLabs Conversational AI agent "Debye" (idempotent). Prints only the agent id.

    python scripts/elevenlabs_agent.py --base https://<tunnel-or-render-url>

Needs in .env (or the environment): ELEVENLABS_API_KEY, VOICE_TOOL_SECRET.
Optional: ELEVENLABS_AGENT_VOICE_ID (English voice), ELEVENLABS_AGENT_LLM, PUBLIC_BASE_URL (default for --base).
Tools are matched by name and the agent by name ("Debye"), so running it again updates them in place.
Put the printed id into .env as ELEVENLABS_AGENT_ID. See docs/voice-setup.md.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx

API = "https://api.elevenlabs.io/v1"
AGENT_NAME = "Debye"
TOOL_PREFIX = "debye_"  # tool names in the workspace: debye_identify_caller, debye_report_issue
DEFAULT_VOICE = "EXAVITQu4vr4xnSDxMaL"  # "Sarah": ElevenLabs default voice (English, warm, calm), in every workspace
LANGUAGE = "en"
DEFAULT_LLM = "gemini-2.5-flash"  # low latency on a phone line
TTS_MODEL = "eleven_flash_v2"  # English agents require turbo/flash v2 (ElevenLabs rule); lowest latency

PROMPT = """\
You are Debye, the AI assistant of the property manager reltix. Residents call you, usually because their \
heating has stopped working. On the phone you are the same Debye as on WhatsApp: the case continues in the chat afterwards.

How you speak
- English, friendly and calm, like a kind property manager. Very short sentences, this is a phone call. \
At most one question at a time. No lists, no jargon.

Steps
1. Call identify_caller first. Greet the person by first name. Never ask for address, floor, name or \
boiler model: reltix already knows them (they are in the identify_caller result).
2. If open_cases already contains a heating case, say it has already been reported and is being handled. \
Do not open a new one.
3. Otherwise: let them describe the problem briefly. Ask once whether all radiators are cold or only one. \
If the person reads out an error code from the display (e.g. "F 28"), don't ask about it again.
4. Call report_issue (summary: one short English sentence, e.g. "Heating cold since this morning"; \
all_radiators_cold: "yes"/"no"/"unknown"; error_code only if mentioned).
5. Then read out the "say" sentence from the report_issue result word for word, with no explanation of your own before it. It already explains an error code correctly: meaning first, then the code. Never start with the code yourself ("F.28 means ..." is wrong). Never mention a code without its meaning.
6. Do NOT ask for consent to share data on the phone; that happens afterwards on WhatsApp. Don't repeat "say". Say a short goodbye using their name and end the conversation with end_call.

Rules
- Never promise costs or appointments. The heating company proposes times.
- Never ask anyone to open the boiler, work on gas parts or reset anything inside the device.
- Gas smell, smoke, water leaking, or someone feels unwell: leave the apartment right away or close the \
main water valve, call 112 (for gas, the gas supplier's emergency line), then report_issue with priority "emergency".
- Other topics (rent, contract): answer briefly if you know, otherwise the property manager will get back to them.
"""

FIRST_MESSAGE = "Hi, this is Debye from reltix. One moment, let me check who's calling."

CALLER_PROPS = {
    "conversation_id": {"type": "string", "dynamic_variable": "system__conversation_id"},
    "caller_id": {"type": "string", "dynamic_variable": "system__caller_id"},
    "contact_id": {"type": "string", "dynamic_variable": "contact_id"},
}


def tool_configs(base: str, secret: str) -> list[dict]:
    headers = {"X-Debye-Voice-Secret": secret}
    return [
        {
            "type": "webhook",
            "name": TOOL_PREFIX + "identify_caller",
            "description": "Look up who is calling in reltix (centrix): first name, address, floor, heating "
                           "system, open cases. Call this first, before anything else.",
            "response_timeout_secs": 10,
            "api_schema": {
                "url": f"{base}/api/voice/tools/identify_caller",
                "method": "POST",
                "request_headers": headers,
                "request_body_schema": {
                    "type": "object",
                    "description": "Caller identity (filled automatically)",
                    "properties": CALLER_PROPS,
                    "required": [],
                },
            },
        },
        {
            "type": "webhook",
            "name": TOOL_PREFIX + "report_issue",
            "description": "Open (or join) the repair case for the caller's problem. Call as soon as you "
                           "understand it is a heating or hot-water fault; call again if you learn whether all "
                           "radiators are cold.",
            "response_timeout_secs": 15,
            "api_schema": {
                "url": f"{base}/api/voice/tools/report_issue",
                "method": "POST",
                "request_headers": headers,
                "request_body_schema": {
                    "type": "object",
                    "description": "The reported problem",
                    "properties": {
                        **CALLER_PROPS,
                        "summary": {"type": "string", "description": "One short English sentence without the error code, e.g. 'Heating cold since this morning'"},
                        "symptoms": {"type": "string", "description": "What the caller said, in English"},
                        "error_code": {"type": "string", "description": "Boiler display code if the caller read one out, e.g. 'F.28'. Empty if none."},
                        "all_radiators_cold": {"type": "string", "description": "'yes', 'no' (only one room) or 'unknown'"},
                        "priority": {"type": "string", "description": "'urgent' normally, 'emergency' for gas smell, smoke, flooding"},
                    },
                    "required": ["summary"],
                },
            },
        },
    ]


def load_env() -> None:
    root = Path(__file__).resolve().parents[1]
    for f in (root / ".env", root / "backend" / ".env"):
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


def fail(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(1)


def check(r: httpx.Response, what: str) -> dict:
    if r.status_code >= 300:
        fail(f"{what}: HTTP {r.status_code} {r.text[:500]}")
    return r.json() if r.content else {}


def upsert_tools(http: httpx.Client, configs: list[dict]) -> list[str]:
    existing = {}
    for t in check(http.get(f"{API}/convai/tools"), "list tools").get("tools", []):
        name = (t.get("tool_config") or {}).get("name")
        if name:
            existing[name] = t["id"]
    ids = []
    for cfg in configs:
        if cfg["name"] in existing:
            tid = existing[cfg["name"]]
            check(http.patch(f"{API}/convai/tools/{tid}", json={"tool_config": cfg}), f"update {cfg['name']}")
        else:
            tid = check(http.post(f"{API}/convai/tools", json={"tool_config": cfg}), f"create {cfg['name']}")["id"]
        ids.append(tid)
    return ids


def ensure_voice(http: httpx.Client, voice_id: str) -> str:
    """Library (shared) voices must be added to the workspace before an agent can use them."""
    if http.get(f"{API}/voices/{voice_id}").status_code == 200:
        return voice_id
    shared = check(http.get(f"{API}/shared-voices", params={"language": LANGUAGE, "page_size": 100}), "shared voices")
    match = next((v for v in shared.get("voices", []) if v.get("voice_id") == voice_id), None)
    if not match:
        fail(f"voice {voice_id} is neither in the workspace nor in the English voice library")
    added = check(http.post(f"{API}/voices/add/{match['public_owner_id']}/{voice_id}",
                            json={"new_name": f"Debye – {match.get('name', 'English')}"[:60]}), "add voice")
    return added.get("voice_id") or voice_id


def agent_body(tool_ids: list[str], voice_id: str) -> dict:
    return {
        "name": AGENT_NAME,
        "tags": ["debye", "hackathon"],
        "conversation_config": {
            "agent": {
                "language": LANGUAGE,
                "first_message": FIRST_MESSAGE,
                "prompt": {
                    "prompt": PROMPT,
                    "llm": os.getenv("ELEVENLABS_AGENT_LLM") or DEFAULT_LLM,
                    "temperature": 0.3,
                    "tool_ids": tool_ids,
                    "built_in_tools": {"end_call": {"name": "end_call", "description": "", "params": {"system_tool_type": "end_call"}}},
                },
                "dynamic_variables": {"dynamic_variable_placeholders": {"contact_id": "unknown"}},
            },
            "tts": {"voice_id": voice_id, "model_id": TTS_MODEL},
            "conversation": {"max_duration_seconds": 300},
        },
    }


def main() -> None:
    load_env()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--base", default=os.getenv("PUBLIC_BASE_URL"), help="public https URL of the backend")
    a = p.parse_args()
    key, secret = os.getenv("ELEVENLABS_API_KEY"), os.getenv("VOICE_TOOL_SECRET")
    if not key:
        fail("ELEVENLABS_API_KEY missing")
    if not secret:
        fail("VOICE_TOOL_SECRET missing (any long random string, same value on the server)")
    base = (a.base or "").rstrip("/")
    if not base.startswith("https://"):
        fail("--base must be the public https URL (cloudflared tunnel or Render), ElevenLabs calls it")
    with httpx.Client(headers={"xi-api-key": key}, timeout=30) as http:
        tool_ids = upsert_tools(http, tool_configs(base, secret))
        voice_id = ensure_voice(http, os.getenv("ELEVENLABS_AGENT_VOICE_ID") or DEFAULT_VOICE)
        body = agent_body(tool_ids, voice_id)
        found = [ag for ag in check(http.get(f"{API}/convai/agents", params={"search": AGENT_NAME}), "list agents")
                 .get("agents", []) if ag.get("name") == AGENT_NAME]
        if found:
            agent_id = found[0]["agent_id"]
            check(http.patch(f"{API}/convai/agents/{agent_id}", json=body), "update agent")
        else:
            agent_id = check(http.post(f"{API}/convai/agents/create", json=body), "create agent")["agent_id"]
    print(agent_id)


if __name__ == "__main__":
    main()
