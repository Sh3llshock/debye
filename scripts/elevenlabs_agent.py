"""Create or update the ElevenLabs Conversational AI agent "Debye" (idempotent). Prints only the agent id.

    python scripts/elevenlabs_agent.py --base https://<tunnel-or-render-url>

Needs in .env (or the environment): ELEVENLABS_API_KEY, VOICE_TOOL_SECRET.
Optional: ELEVENLABS_AGENT_VOICE_ID (English voice), ELEVENLABS_AGENT_LLM, PUBLIC_BASE_URL (default for --base).
Tools are matched by name and the agent by name ("Debye"), so running it again updates them in place.
Put the printed id into .env as ELEVENLABS_AGENT_ID. See docs/voice-setup.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

API = "https://api.elevenlabs.io/v1"
AGENT_NAME = os.getenv("ELEVENLABS_AGENT_NAME") or "Debye"  # another name = separate test agent + tools
TOOL_PREFIX = ("debye" if AGENT_NAME == "Debye" else AGENT_NAME.lower().replace(" ", "_")) + "_"  # debye_identify_caller, debye_report_issue
DEFAULT_VOICE = "EXAVITQu4vr4xnSDxMaL"  # "Sarah": ElevenLabs default voice (English, warm, calm), in every workspace
LANGUAGE = "en"
DEFAULT_LLM = "gemini-2.5-flash"  # low latency on a phone line
TTS_MODEL = "eleven_flash_v2"  # English agents require turbo/flash v2 (ElevenLabs rule); lowest latency

PROMPT = """\
You are Debye, the AI assistant of the property manager reltix. Residents call you about problems in their \
apartment, usually heating or hot water. On the phone you are the same Debye as on WhatsApp: the case continues \
in the chat afterwards.

What you already know about the caller (from reltix / centrix)
- Name: {{tenant_name}}. Unit: {{unit_label}}. Address: {{address}}. Boiler: {{boiler}}.
- Open cases: {{open_case_summary}}
If the address is not "unknown", you already know who is calling: do NOT call identify_caller. Never ask for \
name, address, floor or boiler model. Only if the address is "unknown" (a phone call from a number we could not \
look up yet) call identify_caller once.

How you speak
- English, friendly and calm, like a kind property manager. Very short sentences, this is a phone call. \
At most one question at a time. No lists, no jargon.
- Before a tool call say a short filler like "One second, I'll note that." Use at most one tool call per call (plus end_call). Tools answer within seconds. If a \
tool fails or takes too long, don't call it again: say "Sorry, my system is a bit slow. I'll send you everything \
on WhatsApp right after this call." and continue.

Heating (radiators cold)
1. If open cases says a heating case for the building is already open, say it's already reported and being \
handled. Do not open a new one.
2. Otherwise let them describe it. Ask once whether all radiators are cold or only one. If they read out a display \
code (e.g. "F 28"), don't ask about it again.
3. Call report_issue with issue_type "heating" (summary: one short English sentence without the code; \
all_radiators_cold: "yes"/"no"/"unknown"; error_code only if mentioned).
4. Read the "say" sentence from the result word for word. It explains an error code correctly: meaning first, \
then the code. Never start with the code yourself.

Hot water (cold shower, no warm water)
Ask these one at a time, in your own short words, and skip any the caller already answered. No tool call in between:
{hot_water_questions}
Then call report_issue ONCE with issue_type "hot_water", the caller's words as symptoms, and answers like "q_safety=no; q_scope=only_shower; q_hot_water_use=no; q_wait_result=stays_cold" (only the keys listed above). If the caller smells gas: call report_issue right away with answers "q_safety=yes" and priority "emergency", then read its "say" calmly and end the call. Otherwise read the "say" sentence from the result.

Ending
- Do NOT ask for consent to share data on the phone; that happens afterwards on WhatsApp. Say the WhatsApp \
follow-up only once. Say a short goodbye using their name and end the conversation with end_call.

Rules
- Never promise costs or appointments. The heating company proposes times.
- Never ask anyone to open the boiler, work on gas parts or reset anything inside the device.
- Gas smell, smoke, water leaking, or someone feels unwell: leave the apartment right away or close the \
main water valve, call 112 (for gas, the gas supplier's emergency line), then report_issue with priority "emergency".
- Other topics (rent, contract): answer briefly if you know, otherwise the property manager will get back to them.
"""

FIRST_MESSAGE = "Hi {{tenant_name}}, this is Debye from reltix. What's going on?"

DYNAMIC_DEFAULTS = {  # used when a call starts without them (e.g. a phone call before the init webhook is set up)
    "contact_id": "unknown", "tenant_name": "there", "unit_label": "unknown", "address": "unknown",
    "boiler": "unknown", "open_case_summary": "unknown",
}

CALLER_PROPS = {
    "conversation_id": {"type": "string", "dynamic_variable": "system__conversation_id"},
    "caller_id": {"type": "string", "dynamic_variable": "system__caller_id"},
    "contact_id": {"type": "string", "dynamic_variable": "contact_id"},
}

KB = Path(__file__).resolve().parents[1] / "data" / "diagnosis" / "no_hot_water.json"
PHONE_QUESTIONS = ("q_scope", "q_hot_water_use", "q_wait_result")  # same list as backend/app/voice/calls.py


def hot_water_questions() -> str:
    kb = json.loads(KB.read_text(encoding="utf-8"))
    qs = {q["id"]: q for q in kb["questions"]}
    lines = [f'- q_safety: "{kb["safety_first"]["question"]}" (always first). Keys: yes, no']
    for qid in PHONE_QUESTIONS:
        q = qs[qid]
        keys = ", ".join(f"{k} ({v})" for k, v in q["answers"].items())
        lines.append(f'- {qid}: "{q["text"]}" Keys: {keys}')
    return "\n".join(lines)


TOOL_TIMEOUT = 5  # seconds; our endpoints answer in well under 1 s


def _webhook(base: str, secret: str, name: str, description: str, path: str, props: dict, required: list[str],
             interruptible: bool = False) -> dict:
    return {
        "type": "webhook",
        "name": TOOL_PREFIX + name,
        "description": description,
        "response_timeout_secs": TOOL_TIMEOUT,
        "force_pre_tool_speech": True,  # say a filler first, so the caller doesn't talk over a silent tool call
        "disable_interruptions": not interruptible,  # caller speech must not abandon the tool call
        "api_schema": {
            "url": f"{base}{path}",
            "method": "POST",
            "request_headers": {"X-Debye-Voice-Secret": secret},
            "request_body_schema": {"type": "object", "description": "Tool input", "properties": props,
                                    "required": required},
        },
    }


def tool_configs(base: str, secret: str) -> list[dict]:
    return [
        _webhook(base, secret, "identify_caller",
                 "Phone calls only, and only if the caller's address is 'unknown': look up the caller in reltix "
                 "(first name, address, heating, open cases). Never call it when the caller is already known.",
                 "/api/voice/tools/identify_caller", CALLER_PROPS, []),
        _webhook(base, secret, "report_issue",
                 "Report the caller's problem, once, after the questions. Heating: opens (or joins) the repair "
                 "case. Hot water: records the diagnosis answers; the diagnosis continues on WhatsApp.",
                 "/api/voice/tools/report_issue", {
                     **CALLER_PROPS,
                     "issue_type": {"type": "string", "description": "'heating' (radiators cold), 'hot_water' (cold shower / no warm water) or 'other'"},
                     "summary": {"type": "string", "description": "One short English sentence without the error code, e.g. 'Heating cold since this morning'"},
                     "symptoms": {"type": "string", "description": "What the caller said, in English"},
                     "error_code": {"type": "string", "description": "Boiler display code if the caller read one out, e.g. 'F.28'. Empty if none."},
                     "all_radiators_cold": {"type": "string", "description": "Heating only: 'yes', 'no' (only one room) or 'unknown'"},
                     "priority": {"type": "string", "description": "'urgent' normally, 'emergency' for gas smell, smoke, flooding"},
                     "answers": {"type": "string", "description": "Hot water only: the diagnosis answers as 'q_safety=no; q_scope=only_shower; ...'"},
                 }, ["summary", "issue_type"]),
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
                    "prompt": PROMPT.replace("{hot_water_questions}", hot_water_questions()),
                    "llm": os.getenv("ELEVENLABS_AGENT_LLM") or DEFAULT_LLM,
                    "temperature": 0.3,
                    "tool_ids": tool_ids,
                    "built_in_tools": {"end_call": {"name": "end_call", "description": "", "params": {"system_tool_type": "end_call"}}},
                },
                "dynamic_variables": {"dynamic_variable_placeholders": DYNAMIC_DEFAULTS},
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
