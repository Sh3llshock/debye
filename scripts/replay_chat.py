#!/usr/bin/env python3
"""Replays a tenant chat against the real router + agent (LLM from .env), fake WhatsApp send,
fresh database. Prints what Debye sends after each tenant message.

    python scripts/replay_chat.py                      # Luka's chat from the PR 106 review
    python scripts/replay_chat.py "no hot water" "all taps" "no one" "the screen is dark" "fuse fixed it"
    REPLAY_RUNS=3 python scripts/replay_chat.py        # several runs (the model is not deterministic)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
_tmp = Path(tempfile.mkdtemp(prefix="debye-replay-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_tmp / 'replay.db').as_posix()}")
os.environ.setdefault("STORAGE_DIR", str(_tmp / "storage"))
os.environ.update({"DEMO_MODE": "1", "WA_FAKE_SEND": "1", "WA_PROVIDER": "meta", "ROUTER_DEBOUNCE": "0",
                   "ELEVENLABS_API_KEY": "", "DIAGNOSIS_FOLLOWUP_SECONDS": "86400"})

LUKA = ["my shower is cold", "sinks too", "no", "everything", "as I was cooking just now"]
PHONE = "490000000001"  # c_202 (Luka)


def main(msgs: list[str]) -> int:
    import app.channels.base  # noqa: F401  (.env)
    from fastapi.testclient import TestClient

    from app.agent import state
    from app.channels import whatsapp
    from app.main import app
    from app.seed import seed

    with TestClient(app) as client:
        for run in range(int(os.getenv("REPLAY_RUNS", "1"))):
            seed(reset=True)
            state.reset_all()
            whatsapp.clear_outbox()
            seen = 0
            print(f"--- run {run + 1}")
            for i, text in enumerate(msgs):
                client.post("/webhooks/whatsapp", json={"entry": [{"changes": [{"value": {"messages": [
                    {"from": PHONE, "id": f"wamid.replay.{run}.{i}.{time.time_ns()}", "type": "text",
                     "text": {"body": text}}]}}]}]})
                print(f"T: {text}")
                out = whatsapp.outbox(seen)
                if out:
                    seen = out[-1]["seq"]
                for m in out:
                    p = m["payload"]
                    if p["type"] == "text":
                        print(f"D: {p['text']['body']}")
                    else:
                        it = p["interactive"]
                        opts = [b["reply"]["title"] for b in it["action"].get("buttons", [])] or \
                            [r["title"] for s in it["action"].get("sections", []) for r in s["rows"]]
                        print(f"D: {it['body']['text']}  [{' | '.join(opts)}]")
            d = state.conversation("c_202").diagnosis or {}
            print(f"=> concluded: {d.get('concluded')}, answers: {d.get('answers')}, asked: {d.get('asked')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or LUKA))
