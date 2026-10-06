"""Investigation routes.

* ``GET /api/investigations`` - paginated case list (filter by status / text).
* ``GET /api/investigations/{investigation_id}`` - case detail enriched with
  the related alert snapshot.
* ``POST /api/investigations`` - open a case from an alert.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, status as http_status

from app.api.deps import AlertsDep, InvestigationsDep, PaginationDep
from app.core.exceptions import NotFoundError
from app.schemas.investigations import (
    InvestigationCreate,
    InvestigationDetail,
    InvestigationList,
    InvestigationResponse,
)

router = APIRouter(tags=["investigations"])


@router.get(
    "",
    response_model=InvestigationList,
    summary="List investigations",
    description="Newest-first analyst case files, filterable by status and free text.",
)
async def list_investigations(
    investigations: InvestigationsDep,
    pagination: PaginationDep,
    case_status: str | None = Query(
        default=None,
        alias="status",
        description="open / in_progress / on_hold / closed.",
        examples=["open"],
    ),
    search: str | None = Query(
        default=None, max_length=128, description="Free-text search.", examples=["ddos"]
    ),
) -> InvestigationList:
    items, total = investigations.list_investigations(
        status=case_status,
        search=search,
        offset=pagination.offset,
        limit=pagination.page_size,
    )
    return InvestigationList.create(items, total, pagination.page, pagination.page_size)


@router.post(
    "",
    response_model=InvestigationResponse,
    status_code=http_status.HTTP_201_CREATED,
    summary="Open an investigation from an alert",
    description="Creates a case file linked to the given alert (title/priority default from the alert).",
    responses={404: {"description": "Alert not found"}},
)
async def create_investigation(
    payload: InvestigationCreate,
    investigations: InvestigationsDep,
    alerts: AlertsDep,
) -> InvestigationResponse:
    alert = alerts.get_alert(payload.alert_id)
    if alert is None:
        raise NotFoundError("Alert", payload.alert_id)

    record = await investigations.create_from_alert(
        alert,
        title=payload.title,
        analyst=payload.analyst,
        priority=payload.priority,
        summary=payload.summary,
        tags=payload.tags,
    )
    return InvestigationResponse.model_validate(record)


@router.get(
    "/{investigation_id}",
    response_model=InvestigationDetail,
    summary="Investigation detail",
    description=(
        "Full case record plus the related alert snapshot and the event ids "
        "referenced by that alert."
    ),
    responses={404: {"description": "Investigation not found"}},
)
async def get_investigation(
    investigation_id: str,
    investigations: InvestigationsDep,
    alerts: AlertsDep,
) -> InvestigationDetail:
    record = investigations.get(investigation_id)
    if record is None:
        raise NotFoundError("Investigation", investigation_id)

    alert: dict | None = None
    related_event_ids: list[str] = []
    for alert_id in record.get("related_alert_ids") or []:
        candidate = alerts.get_alert(str(alert_id))
        if candidate is not None:
            alert = candidate
            related_event_ids = [str(e) for e in candidate.get("related_event_ids") or []]
            break

    return InvestigationDetail(
        **record,
        alert=alert,
        related_event_ids=related_event_ids,
    )
