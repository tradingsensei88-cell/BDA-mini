"""WebSocket connection manager.

Tracks active browser connections, keeps per-connection subscription
filters, and fans out JSON envelopes of the shape::

    {"type": "...", "data": {...}, "timestamp": "..."}

Message types broadcast to clients::

    security_event, alert, anomaly, metric_update, system_health

The manager is fully defensive: a failed send marks the connection as
dead and removes it, so one broken client can never break the fan-out
for everybody else.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

import structlog
from fastapi import WebSocket
from starlette.websockets import WebSocketState

from app.core.config import settings

logger = structlog.get_logger("cybershield.backend.websocket")

#: Message types that can be broadcast / subscribed to.
MESSAGE_TYPES: tuple[str, ...] = (
    "security_event",
    "alert",
    "anomaly",
    "metric_update",
    "system_health",
)

#: Server -> client informational types (always delivered, not subscribable).
INFO_TYPES: tuple[str, ...] = (
    "snapshot",
    "subscribed",
    "unsubscribed",
    "ping",
    "pong",
    "error",
)


def _iso(epoch: float | None = None) -> str:
    """UTC ISO-8601 timestamp for a unix epoch (defaults to now)."""

    moment = epoch if epoch is not None else time.time()
    return datetime.fromtimestamp(moment, tz=timezone.utc).isoformat()


def _json_safe(payload: Any) -> Any:
    """Round-trip ``payload`` through JSON so ``send_json`` never chokes."""

    try:
        return json.loads(json.dumps(payload, default=str))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return {"raw": str(payload)}


@dataclass
class Connection:
    """State for one connected WebSocket client."""

    id: str
    websocket: WebSocket
    client: str = "anonymous"
    connected_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    #: ``None`` means "subscribed to everything".
    subscriptions: set[str] | None = None
    messages_sent: int = 0
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def touch(self) -> None:
        self.last_activity = time.time()

    def wants(self, message_type: str) -> bool:
        """Whether this client should receive ``message_type``."""

        if self.subscriptions is None:
            return message_type in MESSAGE_TYPES
        return message_type in self.subscriptions

    def subscription_list(self) -> list[str]:
        """Sorted subscription list (all types when unfiltered)."""

        if self.subscriptions is None:
            return list(MESSAGE_TYPES)
        return sorted(self.subscriptions)

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "client": self.client,
            "connected_at": _iso(self.connected_at),
            "last_activity": _iso(self.last_activity),
            "subscriptions": "all" if self.subscriptions is None else sorted(self.subscriptions),
            "messages_sent": self.messages_sent,
        }


class ConnectionManager:
    """Tracks clients and fans out broadcast messages."""

    def __init__(self) -> None:
        self._connections: dict[str, Connection] = {}
        self._lock = asyncio.Lock()
        self._started_at = time.time()
        self.total_connections = 0
        self.total_disconnects = 0
        self.messages_broadcast = 0
        self.messages_sent = 0
        self.send_errors = 0

    # ------------------------------------------------------------- lifecycle

    async def connect(self, websocket: WebSocket, *, client: str = "anonymous") -> Connection:
        """Accept the handshake and register the client."""

        await websocket.accept()
        connection = Connection(id=uuid.uuid4().hex[:12], websocket=websocket, client=client)
        async with self._lock:
            self._connections[connection.id] = connection
            self.total_connections += 1
        logger.info(
            "ws.connected",
            connection_id=connection.id,
            client=client,
            active=len(self._connections),
        )
        return connection

    async def disconnect(self, connection_id: str, *, close: bool = False) -> None:
        """Remove a client; optionally close the socket if still open."""

        async with self._lock:
            connection = self._connections.pop(connection_id, None)
            if connection is None:
                return
            self.total_disconnects += 1
            active = len(self._connections)
        if close:
            await close_socket(connection.websocket)
        logger.info("ws.disconnected", connection_id=connection_id, active=active)

    def get(self, connection_id: str) -> Connection | None:
        """Look up a connection by id."""

        return self._connections.get(connection_id)

    def active_connections(self) -> list[Connection]:
        """Snapshot of all registered connections."""

        return list(self._connections.values())

    @property
    def active_count(self) -> int:
        """Number of currently connected clients."""

        return len(self._connections)

    # --------------------------------------------------------- subscriptions

    def set_subscriptions(self, connection: Connection, types: Iterable[Any]) -> tuple[list[str], list[str]]:
        """Replace the subscription filter.

        Returns ``(applied, ignored)`` — ``ignored`` lists unknown types.
        An empty request resets the client back to "everything".
        """

        applied: list[str] = []
        ignored: list[str] = []
        for raw in types:
            value = str(raw).strip().lower()
            if not value:
                continue
            if value in MESSAGE_TYPES:
                if value not in applied:
                    applied.append(value)
            else:
                ignored.append(value)
        connection.subscriptions = set(applied) if applied else None
        connection.touch()
        return applied, ignored

    def remove_subscriptions(self, connection: Connection, types: Iterable[Any]) -> list[str]:
        """Remove message types from the filter; returns the remaining list."""

        current = (
            set(connection.subscriptions)
            if connection.subscriptions is not None
            else set(MESSAGE_TYPES)
        )
        for raw in types:
            current.discard(str(raw).strip().lower())
        connection.subscriptions = current
        connection.touch()
        return sorted(current)

    # ---------------------------------------------------------------- send

    @staticmethod
    def build_message(message_type: str, data: Any, *, timestamp: float | None = None) -> dict[str, Any]:
        """Build the wire envelope for one message."""

        return {
            "type": message_type,
            "data": _json_safe(data),
            "timestamp": _iso(timestamp),
        }

    async def _send_envelope(self, connection: Connection, envelope: dict[str, Any]) -> bool:
        """Low-level send; drops the connection when the socket misbehaves."""

        try:
            async with connection.send_lock:
                if connection.websocket.client_state is WebSocketState.DISCONNECTED:
                    raise RuntimeError("WebSocket is disconnected")
                await connection.websocket.send_json(envelope)
            connection.messages_sent += 1
            connection.touch()
            self.messages_sent += 1
            return True
        except Exception as exc:  # noqa: BLE001 - any failure kills this client
            self.send_errors += 1
            logger.debug("ws.send_failed", connection_id=connection.id, error=str(exc))
            await self.disconnect(connection.id, close=True)
            return False

    async def send_message(self, connection: Connection, message_type: str, data: Any) -> bool:
        """Send one envelope to one client (used for snapshot/ping/pong)."""

        envelope = self.build_message(message_type, data)
        return await self._send_envelope(connection, envelope)

    async def broadcast(self, message_type: str, data: Any) -> int:
        """Fan out to every subscribed client; returns the delivery count."""

        recipients = [c for c in self.active_connections() if c.wants(message_type)]
        if not recipients:
            return 0
        envelope = self.build_message(message_type, data)
        delivered = 0
        for connection in recipients:
            if await self._send_envelope(connection, envelope):
                delivered += 1
        self.messages_broadcast += 1
        if message_type not in ("metric_update", "system_health"):
            logger.debug(
                "ws.broadcast",
                type=message_type,
                recipients=len(recipients),
                delivered=delivered,
            )
        return delivered

    # --------------------------------------------------------------- stats

    def stats(self) -> dict[str, Any]:
        """Diagnostics snapshot (consumed by the system health service)."""

        active = self.active_connections()
        per_type = {message_type: 0 for message_type in MESSAGE_TYPES}
        for connection in active:
            for message_type in connection.subscription_list():
                if message_type in per_type:
                    per_type[message_type] += 1
        oldest = min((c.connected_at for c in active), default=None)
        return {
            "active_connections": len(active),
            "total_connections": self.total_connections,
            "total_disconnects": self.total_disconnects,
            "messages_broadcast": self.messages_broadcast,
            "messages_sent": self.messages_sent,
            "send_errors": self.send_errors,
            "subscriptions": per_type,
            "uptime_seconds": round(time.time() - self._started_at, 1),
            "oldest_connection_at": _iso(oldest) if oldest is not None else None,
            "heartbeat_seconds": settings.ws_heartbeat_seconds,
            "clients": [connection.describe() for connection in active],
        }


async def close_socket(websocket: WebSocket) -> None:
    """Close a socket quietly (never raises)."""

    try:
        if websocket.client_state is WebSocketState.CONNECTED:
            await websocket.close(code=1000)
    except Exception:  # noqa: BLE001 - already gone
        pass


#: Shared manager instance.
ws_manager = ConnectionManager()


def get_ws_manager() -> ConnectionManager:
    """FastAPI-friendly accessor for the shared connection manager."""

    return ws_manager
