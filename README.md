# Debye (AI assistant)

**reltix's AI assistant in the resident's WhatsApp, plugged into centrix.** A resident sends one voice note about a broken heater; Debye opens the case, gets consent, sends the job to the right heating installer's partner page, books a slot with the resident on WhatsApp, and files the invoice on the unit. Staff follow everything live on their own page. Zero calls, zero forms.

Built for the reltix track "Plug a Partner into centrix" at MAIN Maastricht 2026.

## Docs

| File | What it is |
|---|---|
| [docs/interfaces.md](docs/interfaces.md) | Team contracts: who owns which files, Python and REST interfaces, v2 product decisions |
| [docs/technical-plan.md](docs/technical-plan.md) | Architecture, data model, channels, agent, partner layer, work packages |
| [docs/connector-spec.md](docs/connector-spec.md) | The partner connector spec (deliverable): manifest, lifecycle, transports, consent |
| [docs/pitch-plan.md](docs/pitch-plan.md) | Flow choice, demo story, 3-minute pitch, Q&A prep |
| [partners/](partners/) | One connector manifest per partner (3 heating installers, 1 internet provider) |
| [data/seed.json](data/seed.json) | Seed data for the centrix mock |

## Status

Planning done; build in progress. Work is tracked as GitHub issues with milestones:
M1 WhatsApp round-trip → M2 Golden path end to end → M3 Hosted V1 → M4 Feature freeze → M5 Submit.

## Run (once the backend exists)

```bash
cp .env.example .env            # fill in keys
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload
cloudflared tunnel --url http://localhost:8000   # webhook URL for Meta
```

## Running fully local (open-source model, no cloud AI)

On this branch Debye's AI runs on the laptop: an open-source model through [Ollama](https://ollama.com), voice notes through
[faster-whisper](https://github.com/SYSTRAN/faster-whisper). No OpenAI or Anthropic key is needed and no resident message,
photo or invoice leaves the machine. Everything else (WhatsApp channels, centrix stand-in, staff / partner / technician pages,
scripted fallbacks) is unchanged.

| Part | Local implementation |
|---|---|
| Chat turns (diagnosis, tool calls) | `qwen3.5:2b` (Alibaba Qwen, Apache-2.0; 1.9B, Q8, tools + vision) via Ollama's OpenAI-compatible API, same tool-calling loop as `gpt-6-luna` (`backend/app/agent/openai_loop.py`) |
| Boiler photo (error code) | same model, vision input (photos downscaled to 512 px) |
| Free-text answers to buttons | same model, JSON-schema output (`agent/choice.py`) |
| Invoice extraction | PDF text via `pypdf` → model with a JSON schema; invoice photos go in as images |
| Voice notes | `faster-whisper` `base` on the CPU (int8) |

Setup (Windows, macOS or Linux):

```bash
# 1. Ollama: https://ollama.com/download  (Windows: winget install Ollama.Ollama)
ollama pull qwen3.5:2b
ollama create debye-local -f ollama/Modelfile     # same model, 8k context (Ollama's default 4096 is too small)
# 2. backend
cp .env.example .env                              # LLM_PROVIDER=ollama is the default here
cd backend && pip install -r requirements.txt     # adds pypdf, faster-whisper, pillow
uvicorn app.main:app --port 8000
```

At startup the server warms the model (loads it and runs the system prompt once) and loads Whisper, so the first resident
message doesn't pay that cost. `OLLAMA_MODEL` takes any Ollama model with tool calling (`llama3.1:8b`, `qwen2.5:7b-instruct`
and others) if the machine has a GPU or more free RAM.

**Why `qwen3.5:2b`:** the demo laptop has no GPU (Intel Core 5 120U, integrated graphics, 16 GB RAM with ~1–2 GB free
while the demo stack runs). A 7–8B model would need ~5 GB more RAM and run 3–4× slower on this CPU. `qwen3.5:2b` is the
smallest model that does tool calls *and* reads the boiler display (it read F.28 correctly in every run).

**Latency on that laptop** (CPU only, `scripts/simulate.py` golden path, other apps running):

| Step | Time |
|---|---|
| Debye turn (voice note + photo → case opened, triage question) | 34–42 s |
| Debye turn (photo after the case is open → error code noted) | 40–49 s |
| Debye turn (neighbour reports the same fault → linked, duplicate notice) | 30–45 s |
| Free-text answer → button option (`choice.model_match`) | 6–8 s |
| Voice-note transcription (faster-whisper base, ~6 s note) | 3–8 s |
| Invoice extraction (PDF → JSON) | 20–25 s |
| Model warm-up at server start | 14–45 s |
| Taps (consent, slots, "fixed") | instant, no model involved |

For comparison, `gpt-6-luna` takes 1–3 s per turn. Each model call on this CPU re-reads the whole prompt (~1,700 tokens at
30–150 tokens/s depending on load: `qwen3.5` is a hybrid recurrent model, so Ollama can't reuse a cached prompt prefix),
then writes at ~8 tokens/s. That's why the turn budget is 120 s here (`AGENT_TIMEOUT`, 20 s with the cloud models) and the
scripted fallback still answers if the model is slower than that or Ollama isn't running.

**Small-model guardrails** (only with `LLM_PROVIDER=ollama`): a shorter system prompt (`LOCAL_SYSTEM` in
`agent/prompts.py`); after `open_case` / `note_error_code` the follow-up message (triage buttons, duplicate notice, error-code
sentence) is sent deterministically instead of by a second model call; plain-text answers without a tool call are delivered
as a reply; triage buttons sent before a case exists become `open_case`. In testing, `qwen3.5:2b` on its own asked a neighbour the triage question on a duplicate case, wrote vague button
texts, sent `"None"` as an error code and retried a rejected tool call until the timeout. The model still does the
understanding: symptom, the error code from the photo, the case summary and priority.

## Assumptions

- Tenant phone numbers come from the lease; tenants opt in to WhatsApp at onboarding.
- The property manager has framework agreements with local trades, including price lists and a per-job auto-approval limit.
- Heating repairs are the landlord's cost.
- Boiler make, model and service history come from the PM's maintenance records.
- centrix is mocked with seeded data (no reltix API exists for the hackathon).
