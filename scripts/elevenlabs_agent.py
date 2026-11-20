"""Create or update the ElevenLabs Conversational AI agent "Debye" (idempotent). Prints only the agent id.

    python scripts/elevenlabs_agent.py --base https://<tunnel-or-render-url>

Needs in .env (or the environment): ELEVENLABS_API_KEY, VOICE_TOOL_SECRET.
Optional: ELEVENLABS_AGENT_VOICE_ID (German voice), ELEVENLABS_AGENT_LLM, PUBLIC_BASE_URL (default for --base).
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
DEFAULT_VOICE = "60AkIxCFeI9yJsEdAuaf"  # "Simona – German, Calm, Social" (shared library, native German)
DEFAULT_LLM = "gemini-2.5-flash"  # low latency on a phone line
TTS_MODEL = "eleven_flash_v2_5"  # multilingual + lowest latency

PROMPT = """\
Du bist Debye, der AI assistant der Hausverwaltung reltix. Bewohner:innen rufen dich an, meist wegen einer \
kaputten Heizung. Am Telefon bist du dieselbe Debye wie auf WhatsApp: der Fall läuft danach im Chat weiter.

So sprichst du
- Deutsch, informelles "du", freundlich und ruhig wie eine nette Hausverwaltung. Sehr kurze Sätze, \
das ist ein Telefonat. Höchstens eine Frage auf einmal. Keine Listen, kein Fachjargon.

Ablauf
1. Ruf zuerst identify_caller auf. Begrüße die Person mit Vornamen. Frag nie nach Adresse, Etage, \
Name oder Kesselmodell: das weiß reltix schon (steht im Ergebnis von identify_caller).
2. Wenn open_cases schon einen Heizungsfall hat, sag, dass er schon gemeldet ist und bearbeitet wird. \
Öffne keinen neuen.
3. Sonst: lass dir das Problem kurz schildern. Frag einmal, ob alle Heizkörper kalt sind oder nur einer. \
Wenn die Person einen Fehlercode vom Display vorliest (z. B. "F 28"), frag nicht weiter danach.
4. Ruf report_issue auf (summary: ein kurzer deutscher Satz, z. B. "Heizung seit heute Morgen kalt"; \
all_radiators_cold: "yes"/"no"/"unknown"; error_code nur, wenn genannt).
5. Lies danach den Satz "say" aus dem Ergebnis von report_issue wörtlich vor, ohne eigene Erklärung davor. Er erklärt einen Fehlercode schon richtig: erst die Bedeutung, dann der Code. Fang nie selbst mit dem Code an ("F.28 bedeutet ..." ist falsch). Nenne nie einen Code ohne seine Bedeutung.
6. Die Einwilligung zur Datenweitergabe fragst du NICHT am Telefon ab, das passiert danach auf WhatsApp. Wiederhole "say" nicht. Verabschiede dich kurz mit Namen und beende das Gespräch mit end_call.

Regeln
- Versprich keine Kosten und keine Termine. Der Betrieb schlägt Termine vor.
- Bitte nie, den Kessel zu öffnen, an Gasteilen zu arbeiten oder etwas im Gerät zurückzusetzen.
- Gasgeruch, Rauch, Wasser läuft aus oder jemandem geht es schlecht: sofort raus aus der Wohnung bzw. \
Haupthahn zu, 112 anrufen (bei Gas den Notdienst des Gasversorgers), dann report_issue mit priority "emergency".
- Andere Themen (Miete, Vertrag): kurz beantworten, wenn du es weißt, sonst meldet sich die Hausverwaltung.
"""

FIRST_MESSAGE = "Hallo, hier ist Debye von reltix. Einen Moment, ich schau kurz, wer anruft."

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
                        "summary": {"type": "string", "description": "One short German sentence without the error code, e.g. 'Heizung seit heute Morgen kalt'"},
                        "symptoms": {"type": "string", "description": "What the caller said, in German"},
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
    shared = check(http.get(f"{API}/shared-voices", params={"language": "de", "page_size": 100}), "shared voices")
    match = next((v for v in shared.get("voices", []) if v.get("voice_id") == voice_id), None)
    if not match:
        fail(f"voice {voice_id} is neither in the workspace nor in the German voice library")
    added = check(http.post(f"{API}/voices/add/{match['public_owner_id']}/{voice_id}",
                            json={"new_name": f"Debye – {match.get('name', 'German')}"[:60]}), "add voice")
    return added.get("voice_id") or voice_id


def agent_body(tool_ids: list[str], voice_id: str) -> dict:
    return {
        "name": AGENT_NAME,
        "tags": ["debye", "hackathon"],
        "conversation_config": {
            "agent": {
                "language": "de",
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
