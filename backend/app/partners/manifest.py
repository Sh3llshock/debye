"""Pydantic model of the connector manifest (docs/connector-spec.md). Lenient: extra keys kept."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class Rule(BaseModel):
    model_config = ConfigDict(extra="allow")
    field: str
    op: str
    value: Any = None


class ContextField(BaseModel):
    model_config = ConfigDict(extra="allow")
    key: str
    source: str
    pii: bool = False
    consent_required: bool = False


class Manifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    partner_id: str
    name: str
    category: str
    kind: str = "deliver"
    triggers: list[str] = []
    service_area: dict = {}
    capabilities: dict = {}
    eligibility: list[Rule] = []
    pricing: dict = {}
    required_context: list[ContextField] = []
    availability: dict = {}
    transport: dict = {}
    status_events: list[str] = []
    documents_returned: list[str] = []
    sla: dict = {}
    rating: float | None = None

    @property
    def brands_certified(self) -> list[str]:
        return list(self.capabilities.get("brands_certified", []))

    @property
    def consent_fields(self) -> list[str]:
        return [c.key for c in self.required_context if c.consent_required]
