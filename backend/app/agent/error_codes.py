"""Boiler error codes, always explained (meaning in plain words, the code alongside).

German for the resident on WhatsApp, English for the staff timeline. Codes are the
Vaillant ecoTEC ones from the seed (asset.known_error_codes).
"""
from __future__ import annotations

# code -> (German: what happened, German: what the resident notices)
DE = {
    "F.22": ("der Wasserdruck ist zu niedrig", "die Heizung schaltet sich zum Schutz ab"),
    "F.28": ("die Zündung ist fehlgeschlagen", "die Heizung startet nicht"),
    "F.29": ("die Flamme ist im Betrieb ausgegangen", "die Heizung geht immer wieder aus"),
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


def resident_sentence(code: str) -> str:
    """'Am Display sehe ich den Fehler F.28 – das heißt, die Zündung ist fehlgeschlagen (die Heizung startet nicht).'"""
    meaning = DE.get(code)
    if not meaning:
        return f"Am Display sehe ich den Fehler {code}. Was er genau bedeutet, klärt der Techniker vor Ort."
    what, effect = meaning
    return f"Am Display sehe ich den Fehler {code} – das heißt, {what} ({effect})."


def timeline_summary(code: str) -> str:
    """'Boiler error: ignition failed (F.28)'"""
    return f"Boiler error: {EN.get(code, 'unknown code, technician to check')} ({code})"
