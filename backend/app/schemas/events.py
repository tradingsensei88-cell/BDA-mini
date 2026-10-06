"""Schemas for network/security event endpoints (``/api/events``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import PaginatedResponse

_EVENT_EXAMPLE = {
    "id": "0f8fad5b-d9cb-469f-a165-70867728950e",
    "timestamp": "2026-10-06T14:03:22.451000Z",
    "ingested_at": "2026-10-06T14:03:22.512000Z",
    "source_host": "HOST-014",
    "source_ip": "172.16.4.14",
    "destination_host": "HOST-042",
    "destination_ip": "10.0.2.42",
    "source_port": 51_332,
    "destination_port": 80,
    "protocol": "TCP",
    "service": "http",
    "flag": "SF",
    "duration": 0,
    "src_bytes": 231,
    "dst_bytes": 512,
    "attack_type": "neptune",
    "attack_category": "DoS",
    "predicted_category": "DoS",
    "is_attack": True,
    "confidence": 0.9721,
    "risk_score": 78.4,
    "risk_band": "High",
    "severity": "high",
    "anomaly_score": 0.71,
    "top_features": ["count", "serror_rate", "src_bytes"],
    "status": "new",
}


class NetworkEventResponse(BaseModel):
    """A single network flow enriched with the model's prediction and risk score."""

    id: str = Field(description="Event id (UUID).")
    timestamp: datetime = Field(description="Event time (UTC).")
    ingested_at: datetime = Field(description="Ingestion time (UTC).")

    source_host: str = Field(description="Origin host name.", examples=["HOST-014"])
    source_ip: str = Field(description="Origin IP address.", examples=["172.16.4.14"])
    destination_host: str = Field(description="Target host name.", examples=["HOST-042"])
    destination_ip: str = Field(description="Target IP address.", examples=["10.0.2.42"])
    source_port: int | None = Field(default=None, ge=0, le=65535)
    destination_port: int | None = Field(default=None, ge=0, le=65535)

    protocol: str = Field(description="Transport protocol (TCP/UDP/ICMP).", examples=["TCP"])
    service: str = Field(description="Destination service.", examples=["http"])
    flag: str = Field(description="NSL-KDD connection flag.", examples=["SF"])
    duration: int = Field(default=0, ge=0, description="Connection duration in seconds.")

    src_bytes: int = Field(default=0, ge=0, description="Bytes sent by the source.")
    dst_bytes: int = Field(default=0, ge=0, description="Bytes sent by the destination.")
    bytes_total: int = Field(default=0, ge=0, description="Total bytes on the flow.")
    packets_sent: int = Field(default=0, ge=0)
    packets_received: int = Field(default=0, ge=0)

    attack_type: str = Field(description="Fine-grained NSL-KDD label.", examples=["neptune"])
    attack_category: str = Field(description="Ground-truth category.", examples=["DoS"])
    predicted_category: str = Field(description="Model-predicted category.", examples=["DoS"])
    is_attack: bool = Field(description="True when the model flagged this flow as an attack.")
    confidence: float = Field(ge=0.0, le=1.0, description="Model confidence, 0-1.")
    probabilities: dict[str, float] = Field(
        default_factory=dict, description="Per-class probability distribution."
    )

    risk_score: float = Field(ge=0.0, le=100.0, description="Composite risk score, 0-100.")
    risk_band: str = Field(description="Risk band: Low/Guarded/Medium/High/Critical.")
    severity: str = Field(description="Alert-style severity: critical/high/medium/low/info.")
    anomaly_score: float | None = Field(default=None, description="Anomaly detector score, 0-1.")

    model_name: str | None = Field(default=None, description="Scoring model name.")
    model_version: str | None = Field(default=None, description="Model version string.")
    latency_ms: float | None = Field(default=None, ge=0, description="Inference latency (ms).")

    top_features: list[str] = Field(
        default_factory=list, description="Top contributing features for this decision."
    )
    status: str = Field(
        default="new", description="Triage status (new/investigating/acknowledged/resolved)."
    )
    features: dict[str, Any] = Field(
        default_factory=dict, description="Raw NSL-KDD feature vector."
    )

    model_config = {
        "json_schema_extra": {"example": _EVENT_EXAMPLE},
    }


class NetworkEventList(PaginatedResponse[NetworkEventResponse]):
    """Paginated collection of network events."""

    model_config = {
        "json_schema_extra": {
            "example": {
                "items": [_EVENT_EXAMPLE],
                "total": 3600,
                "page": 1,
                "page_size": 25,
                "pages": 144,
                "has_next": True,
                "has_prev": False,
            }
        }
    }
