# STUB – replaced by agent-whatsapp
"""Media helpers (interfaces §3.5). Fixed outputs so the backend runs before the real one lands."""
from __future__ import annotations

import logging

log = logging.getLogger("debye.media")


async def transcribe(path: str, language: str = "de") -> str:
    log.info("[media stub] transcribe %s", path)
    return ("Hallo, bei mir in der Wohnung ist die Heizung komplett kalt, seit heute Morgen. "
            "Am Kessel im Keller blinkt F.28.")


async def extract_invoice(path: str) -> dict:
    log.info("[media stub] extract_invoice %s", path)
    return {
        "invoice_number": "RE-2026-1187",
        "date": "2026-11-21",
        "net_eur": 210.00,
        "vat_eur": 39.90,
        "gross_eur": 249.90,
        "line_items": [
            {"desc": "Anfahrtspauschale", "qty": 1, "unit_price": 89.00},
            {"desc": "Arbeitszeit Techniker", "qty": 1.5, "unit_price": 72.00},
            {"desc": "Zündelektrode Vaillant", "qty": 1, "unit_price": 13.00},
        ],
        "labour_hours": 1.5,
    }
