import os
import sys
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="debye-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["STORAGE_DIR"] = str(_tmp / "storage")
os.environ["DEMO_MODE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.seed import seed

    with TestClient(app) as c:
        seed(reset=True)
        yield c


# ---------------------------------------------------------------------------------------------
# Portal auth (app.auth): the flow tests act as staff, partner and technician through the HTTP API.
# When a test sends no Authorization header, add the token of the role that owns the URL:
#   /api/staff, /api/partners, /api/stream, /files → staff · /api/partner/<pid> → that partner ·
#   /api/tech/<tid> → that technician. Tests that check enforcement pass headers={"Authorization": ""}.
def _auto_token(url) -> str | None:
    from urllib.parse import urlsplit

    from app import auth

    path = urlsplit(str(url)).path
    parts = path.strip("/").split("/")
    if path.startswith("/api/staff") or path in ("/api/partners", "/api/stream") or path.startswith("/files/"):
        return auth.make_token("staff", "c_401")
    if path.startswith("/api/partner/") and len(parts) >= 3:
        return auth.make_token("partner", parts[2], parts[2])
    if path.startswith("/api/tech/") and len(parts) >= 3:
        return auth.make_token("tech", parts[2])
    return None


def _install_auto_token() -> None:
    from starlette.testclient import TestClient

    if getattr(TestClient, "_debye_auto_token", False):
        return
    orig = TestClient.request

    def request(self, method, url, *args, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        if not any(k.lower() == "authorization" for k in headers) and "authorization" not in self.headers:
            tok = _auto_token(url)
            if tok:
                headers["Authorization"] = f"Bearer {tok}"
                kwargs["headers"] = headers
        return orig(self, method, url, *args, **kwargs)

    TestClient.request = request
    TestClient._debye_auto_token = True


_install_auto_token()
