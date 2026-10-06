"""Health & system-status routes.

* ``GET /api/health`` - lightweight overall health check.
* ``GET /api/system/status`` - detailed status of every platform dependency
  plus the end-to-end streaming pipeline view.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter

from app.api.deps import SystemDep
from app.core.config import settings
from app.schemas.system import (
    HealthResponse,
    SystemStatusResponse,
)

router = APIRouter(tags=["system"])


def _mode() -> str:
    return "demo" if settings.demo_mode else "live"


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Overall health check",
    description=(
        "Compact health probe suitable for load balancers and container "
        "orchestrators. Returns ``healthy`` when every dependency is OK and "
        "``degraded`` when optional services (Kafka/Spark/HDFS) are down - "
        "the API keeps serving in demo mode."
    ),
)
async def health(system: SystemDep) -> HealthResponse:
    quick = await system.get_quick_health()
    return HealthResponse(
        status=quick["status"],
        service="cybershield-backend",
        version=settings.app_version,
        environment=settings.environment,
        mode=_mode(),
        uptime_seconds=round(time.time() - system.started_at, 1),
        checks=quick["checks"],
        checked_at=datetime.now(timezone.utc),
    )


@router.get(
    "/system/status",
    response_model=SystemStatusResponse,
    summary="Detailed system status",
    description=(
        "Full status snapshot: per-service health probes (backend, "
        "PostgreSQL, Redis, Kafka, Spark, HDFS, WebSocket), the end-to-end "
        "pipeline stages, database/Redis diagnostics and live event metrics."
    ),
)
async def system_status(system: SystemDep) -> SystemStatusResponse:
    payload = await system.get_system_status()
    return SystemStatusResponse.model_validate(payload)
