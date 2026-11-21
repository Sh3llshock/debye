import os
import sys
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="debye-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["STORAGE_DIR"] = str(_tmp / "storage")
os.environ["DEMO_MODE"] = "1"
# never send real approval emails from tests (the repo .env may hold an AgentMail key)
os.environ["APPROVAL_EMAIL_ENABLED"] = "0"
os.environ["AGENTMAIL_API_KEY"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.seed import seed

    with TestClient(app) as c:
        seed(reset=True)
        yield c
