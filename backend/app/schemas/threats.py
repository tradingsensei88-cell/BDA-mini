"""Schemas for the threat intelligence endpoints (``/api/threats``)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import FilterParams, PaginatedResponse


class ThreatFilters(FilterParams):
    """Filters accepted by ``GET /api/threats``."""

    attack_category: str | None = Field(
        default=None, description="DoS / Probe / R2L / U2R.", examples=["Probe"]
    )
    attack_type: str | None = Field(
        default=None, description="Fine-grained label, e.g. neptune.", examples=["neptune"]
    )
    severity: str | None = Field(
        default=None, description="critical / high / medium / low / info.", examples=["high"]
    )
    min_risk: float | None = Field(
        default=None, ge=0, le=100, description="Minimum composite risk score.", examples=[60]
    )
    source_ip: str | None = Field(default=None, description="Filter by source IP.")
    status: str | None = Field(
        default=None, description="Triage status filter (new/investigating/acknowledged/resolved)."
    )


class ThreatResponse(BaseModel):
    """A confirmed threat event (attack flows only)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "3f9d1a2e-6c1b-4bb7-9c22-2f6d27f9c111",
                "timestamp": "2026-10-06T14:03:22.451000Z",
                "source": "HOST-014",
                "source_ip": "172.16.4.14",
                "destination": "HOST-042",
                "destination_ip": "10.0.2.42",
                "protocol": "TCP",
                "attack_category": "DoS",
                "attack_type": "neptune",
                "confidence": 0.9721,
                "risk_score": 78.4,
                "risk_band": "High",
                "severity": "high",
                "status": "new",
                "anomaly_score": 0.71,
                "top_features": ["count", "serror_rate"],
                "alert_id": "b2a7c4d1-90f2-4f7e-a3de-1f02c7a1e8a4",
            }
        }
    )

    id: str = Field(description="Underlying event id.")
    timestamp: datetime = Field(description="Event time (UTC).")

    source: str = Field(description="Source host name.")
    source_ip: str = Field(description="Source IP address.")
    destination: str = Field(description="Destination host name.")
    destination_ip: str = Field(description="Destination IP address.")
    destination_port: int | None = Field(default=None, ge=0, le=65535)
    protocol: str = Field(description="Transport protocol.")

    attack_category: str = Field(description="Attack category (DoS/Probe/R2L/U2R).")
    attack_type: str = Field(description="Fine-grained attack label.")
    predicted_category: str = Field(default="", description="Model-predicted category.")
    confidence: float = Field(ge=0.0, le=1.0, description="Model confidence 0-1.")
    risk_score: float = Field(ge=0.0, le=100.0, description="Composite risk score 0-100.")
    risk_band: str = Field(description="Risk band label.")
    severity: str = Field(description="Severity level.")
    status: str = Field(description="Triage status.")
    anomaly_score: float | None = Field(default=None, description="Anomaly score 0-1.")

    bytes_total: int = Field(default=0, ge=0, description="Total bytes observed.")
    top_features: list[str] = Field(
        default_factory=list, description="Top contributing model features."
    )
    alert_id: str | None = Field(
        default=None, description="Related alert id, when one was generated."
    )
    investigation_ids: list[str] = Field(
        default_factory=list, description="Investigations referencing this threat."
    )


class ThreatList(PaginatedResponse[ThreatResponse]):
    """Paginated collection of threat events."""


class ThreatInvestigationSummary(BaseModel):
    """Short summary of an investigation linked to a threat."""

    id: str = Field(description="Investigation id.")
    title: str = Field(description="Investigation title.")
    status: str = Field(description="Case status (open/in_progress/on_hold/closed).")
    priority: str = Field(description="Case priority.")
    analyst: str | None = Field(default=None, description="Assigned analyst.")
    opened_at: datetime | None = Field(default=None, description="Case opened time (UTC).")


class ThreatDetail(ThreatResponse):
    """Threat detail with model output, raw features and investigation context."""

    probabilities: dict[str, float] = Field(
        default_factory=dict, description="Per-class probability distribution."
    )
    features: dict[str, object] = Field(
        default_factory=dict, description="Raw NSL-KDD feature vector for this flow."
    )
    model_name: str | None = Field(default=None, description="Scoring model name.")
    model_version: str | None = Field(default=None, description="Model version string.")
    latency_ms: float | None = Field(default=None, ge=0, description="Inference latency (ms).")
    description: str = Field(default="", description="Human-readable threat summary.")
    recommendations: list[str] = Field(
        default_factory=list, description="Suggested analyst playbook actions."
    )
    investigations: list[ThreatInvestigationSummary] = Field(
        default_factory=list, description="Investigations referencing this threat."
    )
