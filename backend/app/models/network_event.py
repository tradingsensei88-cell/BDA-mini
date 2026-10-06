"""ORM model for ``network_events`` - raw flow-level telemetry.

Mirrors ``infrastructure/postgres/init.sql`` (section 1). ``raw_payload`` holds
the full JSON event as produced by the ingestion pipeline, so records can be
reconstructed losslessly when serving historical reads.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class NetworkEvent(Base):
    """A single raw network flow record ingested from Kafka (``network-events``)."""

    __tablename__ = "network_events"
    __table_args__ = (
        CheckConstraint(
            "source_port BETWEEN 0 AND 65535", name="ck_network_events_source_port"
        ),
        CheckConstraint(
            "destination_port BETWEEN 0 AND 65535",
            name="ck_network_events_destination_port",
        ),
        CheckConstraint("bytes_sent >= 0", name="ck_network_events_bytes_sent"),
        CheckConstraint("bytes_received >= 0", name="ck_network_events_bytes_received"),
        CheckConstraint("packets_sent >= 0", name="ck_network_events_packets_sent"),
        CheckConstraint("packets_received >= 0", name="ck_network_events_packets_received"),
        CheckConstraint("duration_ms >= 0", name="ck_network_events_duration_ms"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source_ip: Mapped[str] = mapped_column(INET, nullable=False)
    destination_ip: Mapped[str] = mapped_column(INET, nullable=False)
    source_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    destination_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    protocol: Mapped[str] = mapped_column(String(16), nullable=False, default="TCP")
    bytes_sent: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bytes_received: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    packets_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    packets_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tcp_flags: Mapped[str | None] = mapped_column(Text, nullable=True)
    flow_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sensor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    geo_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<NetworkEvent id={self.id} {self.source_ip}->{self.destination_ip} "
            f"at={self.event_time}>"
        )
