"""Settings from env vars (and an optional .env file at the repo root or in backend/)."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
TZ = ZoneInfo("Europe/Berlin")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(BACKEND_DIR / ".env")),
        extra="ignore",
    )

    database_url: str = f"sqlite:///{(BACKEND_DIR / 'debye.db').as_posix()}"
    storage_dir: str = str(BACKEND_DIR / "storage")
    data_dir: str = str(REPO_ROOT / "data")
    partners_dir: str = str(REPO_ROOT / "partners")
    frontend_dist: str = str(REPO_ROOT / "frontend" / "dist")
    demo_mode: bool = True
    reseed_on_boot: bool = False  # RESEED_ON_BOOT=1: drop + re-seed the SQLite DB at startup
    public_base_url: str = "http://localhost:8000"

    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    wa_token: str | None = None
    wa_phone_number_id: str | None = None
    wa_verify_token: str | None = None
    wa_app_secret: str | None = None


settings = Settings()

# --- demo clock -------------------------------------------------------------
# "Skip to tomorrow" moves this offset forward; everything that needs "now" uses now().
_clock_offset = timedelta(0)


def now() -> datetime:
    return datetime.now(TZ) + _clock_offset


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def advance_clock(delta: timedelta) -> None:
    global _clock_offset
    _clock_offset += delta


def reset_clock() -> None:
    global _clock_offset
    _clock_offset = timedelta(0)
