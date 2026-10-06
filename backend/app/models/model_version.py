"""ORM model for ``model_versions`` - ML model registry.

Mirrors ``infrastructure/postgres/init.sql`` (section 3).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

_STAGE_CHECK = "stage IN ('development', 'staging', 'production', 'archived')"


class ModelVersion(Base):
    """A trained model version and its evaluation metrics."""

    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint("model_name", "version", name="uq_model_versions_name_version"),
        CheckConstraint(_STAGE_CHECK, name="ck_model_versions_stage"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="development")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    hyperparameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    training_dataset: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<ModelVersion name={self.model_name!r} version={self.version!r} "
            f"stage={self.stage!r} active={self.is_active}>"
        )
