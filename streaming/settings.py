"""CyberShield AI - environment-driven settings shared by streaming + ML scripts.

This module is intentionally dependency-light (standard library only, with an
*optional* ``python-dotenv`` integration). Every producer, consumer, Spark job
and ML script in the repository reads its configuration through these helpers
so that a single ``.env`` file at the project root configures the whole stack.

Environment variables (see ``.env.example``):

* ``KAFKA_BOOTSTRAP_SERVERS`` - broker list used inside the Docker network
  (``kafka:9092``). Scripts executed on the host machine should use
  ``localhost:29092`` (the external listener), which is the default here.
* ``DATABASE_URL`` - PostgreSQL DSN. The default targets the host-exposed
  ``localhost:5432``; inside Docker Compose the ``postgres`` hostname is used.
* ``LOG_LEVEL`` / ``LOG_FORMAT`` - structured logging controls consumed by
  :mod:`streaming.logging_config`.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Project layout
# ---------------------------------------------------------------------------

#: Absolute path of the ``cybershield-ai`` repository root (this file lives in
#: ``<root>/streaming/settings.py``).
PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]

#: Default location of the raw datasets shipped with the project.
DATA_RAW_DIR: Path = PROJECT_ROOT / "data" / "raw"

#: Default location of the processed Parquet artifacts.
DATA_PROCESSED_DIR: Path = PROJECT_ROOT / "data" / "processed"

# ---------------------------------------------------------------------------
# Defaults (host-machine friendly; Docker Compose overrides via .env)
# ---------------------------------------------------------------------------

DEFAULT_KAFKA_BOOTSTRAP_SERVERS = "localhost:29092"
DEFAULT_DATABASE_URL = (
    "postgresql://cybershield:cybershield_secret@localhost:5432/cybershield"
)
DEFAULT_CONSUMER_GROUP = "cybershield-event-consumer"

_env_loaded = False


def load_env(env_file: Path | str | None = None, *, override: bool = False) -> Path | None:
    """Load variables from a ``.env`` file (idempotent, best-effort).

    Uses ``python-dotenv`` when installed; silently degrades to a no-op when
    the dependency or the file is missing so that scripts never fail just
    because a convenience file is absent.

    Args:
        env_file: Explicit ``.env`` path. Defaults to ``<project root>/.env``.
        override: When ``True``, values from the file override existing
            environment variables.

    Returns:
        The path of the loaded file, or ``None`` if nothing was loaded.
    """

    global _env_loaded

    candidate = Path(env_file) if env_file else PROJECT_ROOT / ".env"
    if not candidate.is_file():
        return None
    if _env_loaded and not override:
        return candidate

    try:
        from dotenv import load_dotenv  # optional dependency
    except ImportError:  # pragma: no cover - depends on local install
        return None

    load_dotenv(candidate, override=override)
    _env_loaded = True
    return candidate


def env(name: str, default: str | None = None) -> str | None:
    """Return an environment variable, loading ``.env`` lazily on first use."""

    load_env()
    return os.getenv(name, default)


# ---------------------------------------------------------------------------
# Typed accessors
# ---------------------------------------------------------------------------


def kafka_bootstrap_servers(default: str = DEFAULT_KAFKA_BOOTSTRAP_SERVERS) -> str:
    """Kafka bootstrap servers for host-run clients (``host:port`` list)."""

    return env("KAFKA_BOOTSTRAP_SERVERS", default) or default


def database_url(default: str = DEFAULT_DATABASE_URL) -> str:
    """PostgreSQL DSN used by the consumers/ML jobs to persist results."""

    return env("DATABASE_URL", default) or default


def kafka_network_events_topic(default: str = "network-events") -> str:
    """Topic carrying raw NSL-KDD style network events."""

    return env("KAFKA_NETWORK_EVENTS_TOPIC", default) or default


def consumer_group(default: str = DEFAULT_CONSUMER_GROUP) -> str:
    """Kafka consumer group id used when none is supplied explicitly."""

    return env("KAFKA_CONSUMER_GROUP", default) or default


def data_raw_dir() -> Path:
    """Directory holding the raw NSL-KDD files (``data/raw``)."""

    return Path(env("DATA_RAW_DIR", str(DATA_RAW_DIR)) or DATA_RAW_DIR)


def data_processed_dir() -> Path:
    """Directory holding processed Parquet artifacts (``data/processed``)."""

    return Path(env("DATA_PROCESSED_DIR", str(DATA_PROCESSED_DIR)) or DATA_PROCESSED_DIR)


def resolve_dataset_path(explicit: str | Path | None = None) -> Path:
    """Resolve the NSL-KDD dataset file to use.

    Resolution order:

    1. ``explicit`` argument (CLI ``--dataset`` flag).
    2. ``NSLKDD_DATASET_PATH`` environment variable.
    3. ``data/raw/KDDTrain+.txt`` (full dataset, if downloaded).
    4. ``data/raw/KDDTrain+.csv``.
    5. ``data/raw/sample_data.csv`` (bundled test sample).

    Raises:
        FileNotFoundError: When no candidate exists.
    """

    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    else:
        env_path = env("NSLKDD_DATASET_PATH")
        if env_path:
            candidates.append(Path(env_path))
        raw = data_raw_dir()
        candidates.extend(
            [
                raw / "KDDTrain+.txt",
                raw / "KDDTrain+.csv",
                raw / "sample_data.csv",
            ]
        )

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    searched = "\n  - ".join(str(c) for c in candidates)
    raise FileNotFoundError(
        "No NSL-KDD dataset found. Searched:\n  - "
        f"{searched}\n"
        "Run `python data/download_dataset.py` to fetch the dataset or create "
        "the bundled sample, or pass --dataset <path> explicitly."
    )
