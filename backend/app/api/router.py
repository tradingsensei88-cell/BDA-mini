"""Combined API router.

Mounts every route module under the configured ``/api`` prefix:

* ``/api/health`` + ``/api/system/*``
* ``/api/events``, ``/api/threats``, ``/api/alerts``
* ``/api/analytics/*``, ``/api/ml/*``
* ``/api/simulation/*``, ``/api/investigations``
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    alerts,
    analytics,
    events,
    health,
    investigations,
    ml,
    simulation,
    threats,
)
from app.core.config import settings

api_router = APIRouter(prefix=settings.api_prefix)

api_router.include_router(health.router)
api_router.include_router(events.router, prefix="/events")
api_router.include_router(threats.router, prefix="/threats")
api_router.include_router(alerts.router, prefix="/alerts")
api_router.include_router(analytics.router, prefix="/analytics")
api_router.include_router(ml.router, prefix="/ml")
api_router.include_router(simulation.router, prefix="/simulation")
api_router.include_router(investigations.router, prefix="/investigations")
