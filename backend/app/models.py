"""Tables (technical-plan §3). IDs are short strings, timestamps tz-aware ISO strings.

JSON columns: never mutate in place; reassign a new dict/list so SQLAlchemy sees the change.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _json(default_factory=dict):
    return Field(default_factory=default_factory, sa_column=Column(JSON))


class Property(SQLModel, table=True):
    id: str = Field(primary_key=True)
    address: str
    postcode: str
    city: str
    building_year: Optional[int] = None
    heating_type: Optional[str] = None
    heating_central: bool = False
    fibre_available: bool = False
    energy_class: Optional[str] = None
    energy_valid_until: Optional[str] = None


class Unit(SQLModel, table=True):
    id: str = Field(primary_key=True)
    property_id: str = Field(foreign_key="property.id")
    floor: Optional[int] = None
    size_sqm: Optional[float] = None
    rooms: Optional[int] = None
    meters: list = _json(list)


class Asset(SQLModel, table=True):
    id: str = Field(primary_key=True)
    property_id: str = Field(foreign_key="property.id")
    unit_id: Optional[str] = None  # None = central asset
    type: str
    make: Optional[str] = None
    model: Optional[str] = None
    installed: Optional[str] = None
    last_service: Optional[str] = None
    known_error_codes: dict = _json(dict)


class Contact(SQLModel, table=True):
    id: str = Field(primary_key=True)
    role: str  # tenant | owner | partner_staff | pm
    name: str
    phone_e164: Optional[str] = Field(default=None, index=True)
    email: Optional[str] = None
    language: str = "de"
    unit_id: Optional[str] = None
    partner_id: Optional[str] = None
    move_in: Optional[str] = None
    whatsapp_opt_in: bool = False


class Contract(SQLModel, table=True):
    id: str = Field(primary_key=True)
    type: str  # lease | framework | service
    unit_id: Optional[str] = None
    contact_id: Optional[str] = None
    partner_id: Optional[str] = None
    data: dict = _json(dict)


class Partner(SQLModel, table=True):
    id: str = Field(primary_key=True)
    manifest: dict = _json(dict)
    active: bool = True


class Technician(SQLModel, table=True):
    id: str = Field(primary_key=True)
    partner_id: str = Field(index=True)
    name: str
    phone_e164: Optional[str] = None
    skills: list = _json(list)
    # absolute [{start, end, reason}] – seeded busy windows + confirmed jobs
    busy: list = _json(list)


class Notice(SQLModel, table=True):
    """Building notice from centrix (e.g. planned maintenance: hot water off 9–13)."""
    id: str = Field(primary_key=True)
    property_id: str = Field(index=True)
    title: str
    body: str = ""
    kind: str = "maintenance"
    active: bool = False
    starts: Optional[str] = None
    ends: Optional[str] = None


class Case(SQLModel, table=True):
    __tablename__ = "cases"

    id: str = Field(primary_key=True)
    type: str
    title: str = ""
    status: str = "new"
    priority: str = "normal"
    summary: str = ""
    symptoms: str = ""
    error_code: Optional[str] = None
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    asset_id: Optional[str] = None
    reporter_contact_id: Optional[str] = None
    partner_id: Optional[str] = None
    cost_bearer: str = "landlord"
    estimated_cost_eur: Optional[float] = None
    slot_start: Optional[str] = None
    slot_end: Optional[str] = None
    created_at: str
    updated_at: str
    closed_at: Optional[str] = None
    # free-form: prefilled_fields, tenant_inputs, ranking, proposed_slots, approval,
    # pending_partner_id, declined_by, completion, price_check, result
    data: dict = _json(dict)


class CaseContact(SQLModel, table=True):
    case_id: str = Field(primary_key=True)
    contact_id: str = Field(primary_key=True)
    relation: str = "reporter"  # reporter | affected


class CaseEvent(SQLModel, table=True):
    id: str = Field(primary_key=True)
    case_id: Optional[str] = Field(default=None, index=True)
    ts: str
    actor: str  # debye | tenant | partner | staff | system
    kind: str
    summary: str
    data: dict = _json(dict)


class Message(SQLModel, table=True):
    id: str = Field(primary_key=True)
    case_id: Optional[str] = Field(default=None, index=True)
    contact_id: Optional[str] = None
    channel: str = "whatsapp"
    direction: str  # in | out
    wa_message_id: Optional[str] = Field(default=None, index=True)
    text: Optional[str] = None
    media_ids: list = _json(list)
    ts: str


class Document(SQLModel, table=True):
    id: str = Field(primary_key=True)
    case_id: Optional[str] = Field(default=None, index=True)
    unit_id: Optional[str] = Field(default=None, index=True)
    kind: str  # photo | invoice | report | contract | audio
    filename: str
    mime: str
    path: str
    extracted: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: Optional[str] = None


class Consent(SQLModel, table=True):
    id: str = Field(primary_key=True)
    contact_id: str
    partner_id: str
    case_id: Optional[str] = None
    data_shared: list = _json(list)
    purpose: str = ""
    channel: str = "whatsapp"
    given_at: str
    revoked_at: Optional[str] = None


class Conversation(SQLModel, table=True):
    contact_id: str = Field(primary_key=True)
    case_id: str = Field(default="", primary_key=True)  # "" = no case yet
    claude_messages: list = _json(list)
    updated_at: Optional[str] = None


def to_dict(obj: Any) -> dict:
    return obj.model_dump() if obj is not None else None
