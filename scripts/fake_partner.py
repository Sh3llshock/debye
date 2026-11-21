"""Fake partner system "Heiztechnik API GmbH" (partners/heiztechnik-api.json, API transport).

A tiny standalone FastAPI app that plays a partner with its own system:
  POST /orders                  ← centrix sends a signed order (X-Centrix-Signature)
  → after ~3 s posts `accepted`, after ~3 s more `accepted` + 2 slots (from the order's slot_hints)
  POST /orders/{order_ref}/complete   manual: posts `completed` + the demo invoice PDF (base64, signed)
  GET  /                        tiny HTML page with the orders and a "Complete" button
  GET  /availability            static free windows (manifest availability_endpoint)

Run (from the repo root; reads PARTNER_API_SECRET from the env or .env):
  python scripts/fake_partner.py --port 8100 --debye http://localhost:8000
Options: --auto-complete N  also post completed+invoice N seconds after the tenant picked a slot
         (retries every 5 s while Debye answers 409 because no slot is booked yet).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data" / "demo" / "invoice_RE-2026-1187.pdf"
TZ = ZoneInfo("Europe/Berlin")

INVOICE = {  # the numbers printed on data/demo/invoice_RE-2026-1187.pdf (structured, no OCR needed)
    "invoice_number": "RE-2026-1187", "date": "2026-11-21",
    "net_eur": 199.50, "vat_eur": 37.91, "gross_eur": 237.41,
    "line_items": [
        {"desc": "Anfahrtspauschale (Rahmenvertrag)", "qty": 1, "unit_price": 89.00},
        {"desc": "Arbeitszeit Heizungstechniker, Std.", "qty": 1, "unit_price": 72.00},
        {"desc": "Zündelektrode Vaillant ecoTEC plus (0020107800)", "qty": 1, "unit_price": 38.50},
    ],
    "labour_hours": 1.0,
}


def env_secret(name: str) -> str:
    v = os.getenv(name)
    if v:
        return v
    for f in (ROOT / ".env", ROOT / "backend" / ".env"):
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                k, _, val = line.strip().partition("=")
                if k.strip() == name and val.strip():
                    return val.strip().strip('"').strip("'")
        except OSError:
            pass
    return ""


def sign(raw: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


class FakePartner:
    def __init__(self, partner_id: str, name: str, secret_env: str, debye: str, auto_complete: float = 0):
        self.partner_id, self.name, self.debye = partner_id, name, debye.rstrip("/")
        self.secret = env_secret(secret_env)
        self.secret_env = secret_env
        self.auto_complete = auto_complete
        self.orders: dict[str, dict] = {}
        self.log: list[str] = []

    def note(self, msg: str) -> None:
        line = f"{datetime.now(TZ):%H:%M:%S} {msg}"
        self.log = (self.log + [line])[-40:]
        print(f"[{self.partner_id}] {line}", flush=True)

    async def post_event(self, ref: str, status: str, data: dict | None = None,
                         documents: list | None = None) -> httpx.Response | None:
        body = {"order_ref": ref, "partner_id": self.partner_id, "status": status,
                "at": datetime.now(TZ).isoformat(timespec="seconds"),
                "data": data or {}, "documents": documents or []}
        raw = json.dumps(body, ensure_ascii=False).encode()
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(f"{self.debye}/api/partners/{self.partner_id}/events", content=raw,
                                 headers={"Content-Type": "application/json",
                                          "X-Centrix-Signature": sign(raw, self.secret)})
        except httpx.HTTPError as e:
            self.note(f"{ref}: {status} -> Debye unreachable ({type(e).__name__})")
            return None
        self.note(f"{ref}: {status} -> {r.status_code} {r.text[:120]}")
        if ref in self.orders and r.status_code < 300:
            self.orders[ref]["status"] = status
        return r


def build_app(p: FakePartner, script) -> FastAPI:
    app = FastAPI(title=f"{p.name} (fake partner system)")

    def check(raw: bytes, header: str | None) -> None:
        if not p.secret or not header or not hmac.compare_digest(sign(raw, p.secret), header):
            p.note("rejected an order with a bad signature")
            raise HTTPException(401, "bad signature")

    @app.post("/orders")
    async def orders(request: Request) -> dict:
        raw = await request.body()
        check(raw, request.headers.get("X-Centrix-Signature"))
        order = json.loads(raw)
        ref = order["order_ref"]
        pid = f"{p.partner_id[:2].upper()}-{uuid.uuid4().hex[:6].upper()}"
        p.orders[ref] = {"order": order, "partner_order_id": pid, "status": "received"}
        p.note(f"order {ref} received (context: {', '.join(order.get('context') or {}) or 'none'})")
        asyncio.get_running_loop().create_task(script(p, ref))
        return {"partner_order_id": pid, "status": "received"}

    @app.post("/orders/{ref}/complete")
    async def complete(ref: str):
        if ref not in p.orders:
            raise HTTPException(404, "unknown order")
        r = await complete_with_invoice(p, ref)
        return {"status": r.status_code if r is not None else None, "body": r.json() if r is not None and r.content else None}

    @app.post("/orders/{ref}/complete-form", include_in_schema=False)
    async def complete_form(ref: str):
        await complete(ref)
        return RedirectResponse("/", status_code=303)

    @app.get("/availability")
    def availability() -> dict:
        return {"mode": "static", "hours": "Mon–Fri 08:00–16:00"}

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        rows = "".join(
            f"<tr><td>{ref}</td><td>{o['partner_order_id']}</td><td>{o['status']}</td>"
            f"<td><form method=post action='/orders/{ref}/complete-form'><button>Complete + invoice</button>"
            f"</form></td></tr>" for ref, o in p.orders.items())
        logs = "<br>".join(reversed(p.log))
        return (f"<html><body style='font-family:sans-serif;padding:16px'><h2>{p.name}</h2>"
                f"<p>Fake partner system → {p.debye}</p><table border=1 cellpadding=6>"
                f"<tr><th>order_ref</th><th>our id</th><th>status</th><th></th></tr>{rows}</table>"
                f"<h3>Log</h3><p style='font-family:monospace'>{logs}</p></body></html>")

    return app


async def complete_with_invoice(p: FakePartner, ref: str):
    pdf = base64.b64encode(PDF.read_bytes()).decode() if PDF.exists() else None
    docs = [{"kind": "invoice", "filename": PDF.name, "mime": "application/pdf", "base64": pdf}] if pdf else []
    return await p.post_event(ref, "completed",
                              {"notes": "Zündelektrode getauscht, Anlage läuft wieder", "invoice": INVOICE},
                              docs)


async def heating_script(p: FakePartner, ref: str) -> None:
    """accepted → 2 slots → (optional) completed + invoice once the tenant booked a slot."""
    await asyncio.sleep(3)
    await p.post_event(ref, "accepted")
    await asyncio.sleep(3)
    hints = (p.orders[ref]["order"].get("slot_hints") or [])[:2]
    if hints:
        await p.post_event(ref, "accepted", {"slots": hints})
    if p.auto_complete > 0:
        await asyncio.sleep(p.auto_complete)
        for _ in range(120):  # up to 10 min until the tenant picked a slot
            r = await complete_with_invoice(p, ref)
            if r is not None and r.status_code != 409:
                return
            await asyncio.sleep(5)


def _utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def main(argv=None, *, partner_id="heiztechnik-api", name="Heiztechnik API GmbH",
         secret_env="PARTNER_API_SECRET", port=8100, script=heating_script) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=port)
    ap.add_argument("--debye", default=os.getenv("DEBYE_BASE", "http://localhost:8000"))
    ap.add_argument("--auto-complete", type=float, default=0, help="seconds; 0 = manual only")
    a = ap.parse_args(argv)
    _utf8_stdout()
    p = FakePartner(partner_id, name, secret_env, a.debye, a.auto_complete)
    if not p.secret:
        sys.exit(f"{secret_env} is not set (env or .env); Debye signs orders with it")
    p.note(f"listening on :{a.port}, events -> {p.debye}")
    uvicorn.run(build_app(p, script), host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
