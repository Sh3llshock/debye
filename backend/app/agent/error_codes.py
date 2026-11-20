"""Boiler error codes, always explained (meaning in plain words, the code alongside).

German for the resident on WhatsApp, English for the staff timeline. Codes are the
Vaillant ecoTEC ones from the seed (asset.known_error_codes).
"""
from __future__ import annotations

# code -> (German "dass ..." clause, German consequence for the resident)
DE = {
    "F.22": ("der Wasserdruck zu niedrig ist", "die Heizung schaltet sich deshalb zum Schutz ab"),
    "F.28": ("die Zündung fehlgeschlagen ist", "die Heizung startet deshalb nicht"),
    "F.29": ("die Flamme im Betrieb ausgegangen ist", "die Heizung geht deshalb immer wieder aus"),
}

EN = {
    "F.22": "water pressure too low",
    "F.28": "ignition failed",
    "F.29": "flame lost during operation",
}


TITLE_DE = {
    "F.22": "Wasserdruck zu niedrig",
    "F.28": "Zündung fehlgeschlagen",
    "F.29": "Flamme im Betrieb ausgegangen",
}


def case_title(code: str | None) -> str:
    """Case summary for the staff page: 'Heizung kalt – Zündung fehlgeschlagen (F.28)'."""
    if not code:
        return "Heizung kalt"
    return f"Heizung kalt – {TITLE_DE.get(code, 'Kesselfehler')} ({code})"


def resident_sentence(code: str, source: str = "photo") -> str:
    """Meaning first, code in brackets:
    'Auf dem Foto sehe ich, dass die Zündung fehlgeschlagen ist (Fehlercode F.28) – die Heizung startet deshalb nicht.'"""
    lead = "Auf dem Foto sehe ich" if source == "photo" else "Der Kessel meldet"
    meaning = DE.get(code)
    if not meaning:
        return f"{lead} eine Störung (Fehlercode {code}). Was genau dahintersteckt, klärt der Techniker vor Ort."
    what, effect = meaning
    return f"{lead}, dass {what} (Fehlercode {code}) – {effect}."


def timeline_summary(code: str) -> str:
    """'Boiler error: ignition failed (F.28)'"""
    return f"Boiler error: {EN.get(code, 'unknown code, technician to check')} ({code})"
