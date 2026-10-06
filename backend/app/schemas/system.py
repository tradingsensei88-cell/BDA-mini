"""Schemas for system health endpoints (``/api/health``, ``/api/system/*``)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ServiceHealth(BaseModel):
    """Health snapshot of one platform dependency."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "service": "postgres",
                "display_name": "PostgreSQL",
                "status": "healthy",
                "latency_ms": 3.2,
                "uptime": 99.98,
                "message": "SELECT 1 OK",
                "checked_at": "2026-10-06T14:05:00Z",
            }
        }
    )

    service: str = Field(description="Service key (kafka/spark/hdfs/postgres/redis/websocket/backend).")
    display_name: str = Field(description="Human-readable service name.")
    status: str = Field(description="healthy / warning / offline.")
    latency_ms: float | None = Field(default=None, ge=0, description="Probe round-trip (ms).")
    uptime: float = Field(default=100.0, ge=0, le=100, description="Recent check success rate, 0-100.")
    message: str = Field(default="", description="Probe result detail.")
    details: dict[str, object] = Field(
        default_factory=dict, description="Extra service-specific details."
    )
    checked_at: datetime = Field(description="Probe time (UTC).")


class PipelineStage(BaseModel):
    """One stage of the end-to-end streaming pipeline."""

    id: str = Field(description="Stage key (ingest/kafka/spark/ml/postgres/websocket).")
    name: str = Field(description="Display name.")
    status: str = Field(description="healthy / warning / offline.")
    latency_ms: float | None = Field(default=None, ge=0, description="Stage latency (ms).")
    throughput: str = Field(default="", description="Human-readable throughput, e.g. ``12.4 ev/s``.")
    processed: int = Field(default=0, ge=0, description="Items processed by the stage.")
    note: str = Field(default="", description="Operator note (e.g. demo-mode hint).")


class PipelineStatus(BaseModel):
    """Aggregate pipeline health spanning ingestion to dashboard."""

    status: str = Field(description="Aggregate status: healthy / warning / offline.")
    mode: str = Field(description="Operating mode: ``live`` or ``demo``.")
    stages: list[PipelineStage] = Field(default_factory=list, description="Ordered stages.")
    events_per_sec: float = Field(default=0.0, ge=0, description="Current ingestion rate.")
    total_events: int = Field(default=0, ge=0, description="Events processed since startup.")


class SystemStatusResponse(BaseModel):
    """Detailed system status returned by ``GET /api/system/status``."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "warning",
                "mode": "demo",
                "version": "0.1.0",
                "environment": "development",
                "uptime_seconds": 1830.5,
                "checked_at": "2026-10-06T14:05:00Z",
                "services": [],
                "pipeline": {
                    "status": "warning",
                    "mode": "demo",
                    "stages": [],
                    "events_per_sec": 12.4,
                    "total_events": 15604,
                },
                "database": {"available": False},
                "redis": {"available": False},
                "websocket": {"connections": 2},
            }
        }
    )

    status: str = Field(description="Aggregate status: healthy / warning / offline.")
    mode: str = Field(description="Operating mode: ``live`` or ``demo``.")
    version: str = Field(description="Backend version.")
    environment: str = Field(description="Deployment environment name.")
    uptime_seconds: float = Field(ge=0, description="Backend process uptime (seconds).")
    checked_at: datetime = Field(description="Probe time (UTC).")
    services: list[ServiceHealth] = Field(
        default_factory=list, description="Per-service health snapshots."
    )
    pipeline: PipelineStatus = Field(description="Streaming pipeline view.")
    database: dict[str, object] = Field(default_factory=dict, description="Database diagnostics.")
    redis: dict[str, object] = Field(default_factory=dict, description="Redis diagnostics.")
    websocket: dict[str, object] = Field(
        default_factory=dict, description="WebSocket connection statistics."
    )
    demo_mode: bool = Field(default=True, description="Whether demo data generation is active.")


class HealthResponse(BaseModel):
    """Lightweight overall health check returned by ``GET /api/health``."""

    status: str = Field(description="healthy / degraded.", examples=["healthy"])
    service: str = Field(description="Service identifier.", examples=["cybershield-backend"])
    version: str = Field(description="Backend version.")
    environment: str = Field(description="Deployment environment.")
    mode: str = Field(description="Operating mode: ``live`` or ``demo``.")
    uptime_seconds: float = Field(ge=0, description="Process uptime (seconds).")
    checks: dict[str, str] = Field(
        default_factory=dict, description="Component -> status map (e.g. database: offline)."
    )
    checked_at: datetime = Field(description="Check time (UTC).")
