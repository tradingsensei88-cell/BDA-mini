"""Schemas for analytics endpoints (``/api/analytics/*``).

Every model is shaped "ready to render": the frontend can bind the arrays
directly into charts without further transformation.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AttackDistributionItem(BaseModel):
    """One slice of the attack-category donut chart."""

    category: str = Field(description="Category key (normal/DoS/Probe/R2L/U2R).")
    label: str = Field(description="Display label.")
    count: int = Field(ge=0, description="Number of events in this category.")
    percentage: float = Field(ge=0, le=100, description="Share of total, 0-100.")
    color: str = Field(description="Suggested hex color for the chart.", examples=["#f97316"])
    severity_weight: float = Field(
        default=0.0, ge=0, le=1, description="Severity weight used in risk scoring."
    )


class AttackDistributionResponse(BaseModel):
    """Distribution of events across attack categories."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "window": "24h",
                "total": 3600,
                "items": [
                    {"category": "Normal", "label": "Normal", "count": 2016, "percentage": 56.0, "color": "#22c55e", "severity_weight": 0.0},
                    {"category": "DoS", "label": "DoS", "count": 720, "percentage": 20.0, "color": "#ef4444", "severity_weight": 0.7},
                ],
                "generated_at": "2026-10-06T14:05:00Z",
            }
        }
    )

    window: str = Field(description="Window the distribution covers.", examples=["24h"])
    total: int = Field(ge=0, description="Total events counted.")
    items: list[AttackDistributionItem] = Field(
        default_factory=list, description="Per-category breakdown."
    )
    generated_at: datetime = Field(description="Computation time (UTC).")


class TimelinePoint(BaseModel):
    """One time bucket of the stacked attack timeline."""

    time: datetime = Field(description="Bucket start (UTC).")
    label: str = Field(description="Short display label, e.g. ``14:05``.")
    normal: int = Field(ge=0, description="Normal flow count.")
    dos: int = Field(ge=0, description="DoS flow count.")
    probe: int = Field(ge=0, description="Probe flow count.")
    r2l: int = Field(ge=0, description="R2L flow count.")
    u2r: int = Field(ge=0, description="U2R flow count.")
    total: int = Field(ge=0, description="All flows in the bucket.")


class TimelineResponse(BaseModel):
    """Events over time, bucketed for the stacked area chart."""

    window: str = Field(description="Requested window (15m/1h/6h/24h/7d).")
    bucket_seconds: int = Field(ge=1, description="Duration of each bucket in seconds.")
    points: list[TimelinePoint] = Field(default_factory=list, description="Ordered buckets.")
    generated_at: datetime = Field(description="Computation time (UTC).")


class TopSourceItem(BaseModel):
    """Aggregated reputation row for a noisy source host."""

    source_ip: str = Field(description="Source IP address.")
    source_host: str = Field(description="Source host name.")
    events: int = Field(ge=0, description="Total events from this source.")
    threats: int = Field(ge=0, description="Attack events from this source.")
    normal: int = Field(ge=0, description="Benign events from this source.")
    risk_score: float = Field(ge=0, le=100, description="Mean risk score, 0-100.")
    max_risk_score: float = Field(ge=0, le=100, description="Peak risk score observed.")
    top_attack: str = Field(description="Most frequent attack label.")
    attack_category: str = Field(description="Dominant attack category.")
    last_seen: datetime = Field(description="Most recent event time (UTC).")
    first_seen: datetime = Field(description="Earliest event time (UTC).")


class TopSourcesResponse(BaseModel):
    """Most active / riskiest source hosts."""

    window: str = Field(description="Window covered.")
    items: list[TopSourceItem] = Field(default_factory=list, description="Ranked sources.")
    generated_at: datetime = Field(description="Computation time (UTC).")


class HeatmapRow(BaseModel):
    """One host row of the threat heatmap (24 hourly cells)."""

    host: str = Field(description="Source host name.")
    source_ip: str = Field(description="Source IP address.")
    cells: list[int] = Field(
        default_factory=list, description="Threat counts per hour (oldest -> newest)."
    )
    total: int = Field(ge=0, description="Row total.")


class HeatmapResponse(BaseModel):
    """Threat intensity heatmap: source host x hour x severity."""

    window: str = Field(description="Window covered (typically 24h).")
    hours: list[str] = Field(
        default_factory=list, description="Hour labels (oldest -> newest)."
    )
    rows: list[HeatmapRow] = Field(default_factory=list, description="Per-host rows.")
    severity_totals: dict[str, int] = Field(
        default_factory=dict, description="Totals per severity across the window."
    )
    max_value: int = Field(ge=0, description="Maximum cell value (heat scale).")
    generated_at: datetime = Field(description="Computation time (UTC).")


class ProtocolDistributionItem(BaseModel):
    """Protocol breakdown for the horizontal bar chart."""

    protocol: str = Field(description="Protocol name.", examples=["TCP"])
    normal: int = Field(ge=0, description="Benign flows.")
    attacks: int = Field(ge=0, description="Attack flows.")
    total: int = Field(ge=0, description="All flows.")
    attack_rate: float = Field(ge=0, le=100, description="Attack share, 0-100.")


class ProtocolDistributionResponse(BaseModel):
    """Distribution of traffic across transport protocols."""

    window: str = Field(description="Window covered.")
    items: list[ProtocolDistributionItem] = Field(
        default_factory=list, description="Per-protocol breakdown."
    )
    generated_at: datetime = Field(description="Computation time (UTC).")
