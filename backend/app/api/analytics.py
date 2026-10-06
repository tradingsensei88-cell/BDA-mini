"""Analytics routes - chart-ready payloads for the dashboard.

All endpoints accept a ``window`` query parameter (``15m`` / ``1h`` / ``6h`` /
``24h`` / ``7d``, default ``24h``) and return data shaped for direct binding
into the frontend charts.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import AnalyticsDep, TimeWindowDep
from app.schemas.analytics import (
    AttackDistributionResponse,
    HeatmapResponse,
    ProtocolDistributionResponse,
    TimelineResponse,
    TopSourcesResponse,
)

router = APIRouter(tags=["analytics"])


@router.get(
    "/attack-distribution",
    response_model=AttackDistributionResponse,
    summary="Attack category distribution",
    description="Counts, percentages, colors and severity weights per attack category (donut chart).",
)
async def attack_distribution(
    analytics: AnalyticsDep, window: TimeWindowDep
) -> AttackDistributionResponse:
    return AttackDistributionResponse.model_validate(analytics.attack_distribution(window))


@router.get(
    "/timeline",
    response_model=TimelineResponse,
    summary="Events over time",
    description=(
        "Stacked events-over-time buckets (per-category counts) for the area "
        "chart. The bucket size adapts to the window (1m / 5m / 15m / 1h / 6h)."
    ),
)
async def timeline(analytics: AnalyticsDep, window: TimeWindowDep) -> TimelineResponse:
    return TimelineResponse.model_validate(analytics.timeline(window))


@router.get(
    "/top-sources",
    response_model=TopSourcesResponse,
    summary="Top threat sources",
    description="Noisiest source hosts ranked by attack count, with mean/peak risk and top attack label.",
)
async def top_sources(
    analytics: AnalyticsDep,
    window: TimeWindowDep,
    limit: int = Query(10, ge=1, le=50, description="Number of sources to return."),
) -> TopSourcesResponse:
    return TopSourcesResponse.model_validate(analytics.top_sources(window, limit=limit))


@router.get(
    "/heatmap",
    response_model=HeatmapResponse,
    summary="Threat heatmap",
    description=(
        "Threat intensity matrix: source host x hour cells, hour labels, "
        "severity totals and the heat scale maximum."
    ),
)
async def heatmap(
    analytics: AnalyticsDep,
    window: TimeWindowDep,
    max_hosts: int = Query(12, ge=1, le=48, description="Maximum number of host rows."),
) -> HeatmapResponse:
    return HeatmapResponse.model_validate(analytics.heatmap(window, max_hosts=max_hosts))


@router.get(
    "/protocol-distribution",
    response_model=ProtocolDistributionResponse,
    summary="Protocol distribution",
    description="TCP / UDP / ICMP split with benign vs attack counts and attack rate.",
)
async def protocol_distribution(
    analytics: AnalyticsDep, window: TimeWindowDep
) -> ProtocolDistributionResponse:
    return ProtocolDistributionResponse.model_validate(analytics.protocol_distribution(window))
