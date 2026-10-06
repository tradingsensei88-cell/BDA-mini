"""Schemas for investigations endpoints (``/api/investigations``)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PaginatedResponse


class InvestigationResponse(BaseModel):
    """An analyst case file grouping related alerts."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "6f0e2a44-93c1-4d0a-b7de-4a1f02c7a1e8",
                "title": "Investigation: DoS burst from HOST-014",
                "status": "open",
                "priority": "high",
                "severity": "high",
                "analyst": "analyst-7",
                "summary": "Sustained neptune flood against HOST-042 saturated the edge.",
                "attack_vector": "network",
                "mitre_techniques": ["T1498"],
                "tags": ["ddos", "edge"],
                "related_alert_ids": ["b2a7c4d1-90f2-4f7e-a3de-1f02c7a1e8a4"],
                "opened_at": "2026-10-06T14:10:00Z",
                "created_at": "2026-10-06T14:10:00Z",
                "updated_at": "2026-10-06T14:10:00Z",
            }
        }
    )

    id: str = Field(description="Investigation id (UUID).")
    title: str = Field(description="Case title.")
    status: str = Field(description="open / in_progress / on_hold / closed.")
    priority: str = Field(description="critical / high / medium / low.")
    severity: str = Field(description="critical / high / medium / low / info.")
    analyst: str | None = Field(default=None, description="Assigned analyst.")
    summary: str | None = Field(default=None, description="Case summary.")
    findings: str | None = Field(default=None, description="Running findings notes.")
    attack_vector: str | None = Field(default=None, description="Attack vector classification.")
    mitre_techniques: list[str] = Field(
        default_factory=list, description="MITRE ATT&CK technique ids."
    )
    tags: list[str] = Field(default_factory=list, description="Free-form labels.")
    related_alert_ids: list[str] = Field(
        default_factory=list, description="Alerts grouped into this case."
    )
    opened_at: datetime | None = Field(default=None, description="Case open time (UTC).")
    closed_at: datetime | None = Field(default=None, description="Case close time (UTC).")
    created_at: datetime = Field(description="Record creation time (UTC).")
    updated_at: datetime | None = Field(default=None, description="Last update time (UTC).")


class InvestigationList(PaginatedResponse[InvestigationResponse]):
    """Paginated collection of investigations."""


class InvestigationCreate(BaseModel):
    """Payload for ``POST /api/investigations`` (created from an alert)."""

    alert_id: str = Field(
        description="Alert the investigation is opened from.",
        examples=["b2a7c4d1-90f2-4f7e-a3de-1f02c7a1e8a4"],
    )
    title: str | None = Field(
        default=None,
        max_length=255,
        description="Optional title override; defaults to the alert title.",
    )
    analyst: str | None = Field(
        default=None, max_length=128, description="Analyst taking the case.", examples=["analyst-7"]
    )
    priority: str | None = Field(
        default=None, description="critical / high / medium / low; defaults from severity."
    )
    summary: str | None = Field(default=None, max_length=2000, description="Case summary.")
    tags: list[str] = Field(default_factory=list, max_length=20, description="Case labels.")


class InvestigationDetail(InvestigationResponse):
    """Investigation detail enriched with the related alert payload."""

    alert: dict[str, object] | None = Field(
        default=None, description="Related alert snapshot, when available."
    )
    related_event_ids: list[str] = Field(
        default_factory=list, description="Event ids referenced by the alerts."
    )
