"""Event routes.

* ``GET /api/events`` - paginated, filterable event feed (newest first).
* ``GET /api/events/{event_id}`` - single event detail.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import EventsDep, FiltersDep, PaginationDep
from app.core.exceptions import NotFoundError
from app.schemas.events import NetworkEventList, NetworkEventResponse

router = APIRouter(tags=["events"])


@router.get(
    "",
    response_model=NetworkEventList,
    summary="List network events",
    description=(
        "Newest-first feed of network/security events enriched with the model "
        "prediction, composite risk score and severity. Supports pagination "
        "plus filters on attack type/category, severity, risk and source."
    ),
)
async def list_events(
    events: EventsDep,
    pagination: PaginationDep,
    filters: FiltersDep,
    attack_type: str | None = Query(
        default=None, description="Fine-grained NSL-KDD label.", examples=["neptune"]
    ),
    attack_category: str | None = Query(
        default=None, description="Attack category filter.", examples=["DoS"]
    ),
    severity: str | None = Query(
        default=None, description="Severity filter.", examples=["high"]
    ),
    is_attack: bool | None = Query(
        default=None, description="Only attacks (true) or only benign (false)."
    ),
    min_risk: float | None = Query(
        default=None, ge=0, le=100, description="Minimum composite risk score."
    ),
    source_ip: str | None = Query(default=None, description="Exact source IP filter."),
) -> NetworkEventList:
    items, total = events.get_recent_events(
        limit=pagination.page_size,
        offset=pagination.offset,
        attack_type=attack_type,
        attack_category=attack_category,
        severity=severity,
        is_attack=is_attack,
        min_risk=min_risk,
        source_ip=source_ip,
        search=filters.search,
        since=filters.resolve_since(),
        until=filters.end_time,
    )
    return NetworkEventList.create(items, total, pagination.page, pagination.page_size)


@router.get(
    "/{event_id}",
    response_model=NetworkEventResponse,
    summary="Event detail",
    description="Full record of a single event including the raw feature vector and probabilities.",
    responses={404: {"description": "Event not found"}},
)
async def get_event(event_id: str, events: EventsDep) -> NetworkEventResponse:
    record = events.get_event_by_id(event_id)
    if record is None:
        raise NotFoundError("Event", event_id)
    return NetworkEventResponse.model_validate(record)
