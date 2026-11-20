#!/usr/bin/env python3
"""Runs the Debye golden path without phones.

Tenant side: posts realistic WhatsApp Cloud API webhook payloads to /webhooks/whatsapp
(text, button reply, list reply, audio/image). Media files are first uploaded to
/demo/sim-media, which returns a media id like "sim-ab12cd.ogg"; the WhatsApp adapter reads
those from storage/sim/<media_id> instead of the Graph API.

Partner side: drives the partner page API (accept, slots, complete with photo + PDF).

  python scripts/simulate.py                       # full golden path via webhooks
  python scripts/simulate.py --direct              # tenant steps via /demo/trigger (no router needed)
  python scripts/simulate.py --step report         # one step only (report|neighbour|consent|
                                                   #   accept|slots|pick|complete|fixed)
  python scripts/simulate.py --base http://localhost:8000 --reset

Only stdlib + httpx. Exit code 1 if a step fails.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import struct
import sys
import time
import zlib
from datetime import datetime, timedelta, timezone

import httpx

LENA = "490000000001"   # WhatsApp sends E.164 without "+"
JONAS = "490000000002"
PARTNER = "heizung-schmidt"
PHONE_NUMBER_ID = os.environ.get("WA_PHONE_NUMBER_ID", "123456789012345")
APP_SECRET = os.environ.get("WA_APP_SECRET", "")


# --------------------------------------------------------------------------- fixtures

def tiny_png(color=(200, 40, 40)) -> bytes:
    w = h = 8
    raw = b"".join(b"\x00" + bytes(color) * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def invoice_pdf() -> bytes:
    lines = ["Heizung Schmidt GmbH - Rechnung RE-2026-1187",
             "Musterstrasse 12, 52062 Aachen, Whg. 4b",
             "Anfahrtspauschale 1 x 89,00",
             "Arbeitszeit Techniker 1,5 h x 72,00 = 108,00",
             "Zuendelektrode Vaillant 1 x 13,00",
             "Netto 210,00  MwSt 19% 39,90  Brutto 249,90 EUR"]
    text = "BT /F1 11 Tf 50 780 Td 14 TL " + " ".join(f"({l}) Tj T*" for l in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(text)} >>\nstream\n{text}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer << /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


FAKE_OGG = b"OggS\x00\x02" + b"\x00" * 64  # not playable; the transcription stub ignores content


# --------------------------------------------------------------------------- WhatsApp payloads

_seq = 0


def _wamid() -> str:
    global _seq
    _seq += 1
    return f"wamid.SIM{int(time.time()*1000)}{_seq}"


def envelope(from_phone: str, name: str, message: dict) -> dict:
    return {"object": "whatsapp_business_account", "entry": [{
        "id": "WABA_SIM", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "15550000000", "phone_number_id": PHONE_NUMBER_ID},
            "contacts": [{"profile": {"name": name}, "wa_id": from_phone}],
            "messages": [{"from": from_phone, "id": _wamid(), "timestamp": str(int(time.time())),
                          **message}]}}]}]}


def text_msg(body: str) -> dict:
    return {"type": "text", "text": {"body": body}}


def button_reply(id_: str, title: str) -> dict:
    return {"type": "interactive", "interactive": {"type": "button_reply",
                                                   "button_reply": {"id": id_, "title": title}}}


def list_reply(id_: str, title: str) -> dict:
    return {"type": "interactive", "interactive": {"type": "list_reply",
                                                   "list_reply": {"id": id_, "title": title}}}


def audio_msg(media_id: str) -> dict:
    return {"type": "audio", "audio": {"id": media_id, "mime_type": "audio/ogg; codecs=opus",
                                       "sha256": "sim", "voice": True}}


def image_msg(media_id: str, caption: str = "") -> dict:
    return {"type": "image", "image": {"id": media_id, "mime_type": "image/jpeg", "sha256": "sim",
                                       "caption": caption}}


# --------------------------------------------------------------------------- runner

class Sim:
    def __init__(self, base: str, direct: bool, wait: float):
        self.c = httpx.Client(base_url=base, timeout=60)
        self.direct = direct
        self.wait = wait

    def log(self, who: str, what: str) -> None:
        print(f"  [{who:>8}] {what}")

    def _check(self, r: httpx.Response) -> dict:
        if r.status_code >= 400:
            raise SystemExit(f"FAILED {r.request.method} {r.request.url}: {r.status_code} {r.text}")
        try:
            return r.json()
        except ValueError:
            return {}

    def upload(self, filename: str, data: bytes, mime: str) -> str:
        r = self._check(self.c.post("/demo/sim-media", files={"file": (filename, data, mime)}))
        return r["media_id"]

    def webhook(self, from_phone: str, name: str, message: dict) -> None:
        body = json.dumps(envelope(from_phone, name, message)).encode()
        headers = {"Content-Type": "application/json"}
        if APP_SECRET:
            sig = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
            headers["X-Hub-Signature-256"] = f"sha256={sig}"
        r = self.c.post("/webhooks/whatsapp", content=body, headers=headers)
        if r.status_code in (404, 405):
            raise SystemExit("/webhooks/whatsapp not found – the agent router isn't merged yet. "
                             "Use --direct.")
        self._check(r)
        time.sleep(self.wait)  # the router processes in a background task

    def trigger(self, name: str, body: dict | None = None) -> dict:
        return self._check(self.c.post(f"/demo/trigger/{name}", json=body or {}))

    def latest_case(self) -> dict:
        cases = self._check(self.c.get("/api/staff/cases"))
        if not cases:
            raise SystemExit("no case yet")
        return cases[0]

    def case(self, cid: str) -> dict:
        return self._check(self.c.get(f"/api/staff/cases/{cid}"))

    # ---- steps
    def report(self) -> None:
        self.log("Lena", "🎤 voice note + 📷 photo of the boiler (F.28)")
        audio = self.upload("voice.ogg", FAKE_OGG, "audio/ogg")
        photo = self.upload("boiler.png", tiny_png(), "image/png")
        if self.direct:
            r = self.trigger("tenant_report", {"media_ids": [audio, photo]})
            self.log("debye", f"opened {r['case_id']}, ranked: "
                     + ", ".join(f"{p['name']} {p['score']}" for p in r.get("ranking", [])))
            return
        self.webhook(LENA, "Lena Hoffmann", audio_msg(audio))
        self.webhook(LENA, "Lena Hoffmann", image_msg(photo, "Das zeigt der Kessel"))
        try:
            cid = self.latest_case()["case_id"]
            self.log("Lena", "taps 'Überall kalt'")
            self.webhook(LENA, "Lena Hoffmann", button_reply(f"cold_all:{cid}", "Überall kalt"))
        except SystemExit:
            self.log("sim", "no case yet after voice+photo (agent may still be asking); continuing")

    def neighbour(self) -> None:
        self.log("Jonas", "Bei uns im 1. Stock ist die Heizung auch kalt.")
        if self.direct:
            r = self.trigger("neighbour_report")
            self.log("debye", f"linked to {r.get('duplicate_of') or r.get('case_id')}")
            return
        self.webhook(JONAS, "Jonas Weber", text_msg("Bei uns im 1. Stock ist die Heizung auch kalt."))

    def consent(self) -> None:
        cid = self.latest_case()["case_id"]
        self.log("Lena", f"taps consent for {cid}")
        if self.direct:
            r = self.trigger("consent", {"case_id": cid})
            self.log("debye", f"dispatch: {r.get('dispatched') or r.get('blocked')}")
            return
        self.webhook(LENA, "Lena Hoffmann", button_reply(f"consent_yes:{cid}", "Ja, teilen"))

    def accept(self) -> None:
        cid = self.latest_case()["case_id"]
        self.log("partner", f"accepts {cid}")
        self._check(self.c.post(f"/api/partner/{PARTNER}/jobs/{cid}/accept"))

    def slots(self) -> None:
        cid = self.latest_case()["case_id"]
        tz = timezone(timedelta(hours=1))
        t = (datetime.now(tz) + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
        slots = [{"start": t.isoformat(), "end": (t + timedelta(hours=2)).isoformat()},
                 {"start": (t + timedelta(days=1, hours=6)).isoformat(),
                  "end": (t + timedelta(days=1, hours=8)).isoformat()}]
        job = self._check(self.c.post(f"/api/partner/{PARTNER}/jobs/{cid}/slots", json={"slots": slots}))
        self.log("partner", "proposes " + " / ".join(s["label"] for s in job["proposed_slots"]))

    def pick(self, index: int = 1) -> None:
        cid = self.latest_case()["case_id"]
        self.log("Lena", f"picks slot {index}")
        if self.direct:
            self.trigger("pick_slot", {"case_id": cid, "index": index})
            return
        self.webhook(LENA, "Lena Hoffmann", list_reply(f"slot_{index}:{cid}", f"Slot {index}"))

    def complete(self) -> None:
        cid = self.latest_case()["case_id"]
        self.log("partner", "marks done with photo + invoice PDF")
        job = self._check(self.c.post(
            f"/api/partner/{PARTNER}/jobs/{cid}/complete",
            data={"notes": "Zündelektrode getauscht, Kessel läuft wieder"},
            files={"photo": ("after.png", tiny_png((40, 160, 60)), "image/png"),
                   "invoice": ("RE-2026-1187.pdf", invoice_pdf(), "application/pdf")}))
        self.log("debye", f"invoice price check: {(job.get('price_check') or {}).get('result')}")

    def fixed(self) -> None:
        cid = self.latest_case()["case_id"]
        self.log("Lena", "taps 'Ja, warm!'")
        if self.direct:
            self.trigger("fixed", {"case_id": cid, "fixed": True})
            return
        self.webhook(LENA, "Lena Hoffmann", button_reply(f"fixed_yes:{cid}", "Ja, warm!"))

    def summary(self) -> bool:
        c = self.case(self.latest_case()["case_id"])
        print(f"\n{c['case_id']}: status={c['status']} partner={(c.get('partner') or {}).get('name')}")
        for e in c["events"]:
            print(f"  {e['ts'][11:19]} {e['actor']:>7}  {e['kind']:<22} {e['summary']}")
        unit = self._check(self.c.get(f"/api/staff/units/{c['unit_id']}"))
        print(f"  documents on {c['unit_id']}: " + ", ".join(f"{d['kind']}:{d['filename']}" for d in unit["documents"]))
        return c["status"] == "closed"


STEPS = ["report", "neighbour", "consent", "accept", "slots", "pick", "complete", "fixed"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=os.environ.get("DEBYE_BASE", "http://localhost:8000"))
    ap.add_argument("--direct", action="store_true",
                    help="tenant steps via /demo/trigger instead of webhooks (before the router lands)")
    ap.add_argument("--reset", action="store_true", help="POST /demo/reset first")
    ap.add_argument("--step", choices=STEPS, help="run one step only")
    ap.add_argument("--wait", type=float, default=1.5, help="seconds to wait after each webhook")
    ap.add_argument("--pause", type=float, default=0.0, help="seconds between steps (for live demos)")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    sim = Sim(args.base, args.direct, 0 if args.direct else args.wait)
    if args.reset:
        sim._check(sim.c.post("/demo/reset"))
        print("reset done")
    steps = [args.step] if args.step else STEPS
    for name in steps:
        print(f"→ {name}")
        getattr(sim, name)()
        time.sleep(args.pause)
    if args.step:
        return 0
    ok = sim.summary()
    print("\nGOLDEN PATH OK" if ok else "\nGOLDEN PATH NOT CLOSED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
