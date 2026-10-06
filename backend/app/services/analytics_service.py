"""Analytics Service.

Aggregates the event stream into chart-ready payloads:

* **Attack distribution** - donut slices per NSL-KDD category.
* **Timeline** - stacked events-over-time buckets (normal/DoS/Probe/R2L/U2R).
* **Top sources** - noisiest / riskiest source hosts.
* **Heatmap** - threat intensity per source host x hour x severity.
* **Protocol distribution** - TCP / UDP / ICMP split with attack rates.

Long windows are served from per-minute buckets maintained by
:class:`~app.services.event_service.EventProcessingService`, so the numbers
stay accurate even when the in-memory event ring has rolled over.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from app.schemas.common import (
    TIME_RANGE_SECONDS,
    TimeRange,
    parse_time_range,
    window_started_at,
)
from app.services.event_service import EventProcessingService, get_event_service
from app.services.risk_scoring import get_risk_engine

logger = structlog.get_logger("cybershield.backend.analytics")

#: Category -> chart color (consistent across the dashboard).
CATEGORY_COLORS: dict[str, str] = {
    "Normal": "#22c55e",
    "DoS": "#ef4444",
    "Probe": "#f59e0b",
    "R2L": "#a855f7",
    "U2R": "#ec4899",
    "Unknown": "#64748b",
}

#: Category order used in responses.
CATEGORY_ORDER = ("Normal", "DoS", "Probe", "R2L", "U2R", "Unknown")

#: Seconds per timeline bucket, chosen per window (~12-28 points).
_TIMELINE_BUCKET_SECONDS: dict[TimeRange, int] = {
    TimeRange.M15: 60,
    TimeRange.H1: 300,
    TimeRange.H6: 900,
    TimeRange.H24: 3600,
    TimeRange.D7: 6 * 3600,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_label(moment: datetime, window: TimeRange) -> str:
    if window is TimeRange.D7:
        return moment.strftime("%d %b %H:%M")
    return moment.strftime("%H:%M")


class AnalyticsService:
    """Builds every analytics payload from the shared event buffer/buckets."""

    def __init__(self, events: EventProcessingService | None = None) -> None:
        self.events = events or get_event_service()

    # ------------------------------------------------------ 1. distribution

    def attack_distribution(
        self, window: str | TimeRange = TimeRange.H24
    ) -> dict[str, Any]:
        """Donut-chart data: counts + percentages per attack category."""

        resolved = _resolve_window(window)
        since = window_started_at(resolved)

        totals: Counter[str] = Counter()
        for minute, counts in self.events.get_minute_buckets(since):
            totals.update(counts)

        total = sum(totals.values())
        items: list[dict[str, Any]] = []
        for category in CATEGORY_ORDER:
            count = int(totals.get(category, 0))
            if count == 0 and category == "Unknown":
                continue
            items.append(
                {
                    "category": category,
                    "label": category,
                    "count": count,
                    "percentage": round(count / total * 100.0, 2) if total else 0.0,
                    "color": CATEGORY_COLORS.get(category, CATEGORY_COLORS["Unknown"]),
                    "severity_weight": get_risk_engine().severity_weight(category),
                }
            )

        return {
            "window": resolved.value,
            "total": total,
            "items": items,
            "generated_at": _utc_now().isoformat(),
        }

    # ---------------------------------------------------------- 2. timeline

    def timeline(self, window: str | TimeRange = TimeRange.H24) -> dict[str, Any]:
        """Stacked events-over-time buckets for the area chart."""

        resolved = _resolve_window(window)
        now = _utc_now()
        since = window_started_at(resolved, now)
        bucket_seconds = _TIMELINE_BUCKET_SECONDS[resolved]

        index_counts: dict[int, Counter[str]] = defaultdict(Counter)
        for minute, counts in self.events.get_minute_buckets(since):
            offset = int((minute - since).total_seconds() // bucket_seconds)
            index_counts[offset].update(counts)

        bucket_count = max(1, int(TIME_RANGE_SECONDS[resolved] // bucket_seconds))
        points: list[dict[str, Any]] = []
        for index in range(bucket_count):
            bucket_start = since + timedelta(seconds=index * bucket_seconds)
            counts = index_counts.get(index, Counter())
            point = {
                "time": bucket_start.isoformat(),
                "label": _format_label(bucket_start, resolved),
                "normal": int(counts.get("Normal", 0)),
                "dos": int(counts.get("DoS", 0)),
                "probe": int(counts.get("Probe", 0)),
                "r2l": int(counts.get("R2L", 0)),
                "u2r": int(counts.get("U2R", 0)),
            }
            point["total"] = (
                point["normal"] + point["dos"] + point["probe"] + point["r2l"] + point["u2r"]
            )
            points.append(point)

        return {
            "window": resolved.value,
            "bucket_seconds": bucket_seconds,
            "points": points,
            "generated_at": _utc_now().isoformat(),
        }

    # -------------------------------------------------------- 3. top sources

    def top_sources(
        self, window: str | TimeRange = TimeRange.H24, *, limit: int = 10
    ) -> dict[str, Any]:
        """Ranked noisiest source hosts (threats first, then mean risk)."""

        resolved = _resolve_window(window)
        since = window_started_at(resolved)

        aggregates: dict[str, dict[str, Any]] = {}
        for record in self.events.get_events_since(since):
            source_ip = str(record.get("source_ip") or "0.0.0.0")
            entry = aggregates.get(source_ip)
            if entry is None:
                entry = {
                    "source_ip": source_ip,
                    "source_host": str(record.get("source_host") or source_ip),
                    "events": 0,
                    "threats": 0,
                    "normal": 0,
                    "risk_sum": 0.0,
                    "max_risk_score": 0.0,
                    "attack_types": Counter(),
                    "categories": Counter(),
                    "first_seen": record.get("timestamp"),
                    "last_seen": record.get("timestamp"),
                }
                aggregates[source_ip] = entry

            entry["events"] += 1
            if record.get("is_attack"):
                entry["threats"] += 1
                entry["attack_types"][str(record.get("attack_type") or "unknown")] += 1
                entry["categories"][str(record.get("attack_category") or "Unknown")] += 1
            else:
                entry["normal"] += 1
            risk = float(record.get("risk_score") or 0.0)
            entry["risk_sum"] += risk
            entry["max_risk_score"] = max(entry["max_risk_score"], risk)
            # Records arrive oldest-first from get_events_since.
            entry["last_seen"] = record.get("timestamp") or entry["last_seen"]

        items: list[dict[str, Any]] = []
        for entry in aggregates.values():
            top_attack = (
                entry["attack_types"].most_common(1)[0][0] if entry["attack_types"] else "normal"
            )
            top_category = (
                entry["categories"].most_common(1)[0][0] if entry["categories"] else "Normal"
            )
            items.append(
                {
                    "source_ip": entry["source_ip"],
                    "source_host": entry["source_host"],
                    "events": entry["events"],
                    "threats": entry["threats"],
                    "normal": entry["normal"],
                    "risk_score": round(entry["risk_sum"] / entry["events"], 2)
                    if entry["events"]
                    else 0.0,
                    "max_risk_score": round(entry["max_risk_score"], 2),
                    "top_attack": top_attack,
                    "attack_category": top_category,
                    "first_seen": entry["first_seen"],
                    "last_seen": entry["last_seen"],
                }
            )

        items.sort(key=lambda item: (item["threats"], item["max_risk_score"]), reverse=True)
        return {
            "window": resolved.value,
            "items": items[: max(1, limit)],
            "generated_at": _utc_now().isoformat(),
        }

    # ------------------------------------------------------------ 4. heatmap

    def heatmap(
        self,
        window: str | TimeRange = TimeRange.H24,
        *,
        max_hosts: int = 12,
    ) -> dict[str, Any]:
        """Threat heatmap: source host x hour cells + severity totals."""

        resolved = _resolve_window(window)
        now = _utc_now()
        since = window_started_at(resolved, now)

        hour_starts: list[datetime] = []
        cursor = since.replace(minute=0, second=0, microsecond=0)
        while cursor <= now:
            hour_starts.append(cursor)
            cursor += timedelta(hours=1)
        if not hour_starts:
            hour_starts = [now.replace(minute=0, second=0, microsecond=0)]
        hour_index = {hour: index for index, hour in enumerate(hour_starts)}

        host_cells: dict[str, list[int]] = {}
        for (hour, host), count in self.events.get_hourly_host_heat(since).items():
            index = hour_index.get(hour)
            if index is None:
                continue
            cells = host_cells.setdefault(host, [0] * len(hour_starts))
            cells[index] += int(count)

        severity_totals: Counter[str] = Counter()
        for _, counts in self.events.get_hourly_severity(since).items():
            severity_totals.update(counts)

        ranked_hosts = sorted(host_cells.items(), key=lambda kv: sum(kv[1]), reverse=True)[
            : max(1, max_hosts)
        ]
        rows = [
            {
                "host": host,
                "source_ip": _host_to_ip(host),
                "cells": cells,
                "total": sum(cells),
            }
            for host, cells in ranked_hosts
        ]

        return {
            "window": resolved.value,
            "hours": [hour.strftime("%H:%M") for hour in hour_starts],
            "rows": rows,
            "severity_totals": dict(severity_totals),
            "max_value": max((max(cells) for _, cells in ranked_hosts), default=0),
            "generated_at": now.isoformat(),
        }

    # ---------------------------------------------- 5. protocol distribution

    def protocol_distribution(
        self, window: str | TimeRange = TimeRange.H24
    ) -> dict[str, Any]:
        """TCP / UDP / ICMP split with normal vs attack counts."""

        resolved = _resolve_window(window)
        since = window_started_at(resolved)

        buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"normal": 0, "attacks": 0})
        for record in self.events.get_events_since(since):
            protocol = str(record.get("protocol") or "TCP").upper()
            if protocol not in ("TCP", "UDP", "ICMP"):
                protocol = "TCP"
            if record.get("is_attack"):
                buckets[protocol]["attacks"] += 1
            else:
                buckets[protocol]["normal"] += 1

        items: list[dict[str, Any]] = []
        for protocol in ("TCP", "UDP", "ICMP"):
            data = buckets.get(protocol, {"normal": 0, "attacks": 0})
            total = data["normal"] + data["attacks"]
            items.append(
                {
                    "protocol": protocol,
                    "normal": data["normal"],
                    "attacks": data["attacks"],
                    "total": total,
                    "attack_rate": round(data["attacks"] / total * 100.0, 2) if total else 0.0,
                }
            )

        return {
            "window": resolved.value,
            "items": items,
            "generated_at": _utc_now().isoformat(),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_window(window: str | TimeRange) -> TimeRange:
    if isinstance(window, TimeRange):
        return window
    return parse_time_range(window)


def _host_to_ip(host: str) -> str:
    """Reverse of the demo host->IP convention (HOST-014 -> 172.16.0.15)."""

    if host.startswith("HOST-"):
        try:
            index = int(host.split("-")[1])
            return f"172.16.{index // 64}.{index % 64 + 1}"
        except (IndexError, ValueError):
            pass
    return "0.0.0.0"


#: Shared service instance.
analytics_service = AnalyticsService()


def get_analytics_service() -> AnalyticsService:
    """FastAPI-friendly accessor for the shared service."""

    return analytics_service
