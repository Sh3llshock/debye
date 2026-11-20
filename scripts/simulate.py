#!/usr/bin/env python3
"""Runs the Debye golden path without phones.

Tenant side: posts realistic WhatsApp Cloud API webhook payloads to /webhooks/whatsapp
(text, button reply, list reply, audio/image), using the files in data/demo/. Media are
uploaded to /demo/sim-media, which returns ids like "sim-ab12cd.jpg" that the adapter reads
from storage (interfaces §3.3b). With --local-media the ids are "local:<path>" instead
(same machine only, no upload).
After each webhook the simulator reads GET /webhooks/whatsapp/_outbox, prints Debye's
replies and fails if there is none. Button/list ids for the next tap are taken from Debye's
latest interactive message when possible.

Partner side: drives the partner page API (accept, slots, complete with photo + invoice PDF).

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
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

LENA = "490000000001"   # WhatsApp sends E.164 without "+"
JONAS = "490000000002"
PARTNER = "heizung-schmidt"
PHONE_NUMBER_ID = os.environ.get("WA_PHONE_NUMBER_ID", "123456789012345")
APP_SECRET = os.environ.get("WA_APP_SECRET", "")

REPO = Path(__file__).resolve().parents[1]
DEMO = REPO / "data" / "demo"
BOILER_PHOTO = DEMO / "boiler_display_F28.jpg"
DONE_PHOTO = DEMO / "repair_done.jpg"
INVOICE_PDF = DEMO / "invoice_RE-2026-1187.pdf"
FAKE_OGG = b"OggS" + bytes(68)  # not playable; the transcription stub ignores it


def voice_note_path() -> Path:
    p = Path(tempfile.gettempdir()) / "debye_sim_voice.ogg"
    if not p.exists():
        p.write_bytes(FAKE_OGG)
    return p


# --------------------------------------------------------------------------- WhatsApp payloads

_seq = 0


def _wamid() -> str:
    global _seq
    _seq += 1
    return f"wamid.SIM{int(time.time() * 1000)}{_seq}"


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


# --------------------------------------------------------------------------- outbox parsing

def _outbox_items(data) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("messages", "outbox", "items"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def _payload(item: dict) -> dict:
    """An outbox item may be the Graph API body itself or wrap it (payload/body/message)."""
    for key in ("payload", "body", "message", "request"):
        if isinstance(item.get(key), dict):
            return {**item[key], **{k: v for k, v in item.items() if k == "to"}}
    return item


def _to(item: dict) -> str:
    return str(_payload(item).get("to", "")).lstrip("+")


def _describe(item: dict) -> str:
    p = _payload(item)
    t = p.get("type")
    if t == "text":
        return (p.get("text") or {}).get("body", "")
    if t == "interactive":
        i = p.get("interactive") or {}
        body = (i.get("body") or {}).get("text", "")
        act = i.get("action") or {}
        if i.get("type") == "button":
            opts = [b.get("reply", {}).get("title") for b in act.get("buttons", [])]
        else:
            opts = [r.get("title") for sec in act.get("sections", []) for r in sec.get("rows", [])]
        return f"{body}  [{' | '.join(o or '' for o in opts)}]"
    if t:
        return f"<{t}>"
    return item.get("text") or json.dumps(item, ensure_ascii=False)[:120]


def _option_ids(item: dict) -> list[str]:
    i = _payload(item).get("interactive") or {}
    act = i.get("action") or {}
    ids = [b.get("reply", {}).get("id") for b in act.get("buttons", [])]
    ids += [r.get("id") for sec in act.get("sections", []) for r in sec.get("rows", [])]
    return [x for x in ids if x]


# --------------------------------------------------------------------------- runner

class Sim:
    def __init__(self, base: str, direct: bool, wait: float, upload: bool = True):
        self.c = httpx.Client(base_url=base, timeout=60)
        self.direct = direct
        self.wait = wait
        self.upload_media = upload
        self.outbox_seen = 0
        self.outbox_all: list[dict] = []

    def log(self, who: str, what: str) -> None:
        print(f"  [{who:>8}] {what}")

    def _check(self, r: httpx.Response) -> dict:
        if r.status_code >= 400:
            raise SystemExit(f"FAILED {r.request.method} {r.request.url}: {r.status_code} {r.text}")
        try:
            return r.json()
        except ValueError:
            return {}

    def media_id(self, path: Path, mime: str) -> str:
        if not self.upload_media:
            return f"local:{path}"
        r = self._check(self.c.post("/demo/sim-media", files={"file": (path.name, path.read_bytes(), mime)}))
        return r["media_id"]

    # ---- outbox
    def read_outbox(self) -> list[dict]:
        r = self.c.get("/webhooks/whatsapp/_outbox")
        if r.status_code >= 400:
            return []
        items = _outbox_items(r.json())
        if len(items) < self.outbox_seen:  # outbox was cleared (reset)
            self.outbox_seen = 0
        new = items[self.outbox_seen:]
        self.outbox_seen = len(items)
        self.outbox_all.extend(new)
        return new

    def option_id(self, phone: str, prefix: str, fallback: str) -> str:
        """Find e.g. 'consent_yes:...' in the latest interactive message sent to phone."""
        for item in reversed(self.outbox_all):
            if _to(item) != phone:
                continue
            for oid in _option_ids(item):
                if oid.startswith(prefix):
                    return oid
        return fallback

    def webhook(self, from_phone: str, name: str, message: dict, expect_reply: bool = True) -> None:
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
        # the router processes in a background task; wait for Debye's reply
        deadline = time.time() + self.wait
        replies: list[dict] = []
        first_reply_at = None
        while time.time() < deadline:
            time.sleep(0.5)
            replies += [i for i in self.read_outbox() if _to(i) == from_phone]
            if replies and first_reply_at is None:
                first_reply_at = time.time()
            if first_reply_at and time.time() - first_reply_at > 1.5:  # collect follow-ups
                break
        for item in replies:
            self.log("debye", f"→ {name.split()[0]}: {_describe(item)}")
        if expect_reply and not replies:
            raise SystemExit(f"FAILED: Debye sent no WhatsApp reply to {name} within {self.wait:.0f}s "
                             "(check /webhooks/whatsapp/_outbox and the server log)")

    def trigger(self, name: str, body: dict | None = None) -> dict:
        return self._check(self.c.post(f"/demo/trigger/{name}", json=body or {}))

    def latest_case(self) -> dict:
        cases = self._check(self.c.get("/api/staff/cases"))
        if not cases:
            raise SystemExit("FAILED: no case yet")
        return cases[0]

    def case(self, cid: str) -> dict:
        return self._check(self.c.get(f"/api/staff/cases/{cid}"))

    # ---- steps
    def report(self) -> None:
        self.log("Lena", "🎤 voice note + 📷 photo of the boiler (F.28)")
        audio = self.media_id(voice_note_path(), "audio/ogg")
        photo = self.media_id(BOILER_PHOTO, "image/jpeg")
        if self.direct:
            r = self.trigger("tenant_report", {"media_ids": [audio, photo]})
            self.log("debye", f"opened {r['case_id']}, ranked: "
                     + ", ".join(f"{p['name']} {p['score']}" for p in r.get("ranking", [])))
            return
        self.webhook(LENA, "Lena Hoffmann", audio_msg(audio))
        self.webhook(LENA, "Lena Hoffmann", image_msg(photo, "Das zeigt der Kessel"))
        cases = self._check(self.c.get("/api/staff/cases"))
        cid = cases[0]["case_id"] if cases else ""
        oid = self.option_id(LENA, "cold_all", f"cold_all:{cid}")
        self.log("Lena", "taps 'Überall kalt'")
        self.webhook(LENA, "Lena Hoffmann", button_reply(oid, "Überall kalt"))

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
        oid = self.option_id(LENA, "consent_yes", f"consent_yes:{cid}")
        self.webhook(LENA, "Lena Hoffmann", button_reply(oid, "Ja, teilen"))

    def accept(self) -> None:
        cid = self.latest_case()["case_id"]
        self.log("partner", f"accepts {cid}")
        self._check(self.c.post(f"/api/partner/{PARTNER}/jobs/{cid}/accept"))
        if not self.direct:
            for item in self.read_outbox():
                self.log("debye", f"→ {_to(item)}: {_describe(item)}")

    def slots(self) -> None:
        cid = self.latest_case()["case_id"]
        tz = timezone(timedelta(hours=1))
        t = (datetime.now(tz) + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
        slots = [{"start": t.isoformat(), "end": (t + timedelta(hours=2)).isoformat()},
                 {"start": (t + timedelta(days=1, hours=6)).isoformat(),
                  "end": (t + timedelta(days=1, hours=8)).isoformat()}]
        job = self._check(self.c.post(f"/api/partner/{PARTNER}/jobs/{cid}/slots", json={"slots": slots}))
        self.log("partner", "proposes " + " / ".join(s["label"] for s in job["proposed_slots"]))
        if not self.direct:
            time.sleep(1)
            for item in self.read_outbox():
                self.log("debye", f"→ {_to(item)}: {_describe(item)}")

    def pick(self, index: int = 1) -> None:
        """index is 1-based, like the list ids slot_1, slot_2 (interfaces §3.3)."""
        cid = self.latest_case()["case_id"]
        self.log("Lena", f"picks slot #{index}")
        if self.direct:
            self.trigger("pick_slot", {"case_id": cid, "index": index})
            return
        # take the row id from Debye's list message; fall back to slot_<index>:<case_id>
        rows = []
        for item in reversed(self.outbox_all):
            if _to(item) == LENA:
                rows = [o for o in _option_ids(item) if o.startswith("slot_") and not o.startswith("slot_none")]
                if rows:
                    break
        oid = rows[index - 1] if 0 < index <= len(rows) else f"slot_{index}:{cid}"
        self.webhook(LENA, "Lena Hoffmann", list_reply(oid, f"Slot {index}"))

    def complete(self) -> None:
        cid = self.latest_case()["case_id"]
        self.log("partner", "marks done with photo + invoice PDF")
        job = self._check(self.c.post(
            f"/api/partner/{PARTNER}/jobs/{cid}/complete",
            data={"notes": "Zündelektrode getauscht, Kessel läuft wieder"},
            files={"photo": (DONE_PHOTO.name, DONE_PHOTO.read_bytes(), "image/jpeg"),
                   "invoice": (INVOICE_PDF.name, INVOICE_PDF.read_bytes(), "application/pdf")}))
        pc = job.get("price_check") or {}
        self.log("debye", f"invoice price check: {pc.get('result')} {pc.get('flags') or ''}")
        if not self.direct:
            time.sleep(1)
            for item in self.read_outbox():
                self.log("debye", f"→ {_to(item)}: {_describe(item)}")

    def fixed(self) -> None:
        cid = self.latest_case()["case_id"]
        self.log("Lena", "taps 'Ja, warm!'")
        if self.direct:
            self.trigger("fixed", {"case_id": cid, "fixed": True})
            return
        oid = self.option_id(LENA, "fixed_yes", f"fixed_yes:{cid}")
        self.webhook(LENA, "Lena Hoffmann", button_reply(oid, "Ja, warm!"))

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
    ap.add_argument("--local-media", action="store_true",
                    help="send local:<path> media ids instead of uploading to /demo/sim-media")
    ap.add_argument("--reset", action="store_true", help="POST /demo/reset first")
    ap.add_argument("--step", choices=STEPS, help="run one step only")
    ap.add_argument("--wait", type=float, default=20.0, help="max seconds to wait for Debye's reply")
    ap.add_argument("--pause", type=float, default=0.0, help="seconds between steps (for live demos)")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    sim = Sim(args.base, args.direct, args.wait, upload=not args.local_media)
    if args.reset:
        sim._check(sim.c.post("/demo/reset"))
        print("reset done")
    sim.read_outbox()  # skip what was already there
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
