"""CyberShield AI - NSL-KDD dataset adapter.

Turns the raw NSL-KDD benchmark files (``KDDTrain+.txt`` / ``KDDTest+.txt`` or
the bundled ``sample_data.csv``) into cleaned, enriched, Kafka-ready event
dictionaries.

Responsibilities
----------------
* Knows the **41 canonical feature columns** (imported from
  :mod:`streaming.schemas.event_schema` - single source of truth) plus the two
  label columns ``attack_type`` and ``difficulty_level``.
* Maps all **39 detailed attack labels** onto the 5 NSL-KDD super-categories
  (Normal / DoS / Probe / R2L / U2R), with a defensive ``Unknown`` fallback.
* :meth:`NSLKDDAdapter.load_dataset` - read the raw file into a DataFrame.
* :meth:`NSLKDDAdapter.preprocess` - clean, label, encode and enrich the
  DataFrame (synthetic ``event_id``, ``timestamp``, ``source_host`` /
  ``destination_host``, ``*_ip``, ``*_port`` fields).
* :meth:`NSLKDDAdapter.to_events` / :meth:`NSLKDDAdapter.iter_events` - produce
  JSON-serialisable event dictionaries ready to be published to the
  ``network-events`` Kafka topic.

CLI (inspection helper)::

    python -m streaming.producers.dataset_adapter --dataset data/raw/sample_data.csv --rows 2
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

if __package__ in (None, ""):  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd

from streaming.logging_config import get_logger
from streaming.schemas.event_schema import (
    NSL_KDD_BINARY_FIELDS,
    NSL_KDD_CATEGORICAL_FIELDS,
    NSL_KDD_COLUMNS,
    NSL_KDD_FEATURE_FIELDS,
    NSL_KDD_LABEL_FIELDS,
    AttackCategory,
    ensure_utc,
)

logger = get_logger(__name__)

# =============================================================================
# Attack taxonomy - all 39 attack types across the 5 NSL-KDD categories
# =============================================================================

_NORMAL = AttackCategory.NORMAL.value
_UNKNOWN = AttackCategory.UNKNOWN.value

#: Detailed NSL-KDD attack types grouped by super-category.
ATTACK_TYPES_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    _NORMAL: ("normal",),
    AttackCategory.DOS.value: (
        "back",
        "land",
        "neptune",
        "pod",
        "smurf",
        "teardrop",
        "apache2",
        "udpstorm",
        "processtable",
        "mailbomb",
    ),
    AttackCategory.PROBE.value: (
        "satan",
        "ipsweep",
        "nmap",
        "portsweep",
        "mscan",
        "saint",
    ),
    AttackCategory.R2L.value: (
        "guess_passwd",
        "ftp_write",
        "imap",
        "phf",
        "multihop",
        "warezmaster",
        "warezclient",
        "spy",
        "xlock",
        "xsnoop",
        "snmpguess",
        "snmpgetattack",
        "httptunnel",
        "sendmail",
        "named",
        "worm",
    ),
    AttackCategory.U2R.value: (
        "buffer_overflow",
        "loadmodule",
        "rootkit",
        "perl",
        "sqlattack",
        "xterm",
        "ps",
    ),
}

#: ``attack_type`` -> super-category lookup covering all 39 attack labels.
ATTACK_CATEGORY_MAP: dict[str, str] = {
    attack: category
    for category, attacks in ATTACK_TYPES_BY_CATEGORY.items()
    for attack in attacks
}

#: Numeric features stored as integers in the raw dataset.
INTEGER_FEATURE_FIELDS: tuple[str, ...] = (
    "duration",
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
    "dst_host_count",
    "dst_host_srv_count",
)

#: Continuous (rate/ratio) features stored as floats in the raw dataset.
CONTINUOUS_FEATURE_FIELDS: tuple[str, ...] = tuple(
    field
    for field in NSL_KDD_FEATURE_FIELDS
    if field not in INTEGER_FEATURE_FIELDS and field not in NSL_KDD_CATEGORICAL_FIELDS
)

#: Well-known destination ports for the NSL-KDD service vocabulary.
#: Services without a conventional port (``private``, ``ecr_i``, ...) are not
#: mapped and yield ``None`` for ``destination_port``.
SERVICE_PORT_MAP: dict[str, int] = {
    "echo": 7,
    "discard": 9,
    "systat": 11,
    "daytime": 13,
    "netstat": 15,
    "ftp_data": 20,
    "ftp": 21,
    "ssh": 22,
    "telnet": 23,
    "smtp": 25,
    "time": 37,
    "name": 42,
    "whois": 43,
    "domain": 53,
    "domain_u": 53,
    "mtp": 57,
    "tftp_u": 69,
    "gopher": 70,
    "finger": 79,
    "http": 80,
    "iso_tsap": 102,
    "hostnames": 101,
    "csnet_ns": 105,
    "pop_2": 109,
    "sunrpc": 111,
    "auth": 113,
    "nntp": 119,
    "ntp_u": 123,
    "netbios_ns": 137,
    "netbios_dgm": 138,
    "netbios_ssn": 139,
    "imap4": 143,
    "sql_net": 1521,
    "bgp": 179,
    "irc": 194,
    "z39_50": 210,
    "ldap": 389,
    "https": 443,
    "http_443": 443,
    "https_443": 443,
    "http_2784": 2784,
    "http_8001": 8001,
    "exec": 512,
    "login": 513,
    "shell": 514,
    "printer": 515,
    "efs": 520,
    "courier": 530,
    "uucp": 540,
    "uucp_path": 540,
    "klogin": 543,
    "kshell": 544,
    "x11": 6000,
    "aol": 5190,
}


# =============================================================================
# Adapter
# =============================================================================


class NSLKDDAdapter:
    """Load, clean, enrich and serialise NSL-KDD network flow records.

    Args:
        dataset_path: Default dataset file used when ``load_dataset`` is
            called without an explicit path.
        seed: Deterministic seed for all synthetic field generation
            (event ids, timestamps, host assignment, ports).
        host_count: Size of the synthetic host pool (``HOST-001..HOST-n``).
        start_timestamp: Base event time. Defaults to "now minus five
            minutes" so simulated traffic always looks recent.
        event_arrival_mean_seconds: Mean inter-arrival time used to generate
            monotonically increasing event timestamps (default 20 ms ~= 50
            events/sec of recorded traffic).
    """

    #: First token of the header row used to detect files with a header line.
    HEADER_SENTINEL = NSL_KDD_FEATURE_FIELDS[0]

    FEATURE_FIELDS = NSL_KDD_FEATURE_FIELDS
    LABEL_FIELDS = NSL_KDD_LABEL_FIELDS
    ALL_FIELDS = NSL_KDD_COLUMNS
    CATEGORICAL_FIELDS = NSL_KDD_CATEGORICAL_FIELDS
    BINARY_FIELDS = NSL_KDD_BINARY_FIELDS
    INTEGER_FIELDS = INTEGER_FEATURE_FIELDS
    CONTINUOUS_FIELDS = CONTINUOUS_FEATURE_FIELDS

    ATTACK_CATEGORY_MAP = ATTACK_CATEGORY_MAP
    ATTACK_TYPES_BY_CATEGORY = ATTACK_TYPES_BY_CATEGORY
    SERVICE_PORT_MAP = SERVICE_PORT_MAP

    def __init__(
        self,
        dataset_path: str | Path | None = None,
        *,
        seed: int = 42,
        host_count: int = 100,
        start_timestamp: datetime | None = None,
        event_arrival_mean_seconds: float = 0.02,
    ) -> None:
        self.dataset_path = Path(dataset_path) if dataset_path else None
        self.seed = int(seed)
        self.host_count = max(2, int(host_count))
        self.start_timestamp = ensure_utc(
            start_timestamp
            or (datetime.now(timezone.utc) - pd.Timedelta(minutes=5).to_pytimedelta())
        )
        self.event_arrival_mean_seconds = max(0.001, float(event_arrival_mean_seconds))

        #: Category label -> integer encoding, populated by ``preprocess``.
        self.encoding_mappings: dict[str, dict[str, int]] = {}
        #: Attack distribution of the most recently preprocessed DataFrame.
        self.attack_distribution_: dict[str, int] = {}

    # ------------------------------------------------------------------ load

    def load_dataset(self, filepath: str | Path | None = None) -> pd.DataFrame:
        """Read a raw NSL-KDD file into a DataFrame.

        Handles both headerless raw files (43 comma-separated columns in the
        canonical order) and CSV exports that include a header row (e.g.
        ``data/raw/sample_data.csv``).

        Args:
            filepath: Path to the dataset file. Falls back to the path given
                to the constructor.

        Returns:
            DataFrame with the 43 canonical columns, categoricals trimmed and
            label columns normalised (``attack_type`` lowercased, trailing
            dots removed).

        Raises:
            ValueError: If no path is available or the file layout does not
                match the NSL-KDD schema.
            FileNotFoundError: If the file does not exist.
        """

        path = Path(filepath) if filepath else self.dataset_path
        if path is None:
            raise ValueError(
                "No dataset path provided. Pass a filepath to load_dataset() or "
                "set dataset_path on the adapter."
            )
        if not path.is_file():
            raise FileNotFoundError(f"Dataset file not found: {path}")

        has_header = self._detect_header(path)
        if has_header:
            frame = pd.read_csv(path, encoding="utf-8-sig", skipinitialspace=True)
            frame.columns = [str(col).strip().lstrip("\ufeff") for col in frame.columns]
            missing = [col for col in self.ALL_FIELDS if col not in frame.columns]
            if missing:
                raise ValueError(
                    f"Dataset {path} is missing required columns: {missing}. "
                    f"Expected the 43 NSL-KDD columns: {list(self.ALL_FIELDS)}"
                )
            extra = [col for col in frame.columns if col not in self.ALL_FIELDS]
            if extra:
                logger.warning("dataset_extra_columns_dropped", path=str(path), columns=extra)
            frame = frame.loc[:, list(self.ALL_FIELDS)]
        else:
            frame = pd.read_csv(
                path,
                header=None,
                names=list(self.ALL_FIELDS),
                encoding="utf-8-sig",
                skipinitialspace=True,
            )
            if frame.shape[1] != len(self.ALL_FIELDS):
                raise ValueError(
                    f"Dataset {path} has {frame.shape[1]} columns, expected "
                    f"{len(self.ALL_FIELDS)} ({len(self.FEATURE_FIELDS)} features + "
                    f"{len(self.LABEL_FIELDS)} labels)."
                )

        frame = self._coerce_labels(frame)
        logger.info(
            "dataset_loaded",
            path=str(path),
            rows=int(len(frame)),
            columns=int(frame.shape[1]),
            header=has_header,
        )
        return frame

    @staticmethod
    def _detect_header(path: Path) -> bool:
        """Return ``True`` when the first line looks like a header row."""

        try:
            with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
                first_line = handle.readline()
        except OSError as exc:  # pragma: no cover - filesystem specific
            raise OSError(f"Unable to read dataset file {path}: {exc}") from exc
        first_token = first_line.split(",", 1)[0].strip().strip('"').lower()
        return first_token == NSLKDDAdapter.HEADER_SENTINEL

    def _coerce_labels(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Normalise label/categorical columns and coerce numeric dtypes."""

        frame = frame.copy()

        for column in self.CATEGORICAL_FIELDS:
            if column in frame.columns:
                frame[column] = frame[column].astype("string").str.strip().fillna("unknown")

        if "attack_type" in frame.columns:
            frame["attack_type"] = (
                frame["attack_type"]
                .astype("string")
                .str.strip()
                .str.lower()
                .str.rstrip(".")
                .replace({"": pd.NA})
            )

        if "difficulty_level" in frame.columns:
            frame["difficulty_level"] = pd.to_numeric(
                frame["difficulty_level"], errors="coerce"
            ).astype("Int64")

        for column in self.INTEGER_FIELDS:
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")

        for column in self.CONTINUOUS_FIELDS:
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")

        return frame

    # ------------------------------------------------------------- preprocess

    def preprocess(
        self,
        frame: pd.DataFrame,
        *,
        handle_missing: bool = True,
        drop_duplicates: bool = False,
        add_synthetic_fields: bool = True,
        add_encoded_columns: bool = True,
    ) -> pd.DataFrame:
        """Clean and enrich a raw NSL-KDD DataFrame.

        Steps:

        1. Validate the presence of the 43 canonical columns.
        2. Normalise categorical/label columns (idempotent).
        3. Handle missing values (numeric -> 0, categorical -> ``"unknown"``,
           rows without an ``attack_type`` label are dropped).
        4. Map ``attack_type`` onto ``attack_category`` (39 labels -> 5
           categories, unknown labels become ``"Unknown"`` and are logged).
        5. Add ``is_attack`` boolean.
        6. Generate synthetic pipeline fields: ``event_id`` (UUID4,
           deterministic under ``seed``), increasing ``timestamp`` values,
           ``source_host`` / ``destination_host`` (``HOST-001..HOST-n``),
           ``source_ip`` / ``destination_ip``, ``source_port`` (ephemeral
           range) and ``destination_port`` (from the service-port map).
        7. Optionally add label-encoded ``*_encoded`` columns for the three
           categorical features.

        Args:
            frame: DataFrame as returned by :meth:`load_dataset` (or any frame
                with the canonical columns).
            handle_missing: Fill/repair missing values (recommended).
            drop_duplicates: Drop duplicate feature rows (kept by default to
                preserve the original class balance of the benchmark).
            add_synthetic_fields: Generate the synthetic event fields.
            add_encoded_columns: Add ``protocol_type_encoded`` etc.

        Returns:
            A new enriched DataFrame.
        """

        self._require_columns(frame)
        result = self._coerce_labels(frame)
        initial_rows = len(result)

        if handle_missing:
            result = self._handle_missing_values(result)

        # Drop rows without an attack label - they cannot be categorised.
        unlabeled = result["attack_type"].isna()
        if unlabeled.any():
            logger.warning("rows_dropped_unlabeled", count=int(unlabeled.sum()))
            result = result.loc[~unlabeled].reset_index(drop=True)

        # Ground-truth category mapping (39 labels -> 5 categories).
        result["attack_category"] = (
            result["attack_type"].map(self.ATTACK_CATEGORY_MAP).fillna(_UNKNOWN)
        )
        unknown_mask = result["attack_category"] == _UNKNOWN
        if unknown_mask.any():
            unknown_labels = sorted(result.loc[unknown_mask, "attack_type"].unique().tolist())
            logger.warning(
                "unknown_attack_labels",
                count=int(unknown_mask.sum()),
                labels=unknown_labels[:20],
            )
        result["is_attack"] = result["attack_category"] != _NORMAL

        if drop_duplicates:
            before = len(result)
            result = result.drop_duplicates(
                subset=[*self.FEATURE_FIELDS, "attack_type"]
            ).reset_index(drop=True)
            logger.info("duplicates_dropped", removed=int(before - len(result)))

        if add_synthetic_fields:
            result = self._add_synthetic_fields(result)

        if add_encoded_columns:
            result = self._add_encoded_columns(result)

        self.attack_distribution_ = {
            str(category): int(count)
            for category, count in result["attack_category"].value_counts().items()
        }
        logger.info(
            "preprocess_complete",
            input_rows=int(initial_rows),
            output_rows=int(len(result)),
            attack_distribution=self.attack_distribution_,
        )
        return result

    def _require_columns(self, frame: pd.DataFrame) -> None:
        missing = [column for column in self.ALL_FIELDS if column not in frame.columns]
        if missing:
            raise ValueError(
                f"DataFrame is missing required NSL-KDD columns: {missing}. "
                "Load the data through NSLKDDAdapter.load_dataset() first."
            )

    def _handle_missing_values(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Fill numeric NaNs with 0 and categorical NaNs with ``"unknown"``."""

        missing_counts: dict[str, int] = {}

        for column in [*self.INTEGER_FIELDS, *self.CONTINUOUS_FIELDS]:
            if column not in frame.columns:
                continue
            count = int(frame[column].isna().sum())
            if count:
                missing_counts[column] = count
                frame[column] = frame[column].fillna(0)

        for column in self.CATEGORICAL_FIELDS:
            count = int(frame[column].isna().sum())
            if count:
                missing_counts[column] = count
                frame[column] = frame[column].fillna("unknown")

        if missing_counts:
            logger.warning("missing_values_filled", columns=missing_counts)

        # Cast integer features to tight int64 once NaNs are resolved.
        for column in self.INTEGER_FIELDS:
            frame[column] = frame[column].astype("int64")
        for column in self.CONTINUOUS_FIELDS:
            frame[column] = frame[column].astype("float64")

        return frame

    def _add_synthetic_fields(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Attach event identity, timestamps and synthetic network topology."""

        rng = np.random.default_rng(self.seed)
        rows = len(frame)
        frame = frame.copy()

        if rows == 0:
            for column in (
                "event_id",
                "timestamp",
                "source_host",
                "destination_host",
                "source_ip",
                "destination_ip",
                "source_port",
                "destination_port",
            ):
                frame[column] = pd.Series(dtype="object")
            return frame

        # -- Event ids: deterministic UUID4 values derived from the seed ------
        raw_bytes = rng.bytes(16 * rows)
        frame["event_id"] = [
            str(uuid.UUID(bytes=raw_bytes[index * 16 : (index + 1) * 16], version=4))
            for index in range(rows)
        ]

        # -- Timestamps: exponentially spaced, monotonically increasing ------
        inter_arrivals = rng.exponential(self.event_arrival_mean_seconds, size=rows)
        offsets = pd.to_timedelta(np.cumsum(inter_arrivals), unit="s")
        frame["timestamp"] = pd.Timestamp(self.start_timestamp) + offsets

        # -- Hosts: HOST-001..HOST-n, never identical on both ends -----------
        source_index = rng.integers(1, self.host_count + 1, size=rows)
        destination_index = rng.integers(1, self.host_count + 1, size=rows)
        collisions = source_index == destination_index
        destination_index[collisions] = (destination_index[collisions] % self.host_count) + 1

        frame["source_host"] = [f"HOST-{index:03d}" for index in source_index]
        frame["destination_host"] = [f"HOST-{index:03d}" for index in destination_index]
        frame["source_ip"] = [self._host_to_ip(index) for index in source_index]
        frame["destination_ip"] = [self._host_to_ip(index) for index in destination_index]

        # -- Ports: ephemeral source ports + service-derived destination ------
        frame["source_port"] = rng.integers(49152, 65536, size=rows)
        service_lookup = {name.lower(): port for name, port in self.SERVICE_PORT_MAP.items()}
        frame["destination_port"] = (
            frame["service"].astype("string").str.lower().map(service_lookup).astype("Int64")
        )

        return frame

    @staticmethod
    def _host_to_ip(index: int) -> str:
        """Map a synthetic host index onto a stable RFC1918 address."""

        return f"10.0.{index // 254}.{index % 254 + 1}"

    def _add_encoded_columns(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Label-encode the categorical features (whole-frame, sorted order).

        Note:
            This convenience encoding is fit on the entire frame and is meant
            for exploration/streaming use. The ML pipeline builds train-fitted
            encoders separately (see ``ml/preprocessing/preprocess.py``).
        """

        self.encoding_mappings = {}
        for column in self.CATEGORICAL_FIELDS:
            values = frame[column].astype("string").fillna("unknown")
            categories = sorted(values.dropna().unique().tolist())
            mapping = {category: index for index, category in enumerate(categories)}
            frame[f"{column}_encoded"] = values.map(mapping).fillna(-1).astype("int64")
            self.encoding_mappings[column] = mapping
        return frame

    # --------------------------------------------------------------- exports

    #: Columns included in JSON events, in wire order.
    EVENT_COLUMNS: tuple[str, ...] = (
        "event_id",
        "timestamp",
        *NSL_KDD_FEATURE_FIELDS,
        "attack_type",
        "attack_category",
        "difficulty_level",
        "source_host",
        "destination_host",
        "source_ip",
        "destination_ip",
        "source_port",
        "destination_port",
    )

    def to_events(self, frame: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
        """Convert a preprocessed DataFrame into JSON-ready event dictionaries.

        Missing synthetic fields are generated automatically by running
        :meth:`preprocess` first. All values are converted to native Python
        types (no numpy scalars) so the payloads can be handed directly to
        ``json.dumps`` / the Kafka producer serializer.
        """

        prepared = self._ensure_event_ready(frame)
        if limit is not None:
            prepared = prepared.iloc[: max(0, int(limit))]

        view = prepared.loc[:, list(self.EVENT_COLUMNS)].copy()
        view["timestamp"] = pd.to_datetime(view["timestamp"], utc=True).dt.strftime(
            "%Y-%m-%dT%H:%M:%S.%f+00:00"
        )
        view["attack_category"] = view["attack_category"].astype("string")

        native = view.astype(object).where(pd.notnull(view), None)
        return native.to_dict(orient="records")

    def iter_events(
        self, frame: pd.DataFrame, chunk_size: int = 2048
    ) -> Iterator[dict[str, Any]]:
        """Yield event dictionaries in bounded-memory chunks.

        Useful for large datasets (KDDTrain+ has 125,973 rows): the full list
        is never materialised at once.
        """

        prepared = self._ensure_event_ready(frame)
        rows = len(prepared)
        for start in range(0, rows, chunk_size):
            chunk = prepared.iloc[start : start + chunk_size]
            yield from self.to_events(chunk)

    def _ensure_event_ready(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return a frame guaranteed to contain the synthetic event fields."""

        required = {"event_id", "timestamp", "attack_category", "source_host"}
        if required.issubset(frame.columns):
            return frame
        logger.info("auto_preprocess_for_events")
        return self.preprocess(frame)

    # ------------------------------------------------------------ summaries

    def summary(self, frame: pd.DataFrame) -> dict[str, Any]:
        """Return a JSON-friendly summary of a (raw or preprocessed) frame."""

        total = int(len(frame))
        if "attack_category" in frame.columns:
            categories = frame["attack_category"].astype("string")
        else:
            categories = (
                frame["attack_type"].map(self.ATTACK_CATEGORY_MAP).fillna(_UNKNOWN)
            )

        distribution = {
            str(category): int(count)
            for category, count in categories.value_counts().items()
        }
        attack_count = int((categories != _NORMAL).sum())
        unknown_labels = sorted(
            frame.loc[categories == _UNKNOWN, "attack_type"].dropna().unique().tolist()
        )

        return {
            "row_count": total,
            "feature_count": len(self.FEATURE_FIELDS),
            "normal_count": total - attack_count,
            "attack_count": attack_count,
            "attack_distribution": distribution,
            "distinct_attack_types": int(frame["attack_type"].nunique()),
            "unknown_attack_types": unknown_labels,
        }


# =============================================================================
# CLI - inspect a dataset file without Spark/Kafka
# =============================================================================


def _main() -> int:  # pragma: no cover - manual helper
    import argparse
    import json

    from streaming.settings import resolve_dataset_path

    parser = argparse.ArgumentParser(
        description="Inspect/preview NSL-KDD data through the dataset adapter."
    )
    parser.add_argument("--dataset", default=None, help="Path to KDDTrain+/test/sample file.")
    parser.add_argument("--rows", type=int, default=2, help="Number of sample events to print.")
    parser.add_argument("--seed", type=int, default=42, help="Synthetic-field seed.")
    args = parser.parse_args()

    path = resolve_dataset_path(args.dataset)
    adapter = NSLKDDAdapter(path, seed=args.seed)

    raw = adapter.load_dataset()
    raw_summary = adapter.summary(raw)
    clean = adapter.preprocess(raw)
    events = adapter.to_events(clean, limit=max(0, args.rows))

    print(json.dumps({"raw_summary": raw_summary}, indent=2, default=str))
    print(json.dumps({"events": events}, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
