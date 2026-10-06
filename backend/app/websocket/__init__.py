"""WebSocket layer for live security-event streaming to the SOC dashboard.

Exports the connection manager, the ``/ws/security-events`` router and
the background streamer that bridges Redis pub/sub (or the in-process
fallback) to connected clients.
"""

from app.websocket.event_streamer import EventStreamer, get_event_streamer
from app.websocket.handler import router
from app.websocket.manager import (
    MESSAGE_TYPES,
    Connection,
    ConnectionManager,
    get_ws_manager,
    ws_manager,
)

__all__ = [
    "MESSAGE_TYPES",
    "Connection",
    "ConnectionManager",
    "EventStreamer",
    "get_event_streamer",
    "get_ws_manager",
    "router",
    "ws_manager",
]
