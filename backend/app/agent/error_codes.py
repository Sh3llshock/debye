"""Boiler error codes, always explained (meaning first in plain words, the code in brackets).

Resident texts are English (Debye's default language; the model mirrors other languages).
Codes are the Vaillant ecoTEC ones from the seed (asset.known_error_codes).
"""
from __future__ import annotations

# code -> (what happened, what it means for the resident)
RESIDENT = {
    "F.22": ("the boiler's water pressure is too low", "so the heating switches itself off for safety"),
    "F.28": ("the boiler's ignition failed", "so the heating won't start"),
    "F.29": ("the boiler's flame went out while running", "so the heating keeps cutting out"),
}

EN = {
    "F.22": "water pressure too low",
    "F.28": "ignition failed",
    "F.29": "flame lost during operation",
}


TITLE = {
    "F.22": "water pressure too low",
    "F.28": "ignition failed",
    "F.29": "flame lost during operation",
}


def case_title(code: str | None) -> str:
    """Case summary for the staff page: 'No heating – ignition failed (F.28)'."""
    if not code:
        return "No heating"
    return f"No heating – {TITLE.get(code, 'boiler error')} ({code})"


def resident_sentence(code: str, source: str = "photo") -> str:
    """Meaning first, code in brackets:
    'On the photo I can see the boiler's ignition failed (error code F.28), so the heating won't start.'"""
    lead = "On the photo I can see" if source == "photo" else "That error means"
    meaning = RESIDENT.get(code)
    if not meaning:
        return f"{lead} there's a boiler fault (error code {code}). The technician will check what's behind it."
    what, effect = meaning
    return f"{lead} {what} (error code {code}), {effect}."


def timeline_summary(code: str) -> str:
    """'Boiler error: ignition failed (F.28)'"""
    return f"Boiler error: {EN.get(code, 'unknown code, technician to check')} ({code})"
