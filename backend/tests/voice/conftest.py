"""Voice tests run against the real backend (DB + services) with fake-send WhatsApp and no ElevenLabs key."""
import os
import sys
from pathlib import Path

import pytest

os.environ["DEBYE_NO_DOTENV"] = "1"
os.environ["WA_TOKEN"] = ""
os.environ["WA_FAKE_SEND"] = "1"
os.environ["DEMO_MODE"] = "1"
os.environ["ROUTER_DEBOUNCE"] = "0"
os.environ["VOICE_TOOL_SECRET"] = "test-secret"
os.environ.pop("ELEVENLABS_API_KEY", None)  # stub ElevenLabs: no background polling, no real calls
os.environ.pop("ELEVENLABS_WEBHOOK_SECRET", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/

H = {"X-Debye-Voice-Secret": "test-secret"}


@pytest.fixture
def app_client():
    from fastapi.testclient import TestClient

    from app import router as msg_router
    from app.agent import state
    from app.channels import whatsapp
    from app.main import app
    from app.seed import seed
    from app.voice import calls

    msg_router.DEBOUNCE_SECONDS = 0
    with TestClient(app) as c:
        seed(reset=True)
        state.reset_all()
        calls.reset_all()
        whatsapp.clear_outbox()
        yield c
