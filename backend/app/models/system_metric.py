"""ORM model for ``system_metrics`` - platform health time-series.

Mirrors ``infrastructure/postgres/init.sql`` (section 8). The primary key is a
``BIGINT GENERATED ALWAYS AS IDENTITY`` column.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Identity, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SystemMetric(Base):
    """One time-series sample emitted by a platform component."""

    __tablename__ = "system_metrics"

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    component: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(128), nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    labels: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<SystemMetric {self.component}.{self.metric_name}={self.metric_value} "
            f"at={self.recorded_at}>"
        )
