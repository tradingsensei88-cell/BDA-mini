"""Demo Data Generator.

Generates realistic NSL-KDD style security events *in-process* so the whole
platform (REST API, WebSocket feed, analytics, alerts) works standalone - no
Kafka, Spark or HDFS required. Enabled with ``DEMO_MODE=true`` (the default).

Every generated event flows through the **real** pipeline:

1. :meth:`EventProcessingService.process_incoming_event` - normalize,
   composite risk score, in-memory buffer, Redis fan-out.
2. :meth:`AlertEngine.process_event` - rule evaluation + deduplication
   (attack confidence, anomaly score, high risk, attack flood).
3. WebSocket listeners registered on the services (wired in ``main.py``).

On bootstrap the generator additionally *backfills* several thousand
events spread over the configured window (``DEMO_BACKFILL_EVENTS`` /
``DEMO_BACKFILL_HOURS``) and seeds a handful of alerts + investigations so
every dashboard has meaningful content the moment the backend starts.
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from collections import Counter, deque
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import structlog

from app.core.config import settings
from app.services.alert_engine import AlertEngine, get_alert_engine
from app.services.event_service import EventProcessingService, get_event_service
from app.services.investigation_service import (
    InvestigationService,
    get_investigation_service,
)

logger = structlog.get_logger("cybershield.backend.demo")

# ---------------------------------------------------------------------------
# NSL-KDD vocabulary & distributions
# ---------------------------------------------------------------------------

CLASS_LABELS: tuple[str, ...] = ("Normal", "DoS", "Probe", "R2L", "U2R")

#: Traffic mix (roughly the NSL-KDD KDDTest+ distribution, attacks boosted a
#: little so the demo dashboards stay interesting).
CATEGORY_WEIGHTS: list[tuple[str, float]] = [
    ("Normal", 0.56),
    ("DoS", 0.20),
    ("Probe", 0.13),
    ("R2L", 0.07),
    ("U2R", 0.04),
]

#: Fine-grained attack types per category (weighted).
ATTACK_TYPES: dict[str, list[tuple[str, float]]] = {
    "DoS": [
        ("neptune", 0.62),
        ("smurf", 0.18),
        ("back", 0.10),
        ("teardrop", 0.06),
        ("pod", 0.04),
    ],
    "Probe": [
        ("portsweep", 0.38),
        ("satan", 0.27),
        ("ipsweep", 0.24),
        ("nmap", 0.11),
    ],
    "R2L": [
        ("guess_passwd", 0.34),
        ("warezclient", 0.24),
        ("ftp_write", 0.22),
        ("imap", 0.20),
    ],
    "U2R": [
        ("buffer_overflow", 0.30),
        ("rootkit", 0.26),
        ("loadmodule", 0.24),
        ("perl", 0.20),
    ],
}

_PROTOCOL_WEIGHTS: dict[str, list[tuple[str, float]]] = {
    "Normal": [("tcp", 0.65), ("udp", 0.25), ("icmp", 0.10)],
    "DoS": [("tcp", 0.55), ("icmp", 0.30), ("udp", 0.15)],
    "Probe": [("tcp", 0.50), ("udp", 0.25), ("icmp", 0.25)],
    "R2L": [("tcp", 0.95), ("udp", 0.05)],
    "U2R": [("tcp", 0.95), ("udp", 0.05)],
}

_PROTOCOL_BY_ATTACK: dict[str, list[tuple[str, float]]] = {
    "neptune": [("tcp", 1.0)],
    "smurf": [("icmp", 0.9), ("udp", 0.1)],
    "back": [("tcp", 1.0)],
    "teardrop": [("udp", 0.7), ("tcp", 0.3)],
    "pod": [("icmp", 0.9), ("tcp", 0.1)],
}

_SERVICE_WEIGHTS: dict[str, list[tuple[str, float]]] = {
    "Normal": [
        ("http", 0.38),
        ("private", 0.14),
        ("domain_u", 0.10),
        ("smtp", 0.08),
        ("ftp_data", 0.07),
        ("ftp", 0.06),
        ("telnet", 0.05),
        ("ssh", 0.05),
        ("other", 0.07),
    ],
    "DoS": [("private", 0.55), ("http", 0.25), ("ecr_i", 0.20)],
    "Probe": [("private", 0.60), ("http", 0.20), ("other", 0.20)],
    "R2L": [("ftp_data", 0.35), ("http", 0.25), ("pop_3", 0.15), ("telnet", 0.15), ("imap", 0.10)],
    "U2R": [("telnet", 0.45), ("ftp_data", 0.25), ("http", 0.30)],
}

_SERVICE_BY_ATTACK: dict[str, list[tuple[str, float]]] = {
    "neptune": [("private", 0.75), ("http", 0.25)],
    "smurf": [("ecr_i", 1.0)],
    "back": [("http", 1.0)],
    "teardrop": [("private", 1.0)],
    "pod": [("ecr_i", 1.0)],
    "portsweep": [("private", 1.0)],
    "ipsweep": [("private", 1.0)],
    "nmap": [("private", 1.0)],
    "satan": [("http", 0.35), ("smtp", 0.2), ("ftp_data", 0.15), ("telnet", 0.15), ("private", 0.15)],
    "guess_passwd": [("pop_3", 0.35), ("ftp", 0.3), ("telnet", 0.2), ("imap", 0.15)],
    "ftp_write": [("ftp_data", 0.85), ("http", 0.15)],
    "warezclient": [("ftp_data", 0.8), ("http", 0.2)],
    "imap": [("imap", 1.0)],
    "buffer_overflow": [("telnet", 0.7), ("ftp_data", 0.3)],
    "rootkit": [("telnet", 1.0)],
    "loadmodule": [("http", 0.6), ("ftp_data", 0.4)],
    "perl": [("http", 0.6), ("ftp_data", 0.4)],
}

_FLAG_WEIGHTS: dict[str, list[tuple[str, float]]] = {
    "Normal": [("SF", 0.88), ("REJ", 0.06), ("S0", 0.04), ("RSTO", 0.02)],
    "DoS": [("S0", 0.75), ("REJ", 0.10), ("SF", 0.10), ("OTH", 0.05)],
    "Probe": [("RSTO", 0.35), ("REJ", 0.30), ("S0", 0.25), ("SF", 0.10)],
    "R2L": [("SF", 0.75), ("REJ", 0.20), ("RSTO", 0.05)],
    "U2R": [("SF", 0.70), ("REJ", 0.20), ("S0", 0.10)],
}

_SERVICE_PORTS: dict[str, int | None] = {
    "http": 80,
    "https": 443,
    "ftp": 21,
    "ftp_data": 20,
    "smtp": 25,
    "ssh": 22,
    "telnet": 23,
    "domain_u": 53,
    "pop_3": 110,
    "imap": 143,
    "private": None,
    "ecr_i": None,
    "other": None,
}

#: "Relatedness" used to distribute classifier mistakes / probabilities.
_CONFUSION_AFFINITY: dict[str, dict[str, float]] = {
    "Normal": {"DoS": 0.45, "Probe": 0.35, "R2L": 0.12, "U2R": 0.08},
    "DoS": {"Probe": 0.50, "Normal": 0.40, "R2L": 0.05, "U2R": 0.05},
    "Probe": {"DoS": 0.50, "Normal": 0.30, "R2L": 0.10, "U2R": 0.10},
    "R2L": {"Normal": 0.50, "U2R": 0.25, "Probe": 0.15, "DoS": 0.10},
    "U2R": {"R2L": 0.45, "Probe": 0.25, "Normal": 0.20, "DoS": 0.10},
}

#: Correct-prediction confidence ranges (R2L / U2R are the "hard" classes and
#: sometimes fall below the alert threshold - exactly like the real model).
_CONFIDENCE_RANGES: dict[str, tuple[float, float]] = {
    "Normal": (0.93, 0.999),
    "DoS": (0.92, 0.999),
    "Probe": (0.80, 0.99),
    "R2L": (0.58, 0.93),
    "U2R": (0.52, 0.90),
}

_TOP_FEATURES: dict[str, list[str]] = {
    "Normal": ["duration", "src_bytes", "dst_bytes"],
    "DoS": ["count", "serror_rate", "src_bytes"],
    "Probe": ["dst_host_count", "rerror_rate", "diff_srv_rate"],
    "R2L": ["num_failed_logins", "logged_in", "hot"],
    "U2R": ["root_shell", "num_root", "num_compromised"],
}

_EXTERNAL_PREFIXES: tuple[str, ...] = ("45.146", "185.220", "104.244", "89.248", "5.188", "91.240")

_SERVER_HOSTS: list[str] = [f"HOST-{index:03d}" for index in range(1, 33)]      # 172.16.0.x
_CLIENT_HOSTS: list[str] = [f"HOST-{index:03d}" for index in range(101, 165)]   # 172.16.1.x

_MODEL_NAME = "cybershield-attack-classifier"
_MODEL_VERSION = "1.0.0"

_BOOTSTRAP_SEED_MASK = 0xBACC
_FREQUENCY_CHECK_SECONDS = 5.0
_ATTACK_WINDOW_SECONDS = 60.0
_LIVE_RATE_WINDOW_SECONDS = 10.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _host_ip(host: str) -> str:
    """Deterministic IP for a ``HOST-XXX`` name (shared convention)."""

    try:
        index = int(host.split("-")[1])
        return f"172.16.{index // 64}.{index % 64 + 1}"
    except (IndexError, ValueError):
        return "172.16.0.1"


def _weighted_choice(rng: random.Random, options: list[tuple[str, float]]) -> str:
    total = sum(weight for _, weight in options)
    target = rng.random() * total
    upto = 0.0
    for value, weight in options:
        upto += weight
        if upto >= target:
            return value
    return options[-1][0]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _log_bytes(rng: random.Random, median: float, sigma: float, cap: float = 60_000.0) -> int:
    return int(_clamp(rng.lognormvariate(math.log(max(1.0, median)), sigma), 0.0, cap))


# ---------------------------------------------------------------------------
# Feature synthesis
# ---------------------------------------------------------------------------


def _generate_normal_features(rng: random.Random, protocol: str, service: str, flag: str) -> dict[str, Any]:
    duration = rng.randint(0, 60) if rng.random() < 0.85 else rng.randint(60, 1800)
    src_bytes = _log_bytes(rng, 240, 1.3)
    dst_bytes = _log_bytes(rng, 380, 1.4)
    count = rng.randint(1, 70)
    same_srv = round(_clamp(rng.uniform(0.7, 1.0), 0, 1), 2)
    return {
        "duration": duration,
        "protocol_type": protocol,
        "service": service,
        "flag": flag,
        "src_bytes": src_bytes,
        "dst_bytes": dst_bytes,
        "land": 0,
        "wrong_fragment": 0,
        "urgent": 0,
        "hot": rng.randint(1, 3) if rng.random() < 0.04 else 0,
        "num_failed_logins": rng.randint(1, 2) if rng.random() < 0.02 else 0,
        "logged_in": 1 if service in ("telnet", "ftp", "ssh", "domain_u") and rng.random() < 0.6 else 0,
        "num_compromised": 0,
        "root_shell": 0,
        "su_attempted": 0,
        "num_root": 0,
        "num_file_creations": 0,
        "num_shells": 0,
        "num_access_files": 0,
        "num_outbound_cmds": 0,
        "is_host_login": 0,
        "is_guest_login": 1 if service in ("ftp", "telnet") and rng.random() < 0.08 else 0,
        "count": count,
        "srv_count": min(255, max(1, count + rng.randint(-12, 12))),
        "serror_rate": round(rng.uniform(0.0, 0.05), 2),
        "srv_serror_rate": round(rng.uniform(0.0, 0.05), 2),
        "rerror_rate": round(rng.uniform(0.0, 0.18), 2) if rng.random() < 0.2 else 0.0,
        "srv_rerror_rate": round(rng.uniform(0.0, 0.12), 2) if rng.random() < 0.15 else 0.0,
        "same_srv_rate": same_srv,
        "diff_srv_rate": round(_clamp(1.0 - same_srv, 0.0, 0.3), 2),
        "srv_diff_host_rate": round(rng.uniform(0.0, 0.1), 2),
        "dst_host_count": rng.randint(1, 255),
        "dst_host_srv_count": rng.randint(1, 255),
        "dst_host_same_srv_rate": round(rng.uniform(0.6, 1.0), 2),
        "dst_host_diff_srv_rate": round(rng.uniform(0.0, 0.2), 2),
        "dst_host_same_src_port_rate": round(rng.uniform(0.5, 1.0), 2),
        "dst_host_srv_diff_host_rate": round(rng.uniform(0.0, 0.1), 2),
        "dst_host_serror_rate": round(rng.uniform(0.0, 0.05), 2),
        "dst_host_srv_serror_rate": round(rng.uniform(0.0, 0.05), 2),
        "dst_host_rerror_rate": round(rng.uniform(0.0, 0.15), 2),
        "dst_host_srv_rerror_rate": round(rng.uniform(0.0, 0.12), 2),
    }


def _generate_dos_features(rng: random.Random, attack_type: str, protocol: str, service: str, flag: str) -> dict[str, Any]:
    if attack_type == "smurf":
        src_bytes, count, serror = rng.randint(480, 1180), rng.randint(300, 511), 0.0
    elif attack_type == "back":
        src_bytes, count, serror = rng.randint(480, 1600), rng.randint(1, 20), round(rng.uniform(0.0, 0.05), 2)
    elif attack_type == "teardrop":
        src_bytes, count, serror = rng.randint(0, 60), rng.randint(200, 511), round(rng.uniform(0.5, 1.0), 2)
    elif attack_type == "pod":
        src_bytes, count, serror = rng.randint(0, 30), rng.randint(200, 511), 0.0
    else:  # neptune (SYN flood)
        src_bytes, count, serror = rng.randint(0, 120), rng.randint(150, 511), round(rng.uniform(0.6, 1.0), 2)

    return {
        "duration": 0 if attack_type != "back" else rng.randint(1, 12),
        "protocol_type": protocol,
        "service": service,
        "flag": flag,
        "src_bytes": src_bytes,
        "dst_bytes": 0 if attack_type != "back" else rng.randint(0, 200),
        "land": 0,
        "wrong_fragment": rng.randint(1, 5) if attack_type == "teardrop" else 0,
        "urgent": 0,
        "hot": 0,
        "num_failed_logins": 0,
        "logged_in": 0,
        "num_compromised": 0,
        "root_shell": 0,
        "su_attempted": 0,
        "num_root": 0,
        "num_file_creations": 0,
        "num_shells": 0,
        "num_access_files": 0,
        "num_outbound_cmds": 0,
        "is_host_login": 0,
        "is_guest_login": 0,
        "count": count,
        "srv_count": count,
        "serror_rate": serror,
        "srv_serror_rate": serror,
        "rerror_rate": round(rng.uniform(0.6, 1.0), 2) if attack_type == "back" else 0.0,
        "srv_rerror_rate": round(rng.uniform(0.6, 1.0), 2) if attack_type == "back" else 0.0,
        "same_srv_rate": 1.0,
        "diff_srv_rate": 0.0,
        "srv_diff_host_rate": 0.0,
        "dst_host_count": 255,
        "dst_host_srv_count": 255,
        "dst_host_same_srv_rate": 1.0,
        "dst_host_diff_srv_rate": 0.0,
        "dst_host_same_src_port_rate": 1.0 if attack_type in ("neptune", "smurf", "pod") else round(rng.uniform(0.5, 1.0), 2),
        "dst_host_srv_diff_host_rate": 0.0,
        "dst_host_serror_rate": serror,
        "dst_host_srv_serror_rate": serror,
        "dst_host_rerror_rate": round(rng.uniform(0.6, 1.0), 2) if attack_type == "back" else 0.0,
        "dst_host_srv_rerror_rate": round(rng.uniform(0.6, 1.0), 2) if attack_type == "back" else 0.0,
    }


def _generate_probe_features(rng: random.Random, attack_type: str, protocol: str, service: str, flag: str) -> dict[str, Any]:
    is_sweep = attack_type in ("portsweep", "ipsweep", "nmap")
    rerror = round(rng.uniform(0.5, 1.0), 2) if is_sweep else round(rng.uniform(0.2, 0.8), 2)
    diff_srv = round(rng.uniform(0.4, 0.9), 2) if is_sweep else round(rng.uniform(0.2, 0.6), 2)
    return {
        "duration": rng.randint(0, 10),
        "protocol_type": protocol,
        "service": service,
        "flag": flag,
        "src_bytes": rng.randint(0, 120),
        "dst_bytes": 0,
        "land": 0,
        "wrong_fragment": 0,
        "urgent": 0,
        "hot": 0,
        "num_failed_logins": 0,
        "logged_in": 0,
        "num_compromised": 0,
        "root_shell": 0,
        "su_attempted": 0,
        "num_root": 0,
        "num_file_creations": 0,
        "num_shells": 0,
        "num_access_files": 0,
        "num_outbound_cmds": 0,
        "is_host_login": 0,
        "is_guest_login": 0,
        "count": rng.randint(1, 180),
        "srv_count": rng.randint(1, 25),
        "serror_rate": round(rng.uniform(0.0, 0.4), 2),
        "srv_serror_rate": round(rng.uniform(0.0, 0.4), 2),
        "rerror_rate": rerror,
        "srv_rerror_rate": round(rerror * rng.uniform(0.4, 0.9), 2),
        "same_srv_rate": round(rng.uniform(0.02, 0.5), 2),
        "diff_srv_rate": diff_srv,
        "srv_diff_host_rate": round(rng.uniform(0.2, 0.8), 2),
        "dst_host_count": rng.randint(120, 255),
        "dst_host_srv_count": rng.randint(1, 60),
        "dst_host_same_srv_rate": round(rng.uniform(0.02, 0.5), 2),
        "dst_host_diff_srv_rate": round(rng.uniform(0.4, 0.95), 2),
        "dst_host_same_src_port_rate": round(rng.uniform(0.3, 1.0), 2),
        "dst_host_srv_diff_host_rate": round(rng.uniform(0.2, 0.8), 2),
        "dst_host_serror_rate": round(rng.uniform(0.0, 0.3), 2),
        "dst_host_srv_serror_rate": round(rng.uniform(0.0, 0.3), 2),
        "dst_host_rerror_rate": rerror,
        "dst_host_srv_rerror_rate": round(rerror * rng.uniform(0.5, 0.95), 2),
    }


def _generate_r2l_features(rng: random.Random, attack_type: str, protocol: str, service: str, flag: str) -> dict[str, Any]:
    failed_logins = rng.randint(1, 5) if attack_type == "guess_passwd" else 0
    hot = {
        "ftp_write": rng.randint(2, 8),
        "warezclient": rng.randint(1, 4),
        "guess_passwd": rng.randint(0, 2),
        "imap": rng.randint(0, 2),
    }.get(attack_type, 0)
    return {
        "duration": rng.randint(80, 2500),
        "protocol_type": protocol,
        "service": service,
        "flag": flag,
        "src_bytes": _log_bytes(rng, 700, 1.2, 30_000),
        "dst_bytes": _log_bytes(rng, 900, 1.2, 60_000),
        "land": 0,
        "wrong_fragment": 0,
        "urgent": 0,
        "hot": hot,
        "num_failed_logins": failed_logins,
        "logged_in": 1 if attack_type in ("ftp_write", "warezclient") else (1 if rng.random() < 0.3 else 0),
        "num_compromised": 0,
        "root_shell": 0,
        "su_attempted": 0,
        "num_root": 0,
        "num_file_creations": rng.randint(1, 4) if attack_type == "ftp_write" else 0,
        "num_shells": 0,
        "num_access_files": rng.randint(1, 3) if attack_type == "ftp_write" else 0,
        "num_outbound_cmds": 0,
        "is_host_login": 0,
        "is_guest_login": 1 if attack_type == "guess_passwd" and rng.random() < 0.4 else 0,
        "count": rng.randint(1, 12),
        "srv_count": rng.randint(1, 12),
        "serror_rate": round(rng.uniform(0.0, 0.1), 2),
        "srv_serror_rate": round(rng.uniform(0.0, 0.1), 2),
        "rerror_rate": round(rng.uniform(0.0, 0.3), 2),
        "srv_rerror_rate": round(rng.uniform(0.0, 0.3), 2),
        "same_srv_rate": round(rng.uniform(0.6, 1.0), 2),
        "diff_srv_rate": round(rng.uniform(0.0, 0.3), 2),
        "srv_diff_host_rate": round(rng.uniform(0.0, 0.2), 2),
        "dst_host_count": rng.randint(1, 120),
        "dst_host_srv_count": rng.randint(1, 120),
        "dst_host_same_srv_rate": round(rng.uniform(0.5, 1.0), 2),
        "dst_host_diff_srv_rate": round(rng.uniform(0.0, 0.3), 2),
        "dst_host_same_src_port_rate": round(rng.uniform(0.2, 0.9), 2),
        "dst_host_srv_diff_host_rate": round(rng.uniform(0.0, 0.2), 2),
        "dst_host_serror_rate": round(rng.uniform(0.0, 0.1), 2),
        "dst_host_srv_serror_rate": round(rng.uniform(0.0, 0.1), 2),
        "dst_host_rerror_rate": round(rng.uniform(0.0, 0.25), 2),
        "dst_host_srv_rerror_rate": round(rng.uniform(0.0, 0.25), 2),
    }


def _generate_u2r_features(rng: random.Random, attack_type: str, protocol: str, service: str, flag: str) -> dict[str, Any]:
    root = rng.random() < (0.7 if attack_type in ("rootkit", "buffer_overflow") else 0.35)
    return {
        "duration": rng.randint(200, 3200),
        "protocol_type": protocol,
        "service": service,
        "flag": flag,
        "src_bytes": _log_bytes(rng, 400, 1.5, 20_000),
        "dst_bytes": _log_bytes(rng, 300, 1.4, 20_000),
        "land": 0,
        "wrong_fragment": 0,
        "urgent": 0,
        "hot": rng.randint(10, 30),
        "num_failed_logins": rng.randint(0, 2),
        "logged_in": 1 if rng.random() < 0.7 else 0,
        "num_compromised": rng.randint(1, 15),
        "root_shell": 1 if root else 0,
        "su_attempted": rng.randint(0, 2),
        "num_root": rng.randint(0, 12) if root else 0,
        "num_file_creations": rng.randint(0, 5),
        "num_shells": rng.randint(0, 3) if root else 0,
        "num_access_files": rng.randint(0, 3),
        "num_outbound_cmds": rng.randint(0, 4) if attack_type == "rootkit" else 0,
        "is_host_login": 0,
        "is_guest_login": 0,
        "count": rng.randint(1, 10),
        "srv_count": rng.randint(1, 10),
        "serror_rate": round(rng.uniform(0.0, 0.1), 2),
        "srv_serror_rate": round(rng.uniform(0.0, 0.1), 2),
        "rerror_rate": round(rng.uniform(0.0, 0.2), 2),
        "srv_rerror_rate": round(rng.uniform(0.0, 0.2), 2),
        "same_srv_rate": round(rng.uniform(0.7, 1.0), 2),
        "diff_srv_rate": round(rng.uniform(0.0, 0.2), 2),
        "srv_diff_host_rate": round(rng.uniform(0.0, 0.2), 2),
        "dst_host_count": rng.randint(1, 60),
        "dst_host_srv_count": rng.randint(1, 60),
        "dst_host_same_srv_rate": round(rng.uniform(0.6, 1.0), 2),
        "dst_host_diff_srv_rate": round(rng.uniform(0.0, 0.2), 2),
        "dst_host_same_src_port_rate": round(rng.uniform(0.4, 1.0), 2),
        "dst_host_srv_diff_host_rate": round(rng.uniform(0.0, 0.2), 2),
        "dst_host_serror_rate": round(rng.uniform(0.0, 0.1), 2),
        "dst_host_srv_serror_rate": round(rng.uniform(0.0, 0.1), 2),
        "dst_host_rerror_rate": round(rng.uniform(0.0, 0.15), 2),
        "dst_host_srv_rerror_rate": round(rng.uniform(0.0, 0.15), 2),
    }


def _generate_features(
    rng: random.Random, category: str, attack_type: str, protocol: str, service: str, flag: str
) -> dict[str, Any]:
    if category == "DoS":
        return _generate_dos_features(rng, attack_type, protocol, service, flag)
    if category == "Probe":
        return _generate_probe_features(rng, attack_type, protocol, service, flag)
    if category == "R2L":
        return _generate_r2l_features(rng, attack_type, protocol, service, flag)
    if category == "U2R":
        return _generate_u2r_features(rng, attack_type, protocol, service, flag)
    return _generate_normal_features(rng, protocol, service, flag)


def _simulate_inference(
    rng: random.Random,
    truth: str,
    features: Mapping[str, Any],
) -> dict[str, Any]:
    """Simulate the classifier + anomaly detector output for one event."""

    predicted = truth
    if truth == "Normal":
        if rng.random() < 0.02:  # false positive
            predicted = _weighted_choice(rng, [("DoS", 0.5), ("Probe", 0.4), ("R2L", 0.1)])
    else:
        roll = rng.random()
        if roll < 0.05:  # false negative
            predicted = "Normal"
        elif roll < 0.13:  # confused attack family
            affinity = _CONFUSION_AFFINITY.get(truth, {})
            predicted = _weighted_choice(rng, list(affinity.items()) or [("Probe", 1.0)])

    if predicted == truth:
        low, high = _CONFIDENCE_RANGES.get(truth, (0.8, 0.99))
        confidence = round(rng.uniform(low, high), 4)
    else:
        confidence = round(rng.uniform(0.52, 0.78), 4)

    # -- probability vector ------------------------------------------------
    remaining = 1.0 - confidence
    affinity = dict(_CONFUSION_AFFINITY.get(truth if predicted == truth else predicted, {}))
    weights: dict[str, float] = {}
    for label in CLASS_LABELS:
        if label == predicted:
            continue
        weight = affinity.get(label, 0.06)
        if predicted != truth and label == truth:
            weight = max(weight, 0.65)  # the truth keeps most of the residual mass
        weights[label] = weight
    weight_total = sum(weights.values()) or 1.0

    probabilities: dict[str, float] = {label: 0.0 for label in CLASS_LABELS}
    for label, weight in weights.items():
        probabilities[label] = round(remaining * weight / weight_total, 4)
    probabilities[predicted] = round(confidence + (1.0 - confidence - sum(probabilities.values())), 4)

    # -- anomaly score -------------------------------------------------------
    if truth == "Normal":
        anomaly = rng.betavariate(1.2, 7.0)
    else:
        anomaly = min(1.0, 0.3 + rng.betavariate(2.5, 2.5) * 0.75)
        if rng.random() < 0.28:
            anomaly = max(anomaly, rng.uniform(0.72, 0.97))
    anomaly = round(_clamp(anomaly, 0.0, 1.0), 4)

    return {
        "predicted_category": predicted,
        "is_attack": predicted != "Normal",
        "confidence": confidence,
        "probabilities": probabilities,
        "anomaly_score": anomaly,
    }


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class DemoDataGenerator:
    """In-process NSL-KDD style traffic simulator."""

    def __init__(
        self,
        *,
        rate: int | None = None,
        seed: int | None = None,
        events: EventProcessingService | None = None,
        alerts: AlertEngine | None = None,
        investigations: InvestigationService | None = None,
    ) -> None:
        self.events = events or get_event_service()
        self.alerts = alerts or get_alert_engine()
        self.investigations = investigations or get_investigation_service()

        self.rate = max(1, int(rate if rate is not None else settings.demo_event_rate))
        self.seed = seed if seed is not None else settings.demo_seed
        self._rng = random.Random(self.seed)

        # -- state -------------------------------------------------------------
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._paused = False
        self._pause_gate = asyncio.Event()
        self._pause_gate.set()
        self._bootstrapped = False
        self._bootstrap_lock = asyncio.Lock()

        # -- stats -------------------------------------------------------------
        self.total_events = 0
        self.backfilled_events = 0
        self.alerts_generated = 0
        self.anomalies_detected = 0
        self.category_breakdown: Counter[str] = Counter()
        self.started_at: datetime | None = None
        self.last_event_at: datetime | None = None
        self._seen_alert_ids: set[str] = set()

        # -- live analysis windows -----------------------------------------------
        self._emit_marks: deque[float] = deque()
        self._attack_marks: deque[float] = deque(maxlen=10_000)
        self._host_marks: dict[str, deque[float]] = {}
        self._last_frequency_check = 0.0

        # -- burst state ---------------------------------------------------------
        self._burst: dict[str, Any] | None = None
        self._next_burst_mono = time.monotonic() + self._rng.uniform(45.0, 90.0)

        # -- external IP pool (deterministic) --------------------------------------
        pool_rng = random.Random(self.seed ^ 0xE47)
        self._external_ips = [
            f"{pool_rng.choice(_EXTERNAL_PREFIXES)}.{pool_rng.randint(1, 254)}.{pool_rng.randint(1, 254)}"
            for _ in range(24)
        ]

        self.alerts.register_listener(self._on_alert)

    # ------------------------------------------------------------ properties

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def paused(self) -> bool:
        return self.running and self._paused

    # ------------------------------------------------------------- lifecycle

    async def bootstrap(self, *, seed_investigations: bool = True) -> dict[str, Any]:
        """One-time startup: backfill history + seed alerts & investigations."""

        if self._bootstrapped:
            return self.get_status()
        async with self._bootstrap_lock:
            if self._bootstrapped:
                return self.get_status()
            await self._backfill()
            seeded = await self._seed_alerts()
            if seed_investigations and seeded:
                top = sorted(
                    seeded, key=lambda alert: float(alert.get("risk_score") or 0.0), reverse=True
                )
                try:
                    await self.investigations.seed_demo(top, count=6)
                except Exception as exc:  # noqa: BLE001 - seeding is best-effort
                    logger.warning("demo.investigation_seed_failed", error=str(exc))
            self._bootstrapped = True
            logger.info(
                "demo.bootstrap_complete",
                backfilled=self.backfilled_events,
                seeded_alerts=len(seeded),
            )
            return self.get_status()

    async def start(self) -> dict[str, Any]:
        """Start (or resume) the background emission loop."""

        if self._task is not None and not self._task.done():
            self.resume()
            return self.get_status()

        self._stopping = False
        self._paused = False
        self._pause_gate.set()
        if self.started_at is None:
            self.started_at = _utc_now()
        self._task = asyncio.create_task(self._run(), name="cybershield-demo-generator")
        logger.info("demo.started", rate=self.rate, seed=self.seed)
        return self.get_status()

    async def stop(self) -> None:
        """Cancel the emission loop (used by reset/shutdown)."""

        task, self._task = self._task, None
        self._stopping = True
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
        self._stopping = False

    def pause(self) -> None:
        """Suspend emission (the task stays alive)."""

        self._paused = True
        self._pause_gate.clear()
        logger.info("demo.paused")

    def resume(self) -> None:
        """Resume emission after :meth:`pause`."""

        self._paused = False
        self._pause_gate.set()
        logger.info("demo.resumed")

    def set_rate(self, rate: int) -> None:
        """Change the emission rate (events/second); applied on the next tick."""

        if rate < 1 or rate > 10_000:
            raise ValueError("rate must be between 1 and 10000")
        self.rate = int(rate)
        logger.info("demo.rate_changed", rate=self.rate)

    def reset(self) -> None:
        """Zero all simulation statistics (platform state is untouched)."""

        self.total_events = 0
        self.backfilled_events = 0
        self.alerts_generated = 0
        self.anomalies_detected = 0
        self.category_breakdown.clear()
        self._seen_alert_ids.clear()
        self._emit_marks.clear()
        self._attack_marks.clear()
        self._host_marks.clear()
        self._burst = None
        self._next_burst_mono = time.monotonic() + self._rng.uniform(30.0, 60.0)
        self.started_at = None
        self.last_event_at = None
        logger.info("demo.reset")

    # ---------------------------------------------------------------- status

    def get_status(self) -> dict[str, Any]:
        """Simulation status payload (matches ``schemas.simulation.SimulationStatus``)."""

        alive = self.running
        paused = self.paused
        state = "paused" if paused else ("running" if alive else "stopped")
        uptime = (
            max(0.001, (_utc_now() - self.started_at).total_seconds())
            if alive and self.started_at is not None
            else 0.0
        )
        return {
            "state": state,
            "running": alive,
            "paused": paused,
            "rate": self.rate,
            "events_per_sec": self._live_rate(),
            "avg_events_per_sec": (
                round(self.total_events / uptime, 2) if uptime > 0 else 0.0
            ),
            "total_events": self.total_events,
            "alerts_generated": self.alerts_generated,
            "anomalies_detected": self.anomalies_detected,
            "category_breakdown": dict(self.category_breakdown),
            "source": "demo",
            "demo_mode": settings.demo_mode,
            "started_at": _iso(self.started_at),
            "uptime_seconds": round(uptime, 1),
            "last_event_at": _iso(self.last_event_at),
            "message": {
                "running": "Simulation is running.",
                "paused": "Simulation is paused.",
                "stopped": "Simulation is stopped.",
            }[state],
        }

    # ------------------------------------------------------------- emission

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await self._pause_gate.wait()
                started = time.monotonic()
                await self._emit_one()
                interval = (1.0 / self.rate) * self._rng.uniform(0.72, 1.35)
                elapsed = time.monotonic() - started
                await asyncio.sleep(max(0.0005, interval - elapsed))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - loop must never die
                logger.warning("demo.emit_failed", error=str(exc))
                await asyncio.sleep(0.5)

    async def _emit_one(self) -> None:
        now_mono = time.monotonic()
        now = _utc_now()

        override = self._maybe_burst(now_mono)
        event = self._build_event(self._rng, now, override=override)
        if override is not None and self._burst is not None:
            self._burst["remaining"] -= 1

        host = str(event["source_host"])
        event["event_frequency"] = float(self._attack_rate_for_host(host, now_mono))

        record = await self.events.process_incoming_event(event)

        # The rate mark is recorded *after* the frequency lookup so an event
        # never inflates its own frequency component.
        if record.get("is_attack"):
            self._attack_marks.append(now_mono)
            marks = self._host_marks.setdefault(host, deque(maxlen=500))
            marks.append(now_mono)
            if len(self._host_marks) > 600:
                for key in [k for k, v in self._host_marks.items() if not v]:
                    self._host_marks.pop(key, None)

        anomaly = float(record.get("anomaly_score") or 0.0)
        if anomaly >= self.alerts.thresholds.anomaly_score:
            self.anomalies_detected += 1

        await self._evaluate_alerts(record)

        self.total_events += 1
        self.category_breakdown[str(record.get("predicted_category") or "Normal")] += 1
        self.last_event_at = now

        marks = self._emit_marks
        marks.append(now_mono)
        cutoff = now_mono - _LIVE_RATE_WINDOW_SECONDS
        while marks and marks[0] < cutoff:
            marks.popleft()

        if now_mono - self._last_frequency_check >= _FREQUENCY_CHECK_SECONDS:
            self._last_frequency_check = now_mono
            await self._frequency_check(now_mono)

    async def _evaluate_alerts(self, record: Mapping[str, Any]) -> None:
        try:
            alert = await self.alerts.process_event(record)
            if alert is None and float(record.get("anomaly_score") or 0.0) >= self.alerts.thresholds.anomaly_score:
                top_features = list(record.get("top_features") or [])
                features = dict(record.get("features") or {})
                await self.alerts.process_anomaly(
                    {
                        "id": record.get("id"),
                        "anomaly_score": record.get("anomaly_score"),
                        "source_host": record.get("source_host"),
                        "source_ip": record.get("source_ip"),
                        "destination_host": record.get("destination_host"),
                        "attack_category": record.get("attack_category"),
                        "method": "isolation_forest",
                        "features": {name: features.get(name) for name in top_features},
                    }
                )
        except Exception as exc:  # noqa: BLE001 - alerting is best-effort
            logger.debug("demo.alert_eval_failed", error=str(exc))

    async def _frequency_check(self, now_mono: float) -> None:
        """Raise a flood alert when the rolling attack rate crosses the threshold."""

        cutoff = now_mono - _ATTACK_WINDOW_SECONDS
        marks = self._attack_marks
        while marks and marks[0] < cutoff:
            marks.popleft()
        if not marks:
            return
        try:
            await self.alerts.process_frequency(len(marks))
        except Exception as exc:  # noqa: BLE001
            logger.debug("demo.frequency_check_failed", error=str(exc))

    def _maybe_burst(self, now_mono: float) -> dict[str, Any] | None:
        """Occasionally concentrate traffic from one host (attack burst)."""

        burst = self._burst
        if burst is not None:
            if burst["remaining"] <= 0:
                self._burst = None
                self._next_burst_mono = now_mono + self._rng.uniform(60.0, 150.0)
                return None
            return burst if self._rng.random() < 0.8 else None

        if now_mono >= self._next_burst_mono:
            category = _weighted_choice(self._rng, [("DoS", 0.5), ("Probe", 0.35), ("R2L", 0.15)])
            host = self._rng.choice(_CLIENT_HOSTS)
            attack_type = _weighted_choice(self._rng, ATTACK_TYPES[category])
            self._burst = {
                "category": category,
                "attack_type": attack_type,
                "source_host": host,
                "source_ip": _host_ip(host),
                "remaining": self._rng.randint(25, 70),
            }
            logger.info(
                "demo.burst_started",
                category=category,
                attack_type=attack_type,
                source_host=host,
            )
            return self._burst
        return None

    def _live_rate(self) -> float:
        now = time.monotonic()
        cutoff = now - _LIVE_RATE_WINDOW_SECONDS
        marks = self._emit_marks
        while marks and marks[0] < cutoff:
            marks.popleft()
        if not marks:
            return 0.0
        elapsed = max(1.0, now - marks[0])
        return round(len(marks) / elapsed, 2)

    def _attack_rate_for_host(self, host: str, now_mono: float) -> int:
        marks = self._host_marks.get(host)
        if not marks:
            return 0
        cutoff = now_mono - _ATTACK_WINDOW_SECONDS
        while marks and marks[0] < cutoff:
            marks.popleft()
        return len(marks)

    # ---------------------------------------------------------- event build

    def _build_event(
        self,
        rng: random.Random,
        timestamp: datetime,
        *,
        override: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Assemble one raw event payload (consumed by ``event_service``)."""

        if override is not None:
            category = str(override["category"])
            attack_type = str(override["attack_type"])
            source_host = str(override["source_host"])
            source_ip = str(override["source_ip"])
        else:
            category = _weighted_choice(rng, CATEGORY_WEIGHTS)
            attack_type = (
                "normal" if category == "Normal" else _weighted_choice(rng, ATTACK_TYPES[category])
            )
            if category == "Normal":
                source_host = rng.choice(_CLIENT_HOSTS)
                source_ip = _host_ip(source_host)
            else:
                external = rng.random() < 0.45
                if external:
                    source_ip = rng.choice(self._external_ips)
                    source_host = f"EXT-{source_ip.replace('.', '-')}"
                else:
                    source_host = rng.choice(_CLIENT_HOSTS)
                    source_ip = _host_ip(source_host)

        destination_host = rng.choice(_SERVER_HOSTS)
        destination_ip = _host_ip(destination_host)

        protocol = _weighted_choice(
            rng, _PROTOCOL_BY_ATTACK.get(attack_type, _PROTOCOL_WEIGHTS[category])
        )
        service = _weighted_choice(
            rng, _SERVICE_BY_ATTACK.get(attack_type, _SERVICE_WEIGHTS[category])
        )
        flag = _weighted_choice(rng, _FLAG_WEIGHTS[category])

        features = _generate_features(rng, category, attack_type, protocol, service, flag)
        inference = _simulate_inference(rng, category, features)

        src_bytes = int(features["src_bytes"])
        dst_bytes = int(features["dst_bytes"])
        packets_sent = max(1, src_bytes // rng.randint(300, 900) + rng.randint(0, 3))
        packets_received = max(0, dst_bytes // rng.randint(300, 900) + rng.randint(0, 2))

        destination_port = _SERVICE_PORTS.get(service)
        if destination_port is None:
            destination_port = (
                rng.randint(1024, 65535) if protocol == "tcp" else rng.randint(1, 65535)
            )
        source_port = 0 if protocol == "icmp" else rng.randint(1024, 65535)

        latency = rng.uniform(2.5, 24.0)
        if rng.random() < 0.04:
            latency = rng.uniform(30.0, 65.0)

        top_features = list(_TOP_FEATURES.get(category, _TOP_FEATURES["Normal"]))
        rng.shuffle(top_features)

        return {
            "timestamp": _iso(timestamp),
            "source_host": source_host,
            "source_ip": source_ip,
            "destination_host": destination_host,
            "destination_ip": destination_ip,
            "source_port": source_port,
            "destination_port": destination_port,
            "protocol": protocol.upper(),
            "service": service,
            "flag": flag,
            "duration": int(features["duration"]),
            "src_bytes": src_bytes,
            "dst_bytes": dst_bytes,
            "packets_sent": packets_sent,
            "packets_received": packets_received,
            "attack_type": attack_type,
            "attack_category": category,
            "predicted_category": inference["predicted_category"],
            "is_attack": inference["is_attack"],
            "confidence": inference["confidence"],
            "probabilities": inference["probabilities"],
            "anomaly_score": inference["anomaly_score"],
            "model_name": _MODEL_NAME,
            "model_version": _MODEL_VERSION,
            "latency_ms": round(latency, 2),
            "top_features": top_features[:3],
            "features": features,
        }

    # -------------------------------------------------------------- seeding

    async def _backfill(self) -> None:
        """Populate the platform with historical events (no alert fan-out)."""

        count = max(0, int(settings.demo_backfill_events))
        hours = max(1, int(settings.demo_backfill_hours))
        if count == 0:
            return

        rng = random.Random(self.seed ^ _BOOTSTRAP_SEED_MASK)
        now = _utc_now()
        span_seconds = hours * 3600.0

        events: list[dict[str, Any]] = []
        for _ in range(count):
            # Bias toward recent history so the 1h/24h dashboards are rich.
            offset = (rng.random() ** 1.5) * span_seconds
            events.append(self._build_event(rng, now - timedelta(seconds=offset)))
        events.sort(key=lambda item: str(item["timestamp"]))

        for payload in events:
            try:
                await self.events.process_incoming_event(
                    payload, notify=False, publish=False, persist=False
                )
                self.backfilled_events += 1
                self.total_events += 1
                self.category_breakdown[str(payload.get("predicted_category") or "Normal")] += 1
                if float(payload.get("anomaly_score") or 0.0) >= self.alerts.thresholds.anomaly_score:
                    self.anomalies_detected += 1
            except Exception as exc:  # noqa: BLE001 - partial backfill is acceptable
                logger.debug("demo.backfill_event_failed", error=str(exc))
        logger.info("demo.backfill_complete", events=self.backfilled_events, hours=hours)

    async def _seed_alerts(self) -> list[dict[str, Any]]:
        """Promote a sample of backfilled attacks into realistic alerts."""

        buffer = list(self.events.buffer)
        attacks = [record for record in buffer if record.get("is_attack")]
        if not attacks:
            return []

        rng = random.Random(self.seed ^ 0xA1E47)
        step = max(1, len(attacks) // 48)
        sample = attacks[::step][:48]
        rng.shuffle(sample)

        created: dict[str, dict[str, Any]] = {}
        for record in sample:
            try:
                alert = await self.alerts.process_event(record)
                if alert is None and float(record.get("anomaly_score") or 0.0) >= self.alerts.thresholds.anomaly_score:
                    alert = await self.alerts.process_anomaly(
                        {
                            "id": record.get("id"),
                            "anomaly_score": record.get("anomaly_score"),
                            "source_host": record.get("source_host"),
                            "source_ip": record.get("source_ip"),
                            "destination_host": record.get("destination_host"),
                            "attack_category": record.get("attack_category"),
                            "method": "isolation_forest",
                            "features": {},
                        }
                    )
                if alert is not None:
                    created[str(alert["id"])] = alert
            except Exception as exc:  # noqa: BLE001
                logger.debug("demo.seed_alert_failed", error=str(exc))

        # Spread the seeded alerts across the lifecycle so the SOC views show
        # (and filter by) every status.
        lifecycle = ("open", "acknowledged", "investigating", "resolved", "false_positive")
        for index, alert_id in enumerate(created):
            status = lifecycle[(index * 2 + 1) % len(lifecycle)]
            if status == "open":
                continue
            try:
                await self.alerts.update_alert_status(
                    alert_id,
                    status,
                    assigned_to=f"analyst-{(index % 4) + 1}" if status != "false_positive" else None,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("demo.seed_status_failed", error=str(exc))

        logger.info("demo.alerts_seeded", alerts=len(created))
        return list(created.values())

    # ------------------------------------------------------------- listeners

    async def _on_alert(self, alert: dict[str, Any], event: str) -> None:
        """Track DISTINCT alerts (new ids only) for the status payload."""

        if event != "new":
            return
        alert_id = str(alert.get("id") or "")
        if alert_id and alert_id not in self._seen_alert_ids:
            self._seen_alert_ids.add(alert_id)
            self.alerts_generated += 1
            if len(self._seen_alert_ids) > 5000:
                self._seen_alert_ids = set(list(self._seen_alert_ids)[-2500:])


#: Shared generator instance (bootstrapped/started by the app lifespan).
demo_generator = DemoDataGenerator()


def get_demo_generator() -> DemoDataGenerator:
    """FastAPI-friendly accessor for the shared generator."""

    return demo_generator
