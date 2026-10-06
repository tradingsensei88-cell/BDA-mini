"""WebSocket endpoint for the real-time security feed.

``WS /ws/security-events`` is the single feed consumed by the dashboard:

* on connect the client receives a ``snapshot`` with the current system
  state (metrics, active alert count, recent events/alerts, simulation);
* afterwards the streamer pushes ``security_event``, ``alert``,
  ``anomaly``, ``metric_update`` and ``system_health`` messages;
* clients may send ``{"type": "subscribe", "topics": [...]}`` (or
  ``unsubscribe``) to narrow the feed, and ``ping``/``pong`` for
  liveness — the server also pings every heartbeat interval.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Iterable

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.services.alert_engine import get_alert_engine
from app.services.event_service import get_event_service
from app.services.simulation_service import get_simulation_service
from app.websocket.manager import MESSAGE_TYPES, Connection, close_socket, get_ws_manager

logger = structlog.get_logger("cybershield.backend.websocket.handler")

router = APIRouter(tags=["websocket"])

#: Client -> server control message types.
_CLIENT_TYPES: tuple[str, ...] = ("ping", "pong", "subscribe", "unsubscribe", "snapshot", "get_snapshot")

#: Keys accepted when a client sends new subscriptions.
_TOPIC_KEYS: tuple[str, ...] = ("topics", "types", "message_types", "events")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_snapshot(connection: Connection | None = None) -> dict[str, Any]:
    """Current system state payload (sent on connect and on demand)."""

    events = get_event_service()
    alerts = get_alert_engine()
    recent_events, _ = events.get_recent_events(limit=settings.ws_replay_limit)
    recent_alerts, _ = alerts.list_alerts(limit=10)
    return {
        "server_time": _now_iso(),
        "metrics": events.get_metrics(),
        "active_alerts": alerts.get_active_alert_count(),
        "recent_alerts": recent_alerts,
        "recent_events": recent_events,
        "simulation": get_simulation_service().get_status(),
        "demo_mode": settings.demo_mode,
        "heartbeat_seconds": settings.ws_heartbeat_seconds,
        "message_types": list(MESSAGE_TYPES),
        "subscriptions": connection.subscription_list() if connection else list(MESSAGE_TYPES),
    }


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
@router.websocket(settings.ws_channel)
async def security_events_feed(websocket: WebSocket) -> None:
    """Main real-time feed consumed by the dashboard."""

    manager = get_ws_manager()
    client = websocket.client.host if websocket.client else "unknown"
    connection = await manager.connect(websocket, client=client)

    if not await manager.send_message(connection, "snapshot", build_snapshot(connection)):
        return

    reader = asyncio.create_task(_client_reader(connection), name=f"ws-reader-{connection.id}")
    heartbeat = asyncio.create_task(_heartbeat_loop(connection), name=f"ws-heartbeat-{connection.id}")
    try:
        await asyncio.wait({reader, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (reader, heartbeat):
            task.cancel()
        await asyncio.gather(reader, heartbeat, return_exceptions=True)
        await manager.disconnect(connection.id)
        await close_socket(websocket)
        logger.info("ws.session_closed", connection_id=connection.id, client=client)


# ---------------------------------------------------------------------------
# Client -> server
# ---------------------------------------------------------------------------
async def _client_reader(connection: Connection) -> None:
    """Read control messages until the client disconnects."""

    try:
        while True:
            raw = await connection.websocket.receive_text()
            connection.touch()
            await _handle_client_message(connection, raw)
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001 - socket-level errors end the session
        logger.debug("ws.reader_stopped", connection_id=connection.id, error=str(exc))


def _extract_topics(payload: dict[str, Any]) -> list[str]:
    """Collect topic names from any of the accepted payload keys."""

    topics: list[str] = []
    for key in _TOPIC_KEYS:
        value = payload.get(key)
        if value is None:
            continue
        candidates: Iterable[Any] = value if isinstance(value, (list, tuple, set)) else [value]
        for item in candidates:
            for part in str(item).split(","):
                name = part.strip().lower()
                if name and name not in topics:
                    topics.append(name)
    return topics


async def _handle_client_message(connection: Connection, raw: str) -> None:
    """Process one control message from a client."""

    manager = get_ws_manager()
    try:
        payload: Any = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        await manager.send_message(
            connection,
            "error",
            {"message": "Invalid JSON payload.", "supported_types": list(_CLIENT_TYPES)},
        )
        return
    if isinstance(payload, str):
        payload = {"type": payload}
    if not isinstance(payload, dict):
        await manager.send_message(connection, "error", {"message": "Expected a JSON object."})
        return

    message_type = str(payload.get("type") or payload.get("action") or "").strip().lower()

    if message_type == "ping":
        await manager.send_message(connection, "pong", {"server_time": _now_iso()})
        return
    if message_type == "pong":
        connection.touch()
        return
    if message_type == "subscribe":
        topics = _extract_topics(payload)
        applied, ignored = manager.set_subscriptions(connection, topics)
        await manager.send_message(
            connection,
            "subscribed",
            {
                "topics": connection.subscription_list(),
                "requested": applied if applied else list(MESSAGE_TYPES),
                "ignored": ignored,
                "server_time": _now_iso(),
            },
        )
        return
    if message_type == "unsubscribe":
        topics = _extract_topics(payload)
        if not topics:
            await manager.send_message(
                connection, "error", {"message": "Provide 'topics' to unsubscribe from."}
            )
            return
        remaining = manager.remove_subscriptions(connection, topics)
        await manager.send_message(
            connection,
            "unsubscribed",
            {"topics": remaining, "removed": topics, "server_time": _now_iso()},
        )
        return
    if message_type in ("snapshot", "get_snapshot"):
        await manager.send_message(connection, "snapshot", build_snapshot(connection))
        return

    await manager.send_message(
        connection,
        "error",
        {
            "message": f"Unsupported message type: {message_type or '<missing>'}.",
            "supported_types": list(_CLIENT_TYPES),
            "broadcast_types": list(MESSAGE_TYPES),
        },
    )


# ---------------------------------------------------------------------------
# Server -> client heartbeat
# ---------------------------------------------------------------------------
async def _heartbeat_loop(connection: Connection) -> None:
    """Ping the client every ``settings.ws_heartbeat_seconds`` until failure."""

    manager = get_ws_manager()
    interval = max(5.0, float(settings.ws_heartbeat_seconds or 30.0))
    while True:
        await asyncio.sleep(interval)
        ok = await manager.send_message(
            connection,
            "ping",
            {
                "server_time": _now_iso(),
                "interval_seconds": interval,
                "active_connections": manager.active_count,
            },
        )
        if not ok:
            return
