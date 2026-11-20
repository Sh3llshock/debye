"""Channel interface shared by WhatsApp and the web-chat fallback.

The agent and router never talk to a transport directly: they call
`channel_for(phone)` and use the `Channel` methods below. Whichever channel the
contact last wrote from is used for replies.
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("debye.channels")

# Limits enforced by WhatsApp; webchat applies the same so behaviour matches.
MAX_BUTTONS = 3
MAX_BUTTON_TITLE = 20
MAX_LIST_ROWS = 10
MAX_ROW_TITLE = 24
MAX_LIST_BUTTON = 20


def storage_dir() -> Path:
    p = Path(os.getenv("STORAGE_DIR", "storage"))
    p.mkdir(parents=True, exist_ok=True)
    return p


@dataclass
class Media:
    media_id: str
    mime: str
    filename: str | None = None
    caption: str | None = None
    local_path: str | None = None  # filled once downloaded

    @property
    def kind(self) -> str:
        if self.mime.startswith("audio/"):
            return "audio"
        if self.mime.startswith("image/"):
            return "image"
        if self.mime == "application/pdf":
            return "pdf"
        return "file"


@dataclass
class InboundMessage:
    channel: str  # "whatsapp" | "webchat"
    from_phone: str  # E.164 with leading +
    wa_message_id: str | None = None
    text: str | None = None
    button_id: str | None = None  # reply-button or list-row id
    button_title: str | None = None
    media: list[Media] = field(default_factory=list)
    profile_name: str | None = None


@dataclass
class Option:
    id: str
    title: str


class Channel(ABC):
    name: str

    @abstractmethod
    async def send_text(self, to: str, text: str) -> str | None: ...

    @abstractmethod
    async def send_buttons(self, to: str, text: str, options: list[Option]) -> str | None: ...

    @abstractmethod
    async def send_list(
        self, to: str, text: str, button_label: str, rows: list[Option], section_title: str = "Optionen"
    ) -> str | None: ...

    @abstractmethod
    async def send_media(
        self, to: str, kind: str, path: str, caption: str | None = None, mime: str | None = None
    ) -> str | None: ...

    @abstractmethod
    async def download_media(self, media: Media) -> str:
        """Saves inbound media to storage/ and returns the local path."""


def clamp_options(options: list[Option], limit: int, title_len: int) -> list[Option]:
    out = []
    for o in options[:limit]:
        out.append(Option(id=o.id[:200], title=o.title[:title_len]))
    if len(options) > limit:
        log.warning("dropped %d options over the limit of %d", len(options) - limit, limit)
    return out


def normalize_phone(raw: str) -> str:
    raw = raw.strip().replace(" ", "")
    return raw if raw.startswith("+") else "+" + raw


# ---------------------------------------------------------------- registry
_channels: dict[str, Channel] = {}
_last_channel: dict[str, str] = {}  # phone -> channel name


def register(channel: Channel) -> None:
    _channels[channel.name] = channel


def get_channel(name: str) -> Channel:
    return _channels[name]


def remember(phone: str, channel_name: str) -> None:
    _last_channel[normalize_phone(phone)] = channel_name


def channel_for(phone: str) -> Channel:
    """Channel the contact last used; WhatsApp by default."""
    name = _last_channel.get(normalize_phone(phone), "whatsapp")
    if name not in _channels:
        name = "whatsapp"
    return _channels[name]
