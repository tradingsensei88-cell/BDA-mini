"""Shared FastAPI dependencies.

Centralizes:

* service accessors (``Depends`` providers wiring the singletons),
* reusable query-parameter groups (pagination, filters, time windows),
* annotated dependency aliases used by every route module.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import Depends, Query

from app.schemas.common import (
    FilterParams,
    PaginationParams,
    TimeRange,
    parse_time_range,
)
from app.services.alert_engine import AlertEngine, get_alert_engine
from app.services.analytics_service import AnalyticsService, get_analytics_service
from app.services.event_service import EventProcessingService, get_event_service
from app.services.investigation_service import (
    InvestigationService,
    get_investigation_service,
)
from app.services.ml_service import MLService, get_ml_service
from app.services.simulation_service import SimulationService, get_simulation_service
from app.services.system_service import SystemService, get_system_service

# ---------------------------------------------------------------------------
# Service accessors (FastAPI-friendly providers around the singletons)
# ---------------------------------------------------------------------------


def events_service() -> EventProcessingService:
    """Shared event processing service."""

    return get_event_service()


def alerts_service() -> AlertEngine:
    """Shared alert engine."""

    return get_alert_engine()


def analytics_service() -> AnalyticsService:
    """Shared analytics service."""

    return get_analytics_service()


def ml_service() -> MLService:
    """Shared ML intelligence service."""

    return get_ml_service()


def system_service() -> SystemService:
    """Shared system health service."""

    return get_system_service()


def simulation_service() -> SimulationService:
    """Shared simulation controller."""

    return get_simulation_service()


def investigations_service() -> InvestigationService:
    """Shared investigation service."""

    return get_investigation_service()


EventsDep = Annotated[EventProcessingService, Depends(events_service)]
AlertsDep = Annotated[AlertEngine, Depends(alerts_service)]
AnalyticsDep = Annotated[AnalyticsService, Depends(analytics_service)]
MLDep = Annotated[MLService, Depends(ml_service)]
SystemDep = Annotated[SystemService, Depends(system_service)]
SimulationDep = Annotated[SimulationService, Depends(simulation_service)]
InvestigationsDep = Annotated[InvestigationService, Depends(investigations_service)]

# ---------------------------------------------------------------------------
# Query-parameter dependency groups
# ---------------------------------------------------------------------------


def pagination_params(
    page: int = Query(1, ge=1, description="1-based page number.", examples=[1]),
    page_size: int = Query(
        25, ge=1, le=200, description="Items per page (max 200).", examples=[25]
    ),
) -> PaginationParams:
    """Standard pagination query parameters."""

    return PaginationParams(page=page, page_size=page_size)


def filter_params(
    search: str | None = Query(
        default=None,
        max_length=128,
        description="Free-text search across hosts, IPs and attack types.",
        examples=["172.16"],
    ),
    time_range: str | None = Query(
        default=None,
        description="Preset window: 15m / 1h / 6h / 24h / 7d.",
        examples=["24h"],
    ),
    start_time: datetime | None = Query(default=None, description="Inclusive lower bound (UTC)."),
    end_time: datetime | None = Query(default=None, description="Inclusive upper bound (UTC)."),
) -> FilterParams:
    """Common list filters (search + time window)."""

    return FilterParams(
        search=search,
        time_range=time_range,
        start_time=start_time,
        end_time=end_time,
    )


def time_window_param(
    window: str | None = Query(
        default=None,
        description="Analysis window: 15m / 1h / 6h / 24h / 7d (default 24h).",
        examples=["24h"],
    ),
) -> TimeRange:
    """Resolve the ``window`` query parameter to a preset ``TimeRange``."""

    return parse_time_range(window, default=TimeRange.H24)


PaginationDep = Annotated[PaginationParams, Depends(pagination_params)]
FiltersDep = Annotated[FilterParams, Depends(filter_params)]
TimeWindowDep = Annotated[TimeRange, Depends(time_window_param)]
