"""Schemas for the simulation control endpoints (``/api/simulation/*``)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SimulationStatus(BaseModel):
    """Current state of the traffic simulation (demo generator or Kafka producer)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "state": "running",
                "running": True,
                "paused": False,
                "rate": 100,
                "events_per_sec": 12.3,
                "avg_events_per_sec": 12.1,
                "total_events": 15604,
                "alerts_generated": 322,
                "anomalies_detected": 41,
                "category_breakdown": {
                    "Normal": 8750,
                    "DoS": 3120,
                    "Probe": 2028,
                    "R2L": 1085,
                    "U2R": 621,
                },
                "source": "demo",
                "demo_mode": True,
                "started_at": "2026-10-06T13:35:00Z",
                "uptime_seconds": 1830.5,
                "last_event_at": "2026-10-06T14:05:31Z",
                "message": "Simulation is running.",
            }
        }
    )

    state: str = Field(description="Lifecycle state: running / paused / stopped.")
    running: bool = Field(description="Whether the generator task is alive.")
    paused: bool = Field(description="Whether emission is currently paused.")
    rate: int = Field(ge=1, description="Configured emission rate (events/second).")
    events_per_sec: float = Field(ge=0, description="Measured instantaneous rate.")
    avg_events_per_sec: float = Field(ge=0, description="Average rate since start.")
    total_events: int = Field(ge=0, description="Events emitted since start.")
    alerts_generated: int = Field(default=0, ge=0, description="Alerts created by the pipeline.")
    anomalies_detected: int = Field(default=0, ge=0, description="Anomalies detected.")
    category_breakdown: dict[str, int] = Field(
        default_factory=dict, description="Event counts per attack category."
    )
    source: str = Field(default="demo", description="Event source: ``demo`` or ``kafka``.")
    demo_mode: bool = Field(default=True, description="Whether demo mode is enabled.")
    started_at: datetime | None = Field(default=None, description="Run start time (UTC).")
    uptime_seconds: float = Field(default=0.0, ge=0, description="Run uptime (seconds).")
    last_event_at: datetime | None = Field(default=None, description="Last emitted event (UTC).")
    message: str = Field(default="", description="Operator-facing status message.")


class SimulationControl(BaseModel):
    """Body of ``POST /api/simulation/rate``."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"rate": 100}},
    )

    rate: int = Field(
        ge=1,
        le=10_000,
        description="Desired emission rate in events/second (1-10000).",
        examples=[100],
    )


class SimulationControlResponse(BaseModel):
    """Generic action result for start/pause/resume/reset/rate."""

    ok: bool = Field(description="Whether the action succeeded.")
    message: str = Field(description="Human-readable outcome.")
    status: SimulationStatus = Field(description="Simulation status after the action.")
