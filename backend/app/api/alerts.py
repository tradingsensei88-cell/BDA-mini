"""Alert routes.

* ``GET /api/alerts`` - paginated alert feed (filters: severity, status, type, risk).
* ``GET /api/alerts/stats`` - aggregate alert statistics for the SOC overview.
* ``POST /api/alerts`` - manually open an alert (tooling / tests).
* ``GET /api/alerts/{alert_id}`` - alert detail.
* ``PATCH /api/alerts/{alert_id}`` - status transition / assignment / note.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Query, status

from app.api.deps import AlertsDep, FiltersDep, PaginationDep
from app.core.exceptions import BadRequestError, NotFoundError
from app.schemas.alerts import (
    AlertCreate,
    AlertList,
    AlertResponse,
    AlertStats,
    AlertUpdate,
    normalize_alert_status,
)

router = APIRouter(tags=["alerts"])


def _split_statuses(value: str | None) -> list[str] | None:
    if not value:
        return None
    parts = [part.strip() for part in value.split(",") if part.strip()]
    return parts or None


@router.get(
    "/stats",
    response_model=AlertStats,
    summary="Alert statistics",
    description=(
        "Aggregate counts by severity and lifecycle status plus mean risk and "
        "the most recent alerts - powers the SOC overview tiles."
    ),
)
async def alert_stats(alerts: AlertsDep) -> AlertStats:
    return AlertStats.model_validate(alerts.get_stats(recent_limit=8))


@router.get(
    "",
    response_model=AlertList,
    summary="List alerts",
    description=(
        "Newest-first alert feed. Filter by severity, one or more statuses "
        "(comma-separated; ``new`` is accepted as alias of ``open``), alert "
        "type, minimum risk and free text."
    ),
)
async def list_alerts(
    alerts: AlertsDep,
    pagination: PaginationDep,
    filters: FiltersDep,
    severity: str | None = Query(
        default=None, description="critical / high / medium / low / info.", examples=["critical"]
    ),
    status: str | None = Query(
        default=None,
        description="Comma-separated statuses; ``new`` is accepted as alias of ``open``.",
        examples=["open,investigating"],
    ),
    alert_type: str | None = Query(
        default=None, description="Alert family filter.", examples=["ddos"]
    ),
    min_risk: float | None = Query(default=None, ge=0, le=100, description="Minimum risk score."),
) -> AlertList:
    items, total = alerts.list_alerts(
        statuses=_split_statuses(status),
        severity=severity,
        alert_type=alert_type,
        search=filters.search,
        min_risk=min_risk,
        since=filters.resolve_since(),
        offset=pagination.offset,
        limit=pagination.page_size,
    )
    return AlertList.create(items, total, pagination.page, pagination.page_size)


@router.post(
    "",
    response_model=AlertResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an alert manually",
    description="Opens an alert without a triggering event (used by tooling and tests).",
)
async def create_alert(payload: AlertCreate, alerts: AlertsDep) -> AlertResponse:
    alert = await alerts.create_alert(
        {
            "alert_type": payload.alert_type,
            "title": payload.title,
            "description": payload.description,
            "severity": payload.severity,
            "source_ip": payload.source_ip,
            "destination_ip": payload.destination_ip,
            "risk_score": payload.risk_score,
        }
    )
    return AlertResponse.model_validate(alert)


@router.get(
    "/{alert_id}",
    response_model=AlertResponse,
    summary="Alert detail",
    description="Full alert record including evidence and lifecycle timestamps.",
    responses={404: {"description": "Alert not found"}},
)
async def get_alert(alert_id: str, alerts: AlertsDep) -> AlertResponse:
    alert = alerts.get_alert(alert_id)
    if alert is None:
        raise NotFoundError("Alert", alert_id)
    return AlertResponse.model_validate(alert)


@router.patch(
    "/{alert_id}",
    response_model=AlertResponse,
    summary="Update alert status",
    description=(
        "Transition an alert through its lifecycle "
        "(open -> acknowledged -> investigating -> resolved / false_positive), "
        "optionally assigning an analyst and appending a triage note."
    ),
    responses={404: {"description": "Alert not found"}},
)
async def update_alert(
    alert_id: str,
    alerts: AlertsDep,
    payload: AlertUpdate = Body(...),
) -> AlertResponse:
    if payload.status is None and payload.assigned_to is None and payload.note is None:
        raise BadRequestError("Provide at least one of: status, assigned_to, note.")

    current = alerts.get_alert(alert_id)
    if current is None:
        raise NotFoundError("Alert", alert_id)

    new_status = payload.status or normalize_alert_status(str(current.get("status") or "open"))
    updated = await alerts.update_alert_status(
        alert_id,
        new_status,
        assigned_to=payload.assigned_to,
        note=payload.note,
    )
    if updated is None:  # pragma: no cover - race between get and update
        raise NotFoundError("Alert", alert_id)
    return AlertResponse.model_validate(updated)
