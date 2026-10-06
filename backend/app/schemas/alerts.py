"""Schemas for alert triage endpoints (``/api/alerts``)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import FilterParams, PaginatedResponse

#: Statuses accepted on the API edge. ``new`` is an alias of ``open``.
ALERT_STATUS_VALUES = ("new", "open", "acknowledged", "investigating", "resolved", "false_positive")

#: Canonical persisted statuses (mirrors the ``alerts.status`` CHECK constraint).
PERSISTED_ALERT_STATUSES = (
    "open",
    "acknowledged",
    "investigating",
    "resolved",
    "false_positive",
)


def normalize_alert_status(value: str) -> str:
    """Normalise an API status value to its persisted form (``new`` -> ``open``)."""

    normalized = value.strip().lower()
    if normalized in ("new", "open", ""):
        return "open"
    if normalized in PERSISTED_ALERT_STATUSES:
        return normalized
    raise ValueError(
        f"invalid alert status {value!r}; expected one of {ALERT_STATUS_VALUES}"
    )


class AlertResponse(BaseModel):
    """A generated SOC alert."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "b2a7c4d1-90f2-4f7e-a3de-1f02c7a1e8a4",
                "alert_type": "ddos",
                "title": "DoS attack detected on HOST-042",
                "description": "neptune flood from 172.16.4.14 (confidence 0.97, risk 78.4).",
                "severity": "high",
                "status": "open",
                "risk_score": 78.4,
                "confidence": 0.9721,
                "source_host": "HOST-014",
                "source_ip": "172.16.4.14",
                "destination_host": "HOST-042",
                "destination_ip": "10.0.2.42",
                "attack_category": "DoS",
                "attack_type": "neptune",
                "occurrences": 4,
                "related_event_ids": ["0f8fad5b-d9cb-469f-a165-70867728950e"],
                "created_at": "2026-10-06T14:03:22.451000Z",
            }
        }
    )

    id: str = Field(description="Alert id (UUID).")
    alert_type: str = Field(description="Alert family: ddos / port_scan / anomaly / ...")
    title: str = Field(description="Short alert headline.")
    description: str | None = Field(default=None, description="Longer explanation.")
    severity: str = Field(description="critical / high / medium / low / info.")
    status: str = Field(description="Lifecycle status (open/acknowledged/investigating/resolved/false_positive).")
    risk_score: float | None = Field(default=None, ge=0, le=100, description="Composite risk 0-100.")
    confidence: float | None = Field(default=None, ge=0, le=1, description="Detection confidence 0-1.")

    source_host: str | None = Field(default=None, description="Source host name.")
    source_ip: str | None = Field(default=None, description="Source IP address.")
    destination_host: str | None = Field(default=None, description="Destination host name.")
    destination_ip: str | None = Field(default=None, description="Destination IP address.")

    attack_category: str | None = Field(default=None, description="Attack category.")
    attack_type: str | None = Field(default=None, description="Fine-grained attack label.")

    occurrences: int = Field(default=1, ge=1, description="Times this alert pattern repeated.")
    related_event_ids: list[str] = Field(
        default_factory=list, description="Contributing event ids."
    )
    evidence: dict[str, object] = Field(
        default_factory=dict, description="Supporting model output / features."
    )

    assigned_to: str | None = Field(default=None, description="Analyst the alert is assigned to.")
    created_at: datetime = Field(description="Alert creation time (UTC).")
    updated_at: datetime | None = Field(default=None, description="Last update time (UTC).")
    acknowledged_at: datetime | None = Field(default=None, description="Acknowledgement time.")
    resolved_at: datetime | None = Field(default=None, description="Resolution time.")


class AlertList(PaginatedResponse[AlertResponse]):
    """Paginated collection of alerts."""


class AlertFilters(FilterParams):
    """Filters accepted by ``GET /api/alerts``."""

    severity: str | None = Field(
        default=None, description="critical / high / medium / low / info.", examples=["critical"]
    )
    status: str | None = Field(
        default=None,
        description="Comma-separated statuses; ``new`` is accepted as alias of ``open``.",
        examples=["open,investigating"],
    )
    alert_type: str | None = Field(
        default=None, description="Alert family filter.", examples=["ddos"]
    )
    min_risk: float | None = Field(default=None, ge=0, le=100, description="Minimum risk score.")


class AlertCreate(BaseModel):
    """Payload for manually opening an alert (used by tests / tooling)."""

    alert_type: str = Field(description="Alert family.", examples=["port_scan"])
    title: str = Field(min_length=3, max_length=255, description="Alert headline.")
    description: str | None = Field(default=None, description="Longer explanation.")
    severity: str = Field(default="medium", description="Severity level.")
    source_ip: str | None = Field(default=None, description="Source IP.")
    destination_ip: str | None = Field(default=None, description="Destination IP.")
    risk_score: float | None = Field(default=None, ge=0, le=100, description="Risk score 0-100.")

    @field_validator("severity")
    @classmethod
    def _validate_severity(cls, value: str) -> str:
        allowed = {"critical", "high", "medium", "low", "info"}
        if value not in allowed:
            raise ValueError(f"severity must be one of {sorted(allowed)}")
        return value


class AlertUpdate(BaseModel):
    """Payload for ``PATCH /api/alerts/{alert_id}``."""

    status: str | None = Field(
        default=None,
        description="New lifecycle status; ``new`` is accepted as alias of ``open``.",
        examples=["investigating"],
    )
    assigned_to: str | None = Field(
        default=None, max_length=128, description="Analyst to assign.", examples=["analyst-7"]
    )
    note: str | None = Field(
        default=None, max_length=1000, description="Optional triage note appended to evidence."
    )

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_alert_status(value)


class AlertStatusCount(BaseModel):
    """One status/severity bucket of :class:`AlertStats`."""

    key: str = Field(description="Status or severity value.")
    count: int = Field(ge=0, description="Number of alerts.")


class AlertStats(BaseModel):
    """Aggregate alert statistics for the SOC overview."""

    total: int = Field(ge=0, description="Total alerts generated.")
    active: int = Field(ge=0, description="Alerts in open/acknowledged/investigating state.")
    last_24h: int = Field(ge=0, description="Alerts created in the last 24 hours.")
    avg_risk_score: float = Field(ge=0, le=100, description="Mean risk score across alerts.")
    by_severity: list[AlertStatusCount] = Field(
        default_factory=list, description="Counts per severity level."
    )
    by_status: list[AlertStatusCount] = Field(
        default_factory=list, description="Counts per lifecycle status."
    )
    recent: list[AlertResponse] = Field(
        default_factory=list, description="The most recent alerts."
    )
