"""CyberShield AI - NSL-KDD dataset downloader + sample generator.

Downloads the benchmark files into ``data/raw/``:

* ``KDDTrain+.txt``  - https://raw.githubusercontent.com/defcom17/NSL_KDD/master/KDDTrain%2B.txt
* ``KDDTest+.txt``   - https://raw.githubusercontent.com/defcom17/NSL_KDD/master/KDDTest%2B.txt

and always ensures ``data/raw/sample_data.csv`` exists: a small (~50 record)
representative mixture of normal traffic and all five attack families, usable
for tests and demos without the full benchmark.

This script intentionally depends on the **standard library only**, so it can
run before ``pip install -r`` has been executed::

    python data/download_dataset.py                # download everything + sample
    python data/download_dataset.py --sample-only  # create just the sample file
    python data/download_dataset.py --force        # re-download / regenerate

The generated CSV is in the exact raw NSL-KDD layout (43 comma separated
columns) plus a header row, which the dataset adapter auto-detects.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "raw"

TRAIN_URL = "https://raw.githubusercontent.com/defcom17/NSL_KDD/master/KDDTrain%2B.txt"
TEST_URL = "https://raw.githubusercontent.com/defcom17/NSL_KDD/master/KDDTest%2B.txt"

USER_AGENT = "CyberShieldAI-DatasetDownloader/1.0"

#: Raw NSL-KDD files contain 43 comma-separated columns (41 features + labels).
EXPECTED_COLUMNS = 43
MIN_VALID_LINES = 100
MIN_VALID_BYTES = 50_000

# NOTE: keep in sync with streaming/schemas/event_schema.py (the runtime source
# of truth). Duplicated here so this script stays free of third-party imports.
COLUMN_NAMES: tuple[str, ...] = (
    "duration",
    "protocol_type",
    "service",
    "flag",
    "src_bytes",
    "dst_bytes",
    "land",
    "wrong_fragment",
    "urgent",
    "hot",
    "num_failed_logins",
    "logged_in",
    "num_compromised",
    "root_shell",
    "su_attempted",
    "num_root",
    "num_file_creations",
    "num_shells",
    "num_access_files",
    "num_outbound_cmds",
    "is_host_login",
    "is_guest_login",
    "count",
    "srv_count",
    "serror_rate",
    "srv_serror_rate",
    "rerror_rate",
    "srv_rerror_rate",
    "same_srv_rate",
    "diff_srv_rate",
    "srv_diff_host_rate",
    "dst_host_count",
    "dst_host_srv_count",
    "dst_host_same_srv_rate",
    "dst_host_diff_srv_rate",
    "dst_host_same_src_port_rate",
    "dst_host_srv_diff_host_rate",
    "dst_host_serror_rate",
    "dst_host_srv_serror_rate",
    "dst_host_rerror_rate",
    "dst_host_srv_rerror_rate",
    "attack_type",
    "difficulty_level",
)


# ---------------------------------------------------------------------------
# Logging (structlog when available, stdlib otherwise)
# ---------------------------------------------------------------------------

try:  # pragma: no cover - depends on local install
    from streaming.logging_config import get_logger

    _STRUCTLOG_LOGGER: Any = get_logger(__name__)

    def _log(level: str, event: str, **context: Any) -> None:
        getattr(_STRUCTLOG_LOGGER, level)(event, **context)

except ImportError:  # pragma: no cover - bare-python fallback
    import logging

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    _STDLIB_LOGGER = logging.getLogger("download_dataset")

    def _log(level: str, event: str, **context: Any) -> None:
        message = event + (" " + str(context) if context else "")
        getattr(_STDLIB_LOGGER, level if level != "warn" else "warning")(message)


# ---------------------------------------------------------------------------
# Synthetic sample generation (stdlib only)
# ---------------------------------------------------------------------------

#: Curated attack types (subset of the full 39) with their super-category.
_SAMPLE_ATTACK_CATEGORIES: dict[str, str] = {
    "normal": "Normal",
    # DoS
    "neptune": "DoS",
    "smurf": "DoS",
    "teardrop": "DoS",
    "back": "DoS",
    "pod": "DoS",
    # Probe
    "portsweep": "Probe",
    "ipsweep": "Probe",
    "nmap": "Probe",
    "satan": "Probe",
    # R2L
    "guess_passwd": "R2L",
    "warezclient": "R2L",
    "ftp_write": "R2L",
    "multihop": "R2L",
    "phf": "R2L",
    # U2R
    "buffer_overflow": "U2R",
    "rootkit": "U2R",
    "perl": "U2R",
    "loadmodule": "U2R",
}

#: Target mixture for the 50-record sample (adjusted to sum to the request).
_SAMPLE_QUOTAS: dict[str, float] = {
    "Normal": 0.44,
    "DoS": 0.20,
    "Probe": 0.12,
    "R2L": 0.14,
    "U2R": 0.10,
}

_FEATURE_DEFAULTS: dict[str, Any] = {
    "duration": 0,
    "protocol_type": "tcp",
    "service": "http",
    "flag": "SF",
    "src_bytes": 0,
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
    "count": 0,
    "srv_count": 0,
    "serror_rate": 0.0,
    "srv_serror_rate": 0.0,
    "rerror_rate": 0.0,
    "srv_rerror_rate": 0.0,
    "same_srv_rate": 0.0,
    "diff_srv_rate": 0.0,
    "srv_diff_host_rate": 0.0,
    "dst_host_count": 0,
    "dst_host_srv_count": 0,
    "dst_host_same_srv_rate": 0.0,
    "dst_host_diff_srv_rate": 0.0,
    "dst_host_same_src_port_rate": 0.0,
    "dst_host_srv_diff_host_rate": 0.0,
    "dst_host_serror_rate": 0.0,
    "dst_host_srv_serror_rate": 0.0,
    "dst_host_rerror_rate": 0.0,
    "dst_host_srv_rerror_rate": 0.0,
}
assert len(_FEATURE_DEFAULTS) == 41, "feature defaults must cover all 41 NSL-KDD features"

#: Sensible per-category feature templates (values/ranges follow the
#: statistical profiles observed in KDDTrain+ for each attack family).
_CATEGORY_BASES: dict[str, dict[str, Any]] = {
    "Normal": {
        "duration": (0, 120),
        "src_bytes": (200, 6000),
        "dst_bytes": (200, 8000),
        "hot": (0, 2),
        "logged_in": 1,
        "count": (1, 30),
        "srv_count": (1, 15),
        "same_srv_rate": (0.9, 1.0),
        "srv_diff_host_rate": (0.0, 0.1),
        "dst_host_count": (1, 60),
        "dst_host_srv_count": (1, 40),
        "dst_host_same_srv_rate": (0.85, 1.0),
        "dst_host_diff_srv_rate": (0.0, 0.1),
        "dst_host_same_src_port_rate": (0.3, 1.0),
    },
    "DoS": {
        "service": "private",
        "flag": "S0",
        "logged_in": 0,
        "count": (200, 511),
        "srv_count": (200, 511),
        "serror_rate": 1.0,
        "srv_serror_rate": 1.0,
        "same_srv_rate": 1.0,
        "dst_host_count": 255,
        "dst_host_srv_count": 255,
        "dst_host_same_srv_rate": 1.0,
        "dst_host_serror_rate": 1.0,
        "dst_host_srv_serror_rate": 1.0,
    },
    "Probe": {
        "service": "private",
        "flag": "REJ",
        "src_bytes": (0, 200),
        "logged_in": 0,
        "count": (100, 500),
        "srv_count": (1, 60),
        "rerror_rate": (0.5, 1.0),
        "srv_rerror_rate": (0.5, 1.0),
        "same_srv_rate": (0.1, 0.5),
        "diff_srv_rate": (0.5, 1.0),
        "srv_diff_host_rate": (0.0, 0.3),
        "dst_host_count": (150, 255),
        "dst_host_srv_count": (1, 100),
        "dst_host_same_srv_rate": (0.1, 0.6),
        "dst_host_diff_srv_rate": (0.4, 1.0),
        "dst_host_same_src_port_rate": (0.0, 0.3),
        "dst_host_srv_diff_host_rate": (0.0, 0.3),
        "dst_host_rerror_rate": (0.5, 1.0),
    },
    "R2L": {
        "service": "ftp",
        "src_bytes": (10, 400),
        "dst_bytes": (10, 500),
        "logged_in": 0,
        "count": (1, 40),
        "srv_count": (1, 20),
        "same_srv_rate": (0.7, 1.0),
        "dst_host_count": (1, 80),
        "dst_host_srv_count": (1, 60),
        "dst_host_same_srv_rate": (0.6, 1.0),
    },
    "U2R": {
        "service": "telnet",
        "src_bytes": (100, 3000),
        "dst_bytes": (100, 4000),
        "hot": (1, 4),
        "logged_in": 1,
        "num_compromised": (0, 3),
        "root_shell": (0, 1),
        "su_attempted": (0, 1),
        "num_root": (0, 3),
        "num_file_creations": (0, 2),
        "num_shells": (0, 1),
        "count": (1, 30),
        "srv_count": (1, 15),
    },
}

#: Per-attack refinements applied on top of the category template.
_TYPE_OVERRIDES: dict[str, dict[str, Any]] = {
    "neptune": {
        "flag": "S0",
        "src_bytes": 0,
        "dst_bytes": 0,
        "dst_host_serror_rate": 1.0,
    },
    "smurf": {
        "protocol_type": "icmp",
        "service": "ecr_i",
        "src_bytes": (0, 1032),
        "dst_host_srv_count": 255,
    },
    "teardrop": {"protocol_type": "udp", "wrong_fragment": (1, 3)},
    "back": {"flag": "SF", "src_bytes": (0, 600), "logged_in": 0},
    "pod": {"protocol_type": "icmp", "service": "ecr_i"},
    "ipsweep": {"protocol_type": "icmp", "service": "ecr_i"},
    "portsweep": {"flag": "REJ", "rerror_rate": (0.5, 1.0)},
    "nmap": {"flag": "SF", "srv_diff_host_rate": (0.5, 1.0)},
    "satan": {"service": "http", "diff_srv_rate": 1.0, "dst_host_diff_srv_rate": 1.0},
    "guess_passwd": {"service": "ftp", "num_failed_logins": (1, 5)},
    "warezclient": {"service": "ftp_data", "logged_in": 1, "src_bytes": (100, 2000)},
    "ftp_write": {"service": "ftp", "logged_in": 1, "dst_bytes": (1000, 8000)},
    "multihop": {"service": "private", "hot": (1, 2), "logged_in": 1},
    "phf": {"service": "http", "hot": (1, 2)},
    "buffer_overflow": {
        "service": "telnet",
        "hot": (2, 4),
        "root_shell": 1,
        "num_root": (1, 5),
        "num_compromised": (1, 5),
    },
    "loadmodule": {"service": "ftp_data", "hot": (1, 4), "num_root": (0, 3)},
    "rootkit": {"num_root": (1, 5), "num_file_creations": (1, 3)},
    "perl": {"su_attempted": 1},
}


def _sample_value(rng: random.Random, spec: Any) -> Any:
    """Resolve a profile spec: scalar -> constant, ``(lo, hi)`` -> random draw."""

    if isinstance(spec, tuple):
        low, high = spec
        if isinstance(low, int) and isinstance(high, int):
            return rng.randint(low, high)
        return round(rng.uniform(float(low), float(high)), 2)
    return spec


def _build_sample_row(rng: random.Random, attack_type: str) -> list[Any]:
    """Create one synthetic raw-format row for ``attack_type``."""

    category = _SAMPLE_ATTACK_CATEGORIES[attack_type]
    values: dict[str, Any] = dict(_FEATURE_DEFAULTS)
    for field, spec in _CATEGORY_BASES[category].items():
        values[field] = _sample_value(rng, spec)
    for field, spec in _TYPE_OVERRIDES.get(attack_type, {}).items():
        values[field] = _sample_value(rng, spec)

    row = [values[field] for field in COLUMN_NAMES[:-2]]
    row.append(attack_type)
    row.append(rng.randint(1, 21))  # difficulty_level as in the benchmark
    return row


def _build_sample_plan(records: int, rng: random.Random) -> list[str]:
    """Mix attack types so all five categories are represented."""

    counts: dict[str, int] = {
        category: int(round(records * quota))
        for category, quota in _SAMPLE_QUOTAS.items()
    }
    # Correct rounding drift on the Normal bucket so the total is exact.
    drift = records - sum(counts.values())
    counts["Normal"] += drift

    plan: list[str] = []
    for category, count in counts.items():
        types = [t for t, c in _SAMPLE_ATTACK_CATEGORIES.items() if c == category]
        for index in range(max(0, count)):
            plan.append(types[index % len(types)])
    rng.shuffle(plan)
    return plan


def generate_sample_rows(records: int = 50, seed: int = 42) -> list[list[Any]]:
    """Generate ``records`` representative raw NSL-KDD rows (no header)."""

    rng = random.Random(seed)
    plan = _build_sample_plan(records, rng)
    return [_build_sample_row(rng, attack_type) for attack_type in plan]


def write_sample_csv(
    destination: Path,
    *,
    records: int = 50,
    seed: int = 42,
    force: bool = False,
) -> Path:
    """Write ``sample_data.csv`` (header + ~50 mixed records) when missing."""

    destination = Path(destination)
    if destination.exists() and not force:
        _log("info", "sample_already_present", path=str(destination))
        return destination

    rows = generate_sample_rows(records=records, seed=seed)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMN_NAMES)
        writer.writerows(rows)
    _log("info", "sample_written", path=str(destination), records=len(rows))
    return destination


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def _validate_nsl_kdd_file(path: Path) -> None:
    """Assert that ``path`` looks like a non-truncated raw NSL-KDD file."""

    size = path.stat().st_size
    if size < MIN_VALID_BYTES:
        raise RuntimeError(f"{path.name} is suspiciously small ({size} bytes)")

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        first_line = handle.readline()
        if not first_line:
            raise RuntimeError(f"{path.name} is empty")
        column_count = len(first_line.rstrip("\r\n").split(","))
        if column_count != EXPECTED_COLUMNS:
            raise RuntimeError(
                f"{path.name} has {column_count} columns on line 1, "
                f"expected {EXPECTED_COLUMNS}"
            )
        line_count = 1
        for _ in handle:
            line_count += 1
            if line_count >= MIN_VALID_LINES:
                break
    if line_count < MIN_VALID_LINES:
        raise RuntimeError(f"{path.name} has fewer than {MIN_VALID_LINES} rows")


def download_file(
    url: str,
    destination: Path,
    *,
    timeout: float = 120.0,
    retries: int = 3,
    chunk_size: int = 1 << 20,
) -> Path:
    """Stream ``url`` into ``destination`` with retries and validation.

    The download lands in a ``.part`` file first and is renamed into place
    only after validation, so an interrupted run never leaves a corrupt
    dataset behind.
    """

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".part")

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            downloaded = 0
            started = time.monotonic()
            with urllib.request.urlopen(request, timeout=timeout) as response, temp_path.open(
                "wb"
            ) as handle:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if downloaded // (10 * chunk_size) != (downloaded - len(chunk)) // (
                        10 * chunk_size
                    ):
                        elapsed = max(0.001, time.monotonic() - started)
                        _log(
                            "info",
                            "download_progress",
                            file=destination.name,
                            megabytes=round(downloaded / 1_048_576, 1),
                            megabytes_per_sec=round(downloaded / 1_048_576 / elapsed, 1),
                        )

            temp_path.replace(destination)
            _validate_nsl_kdd_file(destination)
            _log(
                "info",
                "download_complete",
                file=destination.name,
                bytes=destination.stat().st_size,
                attempt=attempt,
            )
            return destination
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            OSError,
            RuntimeError,
        ) as exc:
            last_error = exc
            _log(
                "warning",
                "download_retry",
                file=destination.name,
                attempt=attempt,
                max_attempts=retries,
                error=str(exc),
            )
            time.sleep(2.0 * attempt)
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

    raise RuntimeError(
        f"Failed to download {url} after {retries} attempts: {last_error}"
    ) from last_error


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="download_dataset",
        description="Download the NSL-KDD benchmark and create data/raw/sample_data.csv.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=f"Target directory (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument("--force", action="store_true", help="Re-download / regenerate.")
    parser.add_argument(
        "--sample-only",
        action="store_true",
        help="Only (re)create the small sample CSV; skip the full benchmark.",
    )
    parser.add_argument("--sample-records", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42, help="Sample generation seed.")
    parser.add_argument("--url-train", default=TRAIN_URL)
    parser.add_argument("--url-test", default=TEST_URL)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=3)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""

    args = build_arg_parser().parse_args(argv)
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1) The sample is always ensured - it makes the pipeline testable even
    #    when the network is unavailable.
    sample_path = write_sample_csv(
        output_dir / "sample_data.csv",
        records=max(10, args.sample_records),
        seed=args.seed,
        force=args.force,
    )

    if args.sample_only:
        _log("info", "dataset_summary", sample=str(sample_path), mode="sample-only")
        return 0

    # 2) Full benchmark files.
    results: dict[str, str] = {}
    for filename, url in (("KDDTrain+.txt", args.url_train), ("KDDTest+.txt", args.url_test)):
        destination = output_dir / filename
        if destination.exists() and not args.force:
            results[filename] = "already-present"
            _log("info", "dataset_present", file=filename, path=str(destination))
            continue
        try:
            download_file(url, destination, timeout=args.timeout, retries=args.retries)
            results[filename] = "downloaded"
        except RuntimeError as exc:
            results[filename] = f"failed: {exc}"
            _log("error", "dataset_download_failed", file=filename, error=str(exc))

    _log(
        "info",
        "dataset_summary",
        output_dir=str(output_dir),
        sample=str(sample_path),
        results=results,
    )

    if results.get("KDDTrain+.txt", "").startswith("failed"):
        _log(
            "warning",
            "dataset_degraded",
            note="Full benchmark unavailable - use data/raw/sample_data.csv for testing.",
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
