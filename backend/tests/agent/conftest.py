"""Fakes for agent-whatsapp tests: in-memory services, stubbed Claude, fake-send WhatsApp."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ["WA_TOKEN"] = ""  # fake-send
os.environ["WA_APP_SECRET"] = ""
os.environ["WA_VERIFY_TOKEN"] = "verify-me"
os.environ["DEMO_MODE"] = "1"
os.environ["ROUTER_DEBOUNCE"] = "0"
LIVE_ANTHROPIC_KEY = os.environ.pop("ANTHROPIC_API_KEY", None)  # used only by test_live_claude
os.environ.pop("OPENAI_API_KEY", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/


class RuleViolation(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class FakeServices:
    def __init__(self):
        self.contacts = {
            "c_202": SimpleNamespace(id="c_202", role="tenant", name="Lena Hoffmann", phone_e164="+490000000001",
                                     unit_id="unit_4b", language="de"),
            "c_203": SimpleNamespace(id="c_203", role="tenant", name="Jonas Weber", phone_e164="+490000000002",
                                     unit_id="unit_2a", language="de"),
            "c_301": SimpleNamespace(id="c_301", role="partner_staff", name="Tom Schmidt",
                                     phone_e164="+490000000003", unit_id=None, language="de"),
        }
        self.cases: dict[str, dict] = {}
        self.case_contacts: dict[str, list[tuple[str, str]]] = {}
        self.calls: list[tuple] = []
        self.messages: list[dict] = []
        self.approval_required = False

    # §3.3
    def get_contact_by_phone(self, phone):
        return next((c for c in self.contacts.values() if c.phone_e164 == phone), None)

    def get_contact(self, cid):
        return self.contacts.get(cid)

    def get_unit_context(self, unit_id):
        return {
            "property": {"id": "prop_12", "address": "Musterstraße 12, 52062 Aachen", "heating_central": True},
            "unit": {"id": unit_id},
            "assets": [{"id": "asset_boiler_1", "type": "gas_boiler", "make": "Vaillant",
                        "known_error_codes": {"F.28": "Ignition failed"}}],
            "open_cases": [c for c in self.cases.values() if c["status"] != "closed"],
        }

    def find_open_case_for_asset(self, asset_id):
        return next((SimpleNamespace(**c) for c in self.cases.values()
                     if c["asset_id"] == asset_id and c["status"] != "closed"), None)

    def open_case(self, reporter_contact_id, type, priority, summary, symptoms, error_code, asset_id):
        cid = f"case_{len(self.cases) + 1:04d}"
        self.cases[cid] = dict(id=cid, status="new", asset_id=asset_id, summary=summary, error_code=error_code,
                               priority=priority, reporter_contact_id=reporter_contact_id)
        self.case_contacts[cid] = [(reporter_contact_id, "reporter")]
        self.calls.append(("open_case", cid, summary, error_code))
        return SimpleNamespace(**self.cases[cid])

    def link_contact_to_case(self, case_id, contact_id, relation):
        self.case_contacts[case_id].append((contact_id, relation))
        self.calls.append(("link", case_id, contact_id, relation))

    def attach_document(self, case_id, kind, filename, mime, path, extracted=None):
        self.calls.append(("attach", case_id, kind, filename))
        return SimpleNamespace(id="doc_1")

    def record_consent(self, contact_id, partner_id, case_id, fields, purpose, channel):
        self.calls.append(("consent", contact_id, partner_id, case_id, tuple(fields), channel))

    def rank_partners(self, case_id):
        return [{"partner_id": "heizung-schmidt", "name": "Heizung Schmidt", "score": 0.86, "reasons": []}]

    def dispatch_job(self, case_id, partner_id):
        if self.approval_required:
            raise RuleViolation("approval_required")
        self.cases[case_id]["status"] = "dispatched"
        self.calls.append(("dispatch", case_id, partner_id))
        return {}

    def confirm_slot(self, case_id, slot_index):
        self.calls.append(("confirm_slot", case_id, slot_index))
        return {}

    def tenant_confirms_fixed(self, case_id, fixed):
        if fixed:
            self.cases[case_id]["status"] = "closed"
        self.calls.append(("fixed", case_id, fixed))
        return {}

    # asked-for extras
    def add_tenant_input(self, case_id, label):
        self.calls.append(("input", case_id, label))

    def message_seen(self, wamid):
        return False

    def get_case_contacts(self, case_id):
        out = []
        for cid, rel in self.case_contacts.get(case_id, []):
            c = self.contacts[cid]
            out.append(SimpleNamespace(**vars(c), relation=rel))
        return out

    def log_message(self, **kw):
        self.messages.append(kw)


from agent_stubs import StubClaude  # noqa: E402


@pytest.fixture
def svc(monkeypatch):
    from app.agent import _backend as be
    from app.agent import state
    from app.channels import whatsapp

    fake = FakeServices()
    monkeypatch.setattr(be, "_services", lambda: fake)
    events = []
    monkeypatch.setattr(be, "record_event", lambda *a, **k: events.append(a))

    async def _pub(*a, **k):
        events.append(a)

    monkeypatch.setattr(be, "publish", _pub)
    fake.events = events
    state.reset_all()
    whatsapp.clear_outbox()
    whatsapp._seen.clear()
    from app import router

    monkeypatch.setattr(router, "DEBOUNCE_SECONDS", 0)
    return fake


@pytest.fixture
def claude(monkeypatch):
    from app.agent import loop

    def _set(script):
        stub = StubClaude(script)
        loop.set_client(stub)
        return stub

    yield _set
    loop.set_client(None)


@pytest.fixture
def client(svc):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.channels.webchat import router as webchat_router
    from app.channels.whatsapp import router as whatsapp_router

    app = FastAPI()
    app.include_router(whatsapp_router)
    app.include_router(webchat_router)
    return TestClient(app)
