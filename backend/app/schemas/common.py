"""Shared schema primitives: pagination, filters, sorting, errors.

All models are Pydantic v2 with field descriptions and validation so they
render a helpful OpenAPI schema at ``/docs``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from math import ceil
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T")


class SortOrder(str, Enum):
    """Sort direction for list endpoints."""

    ASC = "asc"
    DESC = "desc"


class TimeRange(str, Enum):
    """Preset time windows accepted by analytics endpoints."""

    M15 = "15m"
    H1 = "1h"
    H6 = "6h"
    H24 = "24h"
    D7 = "7d"


#: Seconds covered by each preset window.
TIME_RANGE_SECONDS: dict[TimeRange, int] = {
    TimeRange.M15: 15 * 60,
    TimeRange.H1: 60 * 60,
    TimeRange.H6: 6 * 60 * 60,
    TimeRange.H24: 24 * 60 * 60,
    TimeRange.D7: 7 * 24 * 60 * 60,
}


def parse_time_range(value: str | None, default: TimeRange = TimeRange.H24) -> TimeRange:
    """Normalise a free-form ``window``/``time_range`` string to a preset.

    Accepts presets (``1h``, ``24h``, ``7d``, ...) and common aliases
    (``hour``, ``day``, ``week``). Unknown values fall back to ``default``.
    """

    if not value:
        return default
    normalized = value.strip().lower()
    aliases = {
        "15m": TimeRange.M15,
        "15min": TimeRange.M15,
        "1h": TimeRange.H1,
        "hour": TimeRange.H1,
        "60m": TimeRange.H1,
        "6h": TimeRange.H6,
        "24h": TimeRange.H24,
        "day": TimeRange.H24,
        "1d": TimeRange.H24,
        "7d": TimeRange.D7,
        "week": TimeRange.D7,
        "168h": TimeRange.D7,
    }
    return aliases.get(normalized, default)


def window_started_at(window: TimeRange, now: datetime | None = None) -> datetime:
    """UTC datetime marking the start of ``window``."""

    reference = now or datetime.now(timezone.utc)
    return reference - timedelta(seconds=TIME_RANGE_SECONDS[window])


class PaginationParams(BaseModel):
    """Standard pagination query parameters."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1, description="1-based page number.", examples=[1])
    page_size: int = Field(
        default=25,
        ge=1,
        le=200,
        description="Items per page (max 200).",
        examples=[25],
    )

    @property
    def offset(self) -> int:
        """Zero-based offset for slicing."""
        return (self.page - 1) * self.page_size


class SortParams(BaseModel):
    """Standard sorting query parameters."""

    sort_by: str = Field(default="timestamp", description="Field to sort by.", examples=["timestamp"])
    sort_order: SortOrder = Field(default=SortOrder.DESC, description="Sort direction.")


class FilterParams(BaseModel):
    """Common filters shared by event/threat/alert list endpoints."""

    search: str | None = Field(
        default=None,
        max_length=128,
        description="Free-text search across hosts, IPs and attack types.",
        examples=["172.16"],
    )
    time_range: str | None = Field(
        default=None,
        description="Preset window: 15m / 1h / 6h / 24h / 7d.",
        examples=["24h"],
    )
    start_time: datetime | None = Field(default=None, description="Inclusive lower bound (UTC).")
    end_time: datetime | None = Field(default=None, description="Inclusive upper bound (UTC).")

    @field_validator("start_time", "end_time", mode="after")
    @classmethod
    def _ensure_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            return value.replace(tzinfo=timezone.utc)
        return value

    def resolve_since(self, default: TimeRange | None = None) -> datetime | None:
        """Resolve the effective lower bound from ``start_time``/``time_range``."""

        if self.start_time is not None:
            return self.start_time
        if self.time_range:
            return window_started_at(parse_time_range(self.time_range))
        if default is not None:
            return window_started_at(default)
        return None


class PaginatedResponse(BaseModel, Generic[T]):
    """Envelope for every paginated list endpoint."""

    items: list[T] = Field(default_factory=list, description="Page of results.")
    total: int = Field(ge=0, description="Total matching records.", examples=[137])
    page: int = Field(ge=1, description="Current 1-based page.", examples=[1])
    page_size: int = Field(ge=1, description="Items per page.", examples=[25])
    pages: int = Field(ge=0, description="Total number of pages.", examples=[6])
    has_next: bool = Field(description="Whether another page exists.")
    has_prev: bool = Field(description="Whether a previous page exists.")

    @classmethod
    def create(
        cls,
        items: list[T],
        total: int,
        page: int,
        page_size: int,
    ) -> "PaginatedResponse[T]":
        """Build a well-formed page envelope from ``items`` + ``total``."""

        pages = ceil(total / page_size) if page_size > 0 else 0
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
            has_next=page < pages,
            has_prev=page > 1,
        )


class ErrorDetail(BaseModel):
    """Machine-readable error payload returned by the exception handlers."""

    code: int = Field(description="HTTP status code.", examples=[404])
    message: str = Field(description="Human-readable error message.", examples=["Event not found"])
    detail: object | None = Field(default=None, description="Optional structured detail.")


class ErrorResponse(BaseModel):
    """Top-level error envelope."""

    error: ErrorDetail
    request_id: str | None = Field(default=None, description="Correlation id of the request.")
