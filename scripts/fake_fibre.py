"""Fake partner system "Example Fibre GmbH" (partners/example-fibre.json, kind sell, API transport).

Same core as scripts/fake_partner.py, sell lifecycle instead:
  POST /orders  ← signed order (offer_id, consented context: name, address, move_in_date)
  → ~3 s `accepted` → ~3 s `signed` (+ order confirmation PDF) → ~3 s `active` {start, product, monthly_price_eur}

Run (from the repo root; reads FIBRE_SECRET from the env or .env):
  python scripts/fake_fibre.py --port 8101 --debye http://localhost:8000
"""
from __future__ import annotations

import asyncio
import base64

from fake_partner import FakePartner, main as partner_main

OFFERS = {"fibre-250": ("Fibre 250", 29.99), "fibre-500": ("Fibre 500", 34.99)}


def confirmation_pdf(text: str) -> bytes:
    """A one-page PDF with one line of text (no dependencies)."""
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1", "replace")
    stream = b"BT /F1 14 Tf 72 760 Td (" + safe + b") Tj ET"
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets)
    out += f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


async def sell_script(p: FakePartner, ref: str) -> None:
    order = p.orders[ref]["order"]
    title, price = OFFERS.get(order.get("offer_id"), (order.get("offer_id") or "Fibre", None))
    ctx = order.get("context") or {}
    start = ctx.get("move_in_date") or order.get("sent_at", "")[:10]
    await asyncio.sleep(3)
    await p.post_event(ref, "accepted")
    await asyncio.sleep(3)
    pdf = confirmation_pdf(f"{p.name}: {title} for {ctx.get('name', 'the tenant')}, start {start}")
    await p.post_event(ref, "signed", {"product": title},
                       [{"kind": "contract", "filename": f"contract_{p.orders[ref]['partner_order_id']}.pdf",
                         "mime": "application/pdf", "base64": base64.b64encode(pdf).decode()}])
    await asyncio.sleep(3)
    await p.post_event(ref, "active", {"start": start, "product": title, "monthly_price_eur": price})


if __name__ == "__main__":
    partner_main(partner_id="example-fibre", name="Example Fibre GmbH", secret_env="FIBRE_SECRET",
                 port=8101, script=sell_script)
