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
    # numbers of data/demo/invoice_RE-2026-1187.pdf
    return {
        "invoice_number": "RE-2026-1187",
        "date": "2026-11-21",
        "net_eur": 199.50,
        "vat_eur": 37.91,
        "gross_eur": 237.41,
        "line_items": [
            {"desc": "Anfahrtspauschale (Rahmenvertrag)", "qty": 1, "unit_price": 89.00},
            {"desc": "Arbeitszeit Heizungstechniker, Std.", "qty": 1, "unit_price": 72.00},
            {"desc": "Zündelektrode Vaillant ecoTEC plus (0020107800)", "qty": 1, "unit_price": 38.50},
        ],
        "labour_hours": 1.0,
    }
