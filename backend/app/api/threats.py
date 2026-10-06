"""Threat routes.

* ``GET /api/threats`` - paginated list of confirmed threats (attack flows).
* ``GET /api/threats/{threat_id}`` - threat detail with the full model
  output, raw features and linked investigation data.
"""

from __future__ import annotations

from typing import Any, Mapping

from fastapi import APIRouter, Query

from app.api.deps import AlertsDep, EventsDep, FiltersDep, InvestigationsDep, PaginationDep
from app.core.exceptions import NotFoundError
from app.schemas.threats import (
    ThreatDetail,
    ThreatInvestigationSummary,
    ThreatList,
    ThreatResponse,
)

router = APIRouter(tags=["threats"])

#: Suggested analyst playbook actions per attack category.
_PLAYBOOK: dict[str, list[str]] = {
    "DoS": [
        "Rate-limit or block the source IP at the edge firewall.",
        "Verify upstream scrubbing / DDoS protection is engaged.",
        "Check target host health and connection-table exhaustion.",
    ],
    "Probe": [
        "Block the scanning source and review exposed ports on the target.",
        "Correlate with previous scans from the same subnet.",
        "Confirm IDS signatures fired and tune for the scan profile.",
    ],
    "R2L": [
        "Force a password reset and enable MFA for the targeted account.",
        "Review authentication logs for successful logins from the source.",
        "Check for transferred or modified files on the destination host.",
    ],
    "U2R": [
        "Isolate the affected host immediately and snapshot memory.",
        "Audit privilege changes, shells spawned and new root accounts.",
        "Review kernel/module integrity and scheduled tasks.",
    ],
}
_DEFAULT_PLAYBOOK = [
    "Enrich the source IP reputation and pivot on related events.",
    "Escalate to tier-2 for manual triage if activity continues.",
]


def _to_threat(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(record.get("id")),
        "timestamp": record.get("timestamp"),
        "source": str(record.get("source_host") or "unknown"),
        "source_ip": str(record.get("source_ip") or "0.0.0.0"),
        "destination": str(record.get("destination_host") or "unknown"),
        "destination_ip": str(record.get("destination_ip") or "0.0.0.0"),
        "destination_port": record.get("destination_port"),
        "protocol": str(record.get("protocol") or "TCP"),
        "attack_category": str(record.get("attack_category") or "Unknown"),
        "attack_type": str(record.get("attack_type") or "unknown"),
        "predicted_category": str(record.get("predicted_category") or ""),
        "confidence": float(record.get("confidence") or 0.0),
        "risk_score": float(record.get("risk_score") or 0.0),
        "risk_band": str(record.get("risk_band") or "Low"),
        "severity": str(record.get("severity") or "info"),
        "status": str(record.get("status") or "new"),
        "anomaly_score": record.get("anomaly_score"),
        "bytes_total": int(record.get("bytes_total") or 0),
        "top_features": list(record.get("top_features") or []),
    }


def _alert_index(alerts: Any, event_ids: set[str]) -> dict[str, Mapping[str, Any]]:
    """Map event id -> most recent alert referencing it (single scan)."""

    index: dict[str, Mapping[str, Any]] = {}
    items, _ = alerts.list_alerts(limit=2000)
    for alert in items:  # newest first - first hit wins
        for event_id in alert.get("related_event_ids") or []:
            key = str(event_id)
            if key in event_ids and key not in index:
                index[key] = alert
    return index


@router.get(
    "",
    response_model=ThreatList,
    summary="List threats",
    description=(
        "Confirmed threat feed (events the model classified as attacks), "
        "newest first. Filterable by category, attack type, severity, minimum "
        "risk and source; each row links to its alert when one was generated."
    ),
)
async def list_threats(
    events: EventsDep,
    alerts: AlertsDep,
    pagination: PaginationDep,
    filters: FiltersDep,
    attack_category: str | None = Query(
        default=None, description="DoS / Probe / R2L / U2R.", examples=["Probe"]
    ),
    attack_type: str | None = Query(
        default=None, description="Fine-grained label, e.g. neptune.", examples=["neptune"]
    ),
    severity: str | None = Query(default=None, description="Severity level.", examples=["high"]),
    min_risk: float | None = Query(default=None, ge=0, le=100, description="Minimum risk score."),
    source_ip: str | None = Query(default=None, description="Filter by source IP."),
) -> ThreatList:
    items, total = events.get_recent_events(
        limit=pagination.page_size,
        offset=pagination.offset,
        attack_type=attack_type,
        attack_category=attack_category,
        severity=severity,
        is_attack=True,
        min_risk=min_risk,
        source_ip=source_ip,
        search=filters.search,
        since=filters.resolve_since(),
        until=filters.end_time,
    )

    alert_index = _alert_index(alerts, {str(item.get("id")) for item in items})
    threats = []
    for record in items:
        threat = _to_threat(record)
        alert = alert_index.get(str(record.get("id")))
        threat["alert_id"] = str(alert["id"]) if alert else None
        threats.append(threat)
    return ThreatList.create(threats, total, pagination.page, pagination.page_size)


@router.get(
    "/{threat_id}",
    response_model=ThreatDetail,
    summary="Threat detail",
    description=(
        "Full threat record: probability distribution, raw NSL-KDD features, "
        "model metadata, suggested playbook actions and any linked "
        "investigations."
    ),
    responses={404: {"description": "Threat not found"}},
)
async def get_threat(
    threat_id: str,
    events: EventsDep,
    alerts: AlertsDep,
    investigations: InvestigationsDep,
) -> ThreatDetail:
    record = events.get_event_by_id(threat_id)
    if record is None or not record.get("is_attack"):
        raise NotFoundError("Threat", threat_id)

    threat = _to_threat(record)
    related_alert = _alert_index(alerts, {str(threat_id)}).get(str(threat_id))
    threat["alert_id"] = str(related_alert["id"]) if related_alert else None

    linked: list[ThreatInvestigationSummary] = []
    if related_alert is not None:
        for investigation in investigations.find_by_alert(str(related_alert["id"])):
            linked.append(
                ThreatInvestigationSummary(
                    id=str(investigation["id"]),
                    title=str(investigation["title"]),
                    status=str(investigation["status"]),
                    priority=str(investigation["priority"]),
                    analyst=investigation.get("analyst"),
                    opened_at=investigation.get("opened_at"),
                )
            )

    category = str(record.get("attack_category") or "Unknown")
    description = (
        f"{record.get('attack_type')} ({category}) detected from "
        f"{record.get('source_host')} ({record.get('source_ip')}) targeting "
        f"{record.get('destination_host')}:{record.get('destination_port')} "
        f"with confidence {float(record.get('confidence') or 0.0):.2f} and "
        f"risk {float(record.get('risk_score') or 0.0):.1f} "
        f"({record.get('risk_band')})."
    )

    return ThreatDetail(
        **threat,
        probabilities=dict(record.get("probabilities") or {}),
        features=dict(record.get("features") or {}),
        model_name=record.get("model_name"),
        model_version=record.get("model_version"),
        latency_ms=record.get("latency_ms"),
        description=description,
        recommendations=list(_PLAYBOOK.get(category, _DEFAULT_PLAYBOOK)),
        investigations=linked,
    )
