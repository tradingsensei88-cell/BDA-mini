"""CyberShield AI - NSL-KDD preprocessing pipeline for model training.

Transforms the raw benchmark files into leakage-free, training-ready Parquet
artifacts for the attack-detection models.

Documented preprocessing steps (executed in this order)
-------------------------------------------------------
1. **Load**    - read ``KDDTrain+`` (+ ``KDDTest+`` when present) through
   :class:`~streaming.producers.dataset_adapter.NSLKDDAdapter`, which coerces
   dtypes, trims labels and validates the 43-column layout.
2. **Label**   - map the 39 fine-grained ``attack_type`` labels onto the five
   super-categories (Normal/DoS/Probe/R2L/U2R), add the canonical
   ``attack_category_encoded`` codes (Normal=0, DoS=1, Probe=2, R2L=3, U2R=4,
   Unknown=5) and the binary ``is_attack`` flag.
3. **Missing values** - numeric NaN -> ``0`` (no measured activity),
   categorical NaN -> ``"unknown"``; every fill is counted and reported.
4. **Constant columns** - drop zero-variance features (e.g.
   ``num_outbound_cmds``) detected on the *training* split.
5. **Split**   - use ``KDDTest+`` as the test set when available; otherwise
   perform a stratified ``train_test_split`` on ``attack_category``.
6. **Encode**  - label-encode ``protocol_type`` / ``service`` / ``flag`` with
   encoders **fitted on the training split only**; unseen test categories get
   the reserved code ``len(classes)`` (their count is reported).
7. **Normalize** - ``MinMaxScaler`` fitted on the training split is applied to
   the non-binary numeric features; scaled values are stored as
   ``<feature>_scaled`` columns alongside the raw values.
8. **Persist** - write ``train.parquet`` / ``test.parquet`` plus
   ``label_encoders.json``, ``scaler.json`` and ``preprocessing_report.json``
   into ``data/processed/``.

CLI::

    python -m ml.preprocessing.preprocess
    python -m ml.preprocessing.preprocess --train-path data/raw/sample_data.csv \
        --output-dir data/processed --test-size 0.3
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, MinMaxScaler

from streaming.logging_config import configure_logging, get_logger
from streaming.producers.dataset_adapter import (
    ATTACK_CATEGORY_MAP,
    INTEGER_FEATURE_FIELDS,
    NSLKDDAdapter,
)
from streaming.schemas.event_schema import (
    NSL_KDD_BINARY_FIELDS,
    NSL_KDD_CATEGORICAL_FIELDS,
    NSL_KDD_FEATURE_FIELDS,
)
from streaming.settings import data_processed_dir, load_env, resolve_dataset_path

logger = get_logger(__name__)

#: Canonical, deterministic encoding of the attack categories. Fixed codes
#: (instead of alphabetical ``LabelEncoder`` output) keep the semantics
#: stable across training runs and datasets.
ATTACK_CATEGORY_CODES: dict[str, int] = {
    "Normal": 0,
    "DoS": 1,
    "Probe": 2,
    "R2L": 3,
    "U2R": 4,
    "Unknown": 5,
}

DEFAULT_TEST_SIZE = 0.2
DEFAULT_RANDOM_STATE = 42

#: Features that must not be scaled: categorical strings and 0/1 flags.
NON_SCALED_FEATURES: frozenset[str] = frozenset(
    {*NSL_KDD_CATEGORICAL_FIELDS, *NSL_KDD_BINARY_FIELDS}
)


# =============================================================================
# 1-2. Loading + labelling
# =============================================================================


def load_raw_dataset(
    train_path: str | Path,
    test_path: str | Path | None = None,
    *,
    adapter: NSLKDDAdapter | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Load and label the raw dataset file(s).

    Returns ``(train, test)`` where ``test`` is ``None`` when no separate test
    file was provided (the caller then performs a stratified split).
    """

    adapter = adapter or NSLKDDAdapter()
    train = _load_and_label(train_path, adapter, split_name="train")
    logger.info("step_load_train", path=str(train_path), rows=int(len(train)))

    test: pd.DataFrame | None = None
    if test_path is not None:
        test = _load_and_label(test_path, adapter, split_name="test")
        logger.info("step_load_test", path=str(test_path), rows=int(len(test)))

    return train, test


def _load_and_label(path: str | Path, adapter: NSLKDDAdapter, *, split_name: str) -> pd.DataFrame:
    """Load one file and attach the ground-truth label columns."""

    raw = adapter.load_dataset(path)
    # Cleaning without synthetic metadata or opportunistic encodings - the ML
    # pipeline builds its own train-fitted encoders below.
    labelled = adapter.preprocess(
        raw,
        handle_missing=False,
        drop_duplicates=False,
        add_synthetic_fields=False,
        add_encoded_columns=False,
    )
    labelled = add_attack_labels(labelled)
    labelled["source_split"] = split_name
    return labelled


def add_attack_labels(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach ``attack_category``, ``attack_category_encoded`` and ``is_attack``.

    Unknown fine-grained labels (never seen in the 39-type taxonomy) are
    mapped to ``"Unknown"`` and counted in the logs.
    """

    frame = frame.copy()
    frame["attack_category"] = (
        frame["attack_type"].map(ATTACK_CATEGORY_MAP).fillna("Unknown")
    )
    unknown = int((frame["attack_category"] == "Unknown").sum())
    if unknown:
        labels = sorted(
            frame.loc[frame["attack_category"] == "Unknown", "attack_type"]
            .dropna()
            .unique()
            .tolist()
        )
        logger.warning("unknown_attack_labels", count=unknown, labels=labels[:20])

    frame["attack_category_encoded"] = (
        frame["attack_category"].map(ATTACK_CATEGORY_CODES).fillna(-1).astype("int64")
    )
    frame["is_attack"] = frame["attack_category"] != "Normal"
    return frame


# =============================================================================
# 3. Missing values
# =============================================================================


def handle_missing_values(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Fill numeric NaN with ``0`` and categorical NaN with ``"unknown"``.

    The raw benchmark contains no missing cells, but merged/streamed sources
    may; this step makes the pipeline robust either way. Returns the filled
    frame and a ``{column: count}`` report of everything that was repaired.
    """

    frame = frame.copy()
    report: dict[str, int] = {}

    numeric_columns = [
        column
        for column in NSL_KDD_FEATURE_FIELDS
        if column not in NSL_KDD_CATEGORICAL_FIELDS and column in frame.columns
    ]
    for column in numeric_columns:
        missing = int(frame[column].isna().sum())
        if missing:
            report[column] = missing
            frame[column] = frame[column].fillna(0)
        # Restore tight dtypes: integer features stay integral, rate features
        # remain floats even when their values happen to be 0.0/1.0 only.
        if column in INTEGER_FEATURE_FIELDS:
            frame[column] = frame[column].astype("int64")
        else:
            frame[column] = frame[column].astype("float64")

    for column in frame.columns:
        if frame[column].dtype == object or str(frame[column].dtype) == "string":
            missing = int(frame[column].isna().sum())
            if missing:
                report[column] = missing
                frame[column] = frame[column].fillna("unknown")

    if report:
        logger.info("step_missing_values", repaired=report)
    else:
        logger.info("step_missing_values", repaired={}, note="no missing values found")
    return frame, report


# =============================================================================
# 4. Constant columns
# =============================================================================


def remove_constant_columns(
    train: pd.DataFrame, test: pd.DataFrame | None
) -> tuple[pd.DataFrame, pd.DataFrame | None, list[str]]:
    """Drop features with a single distinct value across the training split."""

    candidates = [c for c in NSL_KDD_FEATURE_FIELDS if c in train.columns]
    constants = [column for column in candidates if train[column].nunique(dropna=False) <= 1]

    if not constants:
        logger.info("step_constant_columns", removed=[])
        return train, test, []

    train = train.drop(columns=constants)
    if test is not None:
        test = test.drop(columns=[c for c in constants if c in test.columns])
    logger.info("step_constant_columns", removed=constants)
    return train, test, constants


# =============================================================================
# 5. Split
# =============================================================================


def split_dataset(
    frame: pd.DataFrame,
    *,
    test_size: float = DEFAULT_TEST_SIZE,
    random_state: int = DEFAULT_RANDOM_STATE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Stratified train/test split (stratified on ``attack_category``)."""

    try:
        train, test = train_test_split(
            frame,
            test_size=test_size,
            random_state=random_state,
            stratify=frame["attack_category"],
        )
    except ValueError as exc:
        logger.warning("stratified_split_failed", error=str(exc), fallback="random")
        train, test = train_test_split(
            frame, test_size=test_size, random_state=random_state, shuffle=True
        )
    logger.info(
        "step_split",
        train_rows=int(len(train)),
        test_rows=int(len(test)),
        test_size=test_size,
    )
    return train.reset_index(drop=True), test.reset_index(drop=True)


# =============================================================================
# 6. Categorical encoding
# =============================================================================


def encode_categorical_features(
    train: pd.DataFrame,
    test: pd.DataFrame | None,
    *,
    columns: tuple[str, ...] = NSL_KDD_CATEGORICAL_FIELDS,
    drop_original: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame | None, dict[str, dict[str, Any]]]:
    """Label-encode categorical features with train-fitted encoders.

    Unseen categories in the test split are mapped to the reserved code
    ``len(classes)`` and counted in the logs.
    """

    train = train.copy()
    test = test.copy() if test is not None else None
    encoders: dict[str, dict[str, Any]] = {}

    for column in columns:
        if column not in train.columns:
            continue
        encoder = LabelEncoder()
        train_values = train[column].astype(str)
        encoder.fit(train_values)
        mapping = {label: int(code) for code, label in enumerate(encoder.classes_)}
        unseen_code = len(encoder.classes_)
        target_column = f"{column}_encoded"

        train[target_column] = train_values.map(mapping).astype("int64")

        unseen_count = 0
        if test is not None:
            test_values = test[column].astype(str)
            encoded = test_values.map(mapping)
            unseen_count = int(encoded.isna().sum())
            test[target_column] = encoded.fillna(unseen_code).astype("int64")

        if drop_original:
            train = train.drop(columns=[column])
            if test is not None:
                test = test.drop(columns=[column])

        encoders[column] = {
            "classes": encoder.classes_.tolist(),
            "mapping": mapping,
            "unseen_code": unseen_code,
            "unseen_test_values": unseen_count,
        }
        logger.info(
            "step_encode",
            column=column,
            classes=len(encoder.classes_),
            unseen_in_test=unseen_count,
        )

    return train, test, encoders


# =============================================================================
# 7. Normalization
# =============================================================================


def normalize_numeric_features(
    train: pd.DataFrame,
    test: pd.DataFrame | None,
    *,
    excluded: frozenset[str] = NON_SCALED_FEATURES,
) -> tuple[pd.DataFrame, pd.DataFrame | None, dict[str, Any]]:
    """MinMax-scale non-binary numeric features (fitted on train only).

    Scaled values are written to ``<feature>_scaled`` columns; the raw
    columns are preserved for auditability.
    """

    train = train.copy()
    test = test.copy() if test is not None else None

    scale_columns = [
        column
        for column in NSL_KDD_FEATURE_FIELDS
        if column in train.columns and column not in excluded
    ]
    if not scale_columns:
        logger.warning("step_normalize_skipped", reason="no scalable feature columns")
        return train, test, {"method": "minmax", "columns": [], "data_min": {}, "data_max": {}}

    scaler = MinMaxScaler()
    scaler.fit(train[scale_columns].astype("float64"))

    scaled_names = [f"{column}_scaled" for column in scale_columns]
    train[scaled_names] = scaler.transform(train[scale_columns].astype("float64"))
    if test is not None:
        test[scaled_names] = scaler.transform(test[scale_columns].astype("float64"))

    scaler_params: dict[str, Any] = {
        "method": "minmax",
        "columns": scale_columns,
        "data_min": {
            column: float(value)
            for column, value in zip(scale_columns, scaler.data_min_, strict=False)
        },
        "data_max": {
            column: float(value)
            for column, value in zip(scale_columns, scaler.data_max_, strict=False)
        },
        "scale": {
            column: float(value)
            for column, value in zip(scale_columns, scaler.scale_, strict=False)
        },
    }
    logger.info("step_normalize", scaled_features=len(scale_columns))
    return train, test, scaler_params


# =============================================================================
# 8. Persistence
# =============================================================================


def save_processed_data(
    train: pd.DataFrame,
    test: pd.DataFrame,
    output_dir: str | Path,
) -> dict[str, str]:
    """Write the processed splits as Parquet files."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    outputs: dict[str, str] = {}
    for name, frame in (("train", train), ("test", test)):
        path = output_dir / f"{name}.parquet"
        try:
            frame.to_parquet(path, index=False)
        except ImportError as exc:  # pyarrow / fastparquet missing
            raise RuntimeError(
                "Parquet support requires pyarrow - run `pip install pyarrow`."
            ) from exc
        outputs[f"{name}_parquet"] = str(path)
        logger.info("step_save", split=name, path=str(path), rows=int(len(frame)))

    return outputs


def save_artifacts(
    output_dir: str | Path,
    *,
    label_encoders: dict[str, Any],
    scaler: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, str]:
    """Write encoder/scaler/report JSON artifacts next to the parquet files."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts: dict[str, str] = {}
    payloads = {
        "label_encoders.json": label_encoders,
        "scaler.json": scaler,
        "preprocessing_report.json": report,
    }
    for filename, payload in payloads.items():
        path = output_dir / filename
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
        artifacts[filename] = str(path)
    return artifacts


# =============================================================================
# Orchestration
# =============================================================================


def _class_distribution(frame: pd.DataFrame) -> dict[str, int]:
    return {
        str(category): int(count)
        for category, count in frame["attack_category"].value_counts().items()
    }


def run_preprocessing(
    train_path: str | Path | None = None,
    test_path: str | Path | None = None,
    *,
    output_dir: str | Path | None = None,
    test_size: float = DEFAULT_TEST_SIZE,
    random_state: int = DEFAULT_RANDOM_STATE,
    drop_duplicates: bool = False,
    drop_constant: bool = True,
    drop_categoricals: bool = False,
    scale: bool = True,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Execute the full preprocessing pipeline and return the report."""

    started = time.monotonic()
    steps: list[dict[str, Any]] = []

    adapter = NSLKDDAdapter(seed=random_state)

    # -- resolve inputs -------------------------------------------------------
    resolved_train = Path(train_path) if train_path else resolve_dataset_path()
    if test_path is not None:
        resolved_test: Path | None = Path(test_path)
    else:
        candidate = resolved_train.parent / "KDDTest+.txt"
        resolved_test = candidate if candidate.is_file() else None

    # -- step 1-2: load + label ------------------------------------------------
    train, test = load_raw_dataset(resolved_train, resolved_test, adapter=adapter)
    steps.append(
        {
            "step": "load_label",
            "train_path": str(resolved_train),
            "test_path": str(resolved_test) if resolved_test else None,
            "train_rows": int(len(train)),
            "test_rows": int(len(test)) if test is not None else 0,
        }
    )

    # -- step 2b: optional duplicate removal (train only) -----------------------
    if drop_duplicates:
        before = len(train)
        train = train.drop_duplicates(
            subset=[*NSL_KDD_FEATURE_FIELDS, "attack_type"]
        ).reset_index(drop=True)
        removed = before - len(train)
        steps.append({"step": "drop_duplicates", "removed_rows": removed})
        logger.info("step_drop_duplicates", removed_rows=removed)

    # -- optional subsampling for quick experiments -----------------------------
    if max_rows is not None and len(train) > max_rows:
        train = train.sample(n=max_rows, random_state=random_state).reset_index(drop=True)
        steps.append({"step": "subsample", "max_rows": max_rows, "rows": int(len(train))})
        logger.info("step_subsample", max_rows=max_rows, rows=int(len(train)))

    # -- step 3: missing values --------------------------------------------------
    train, missing_report = handle_missing_values(train)
    if test is not None:
        test, test_missing_report = handle_missing_values(test)
        missing_report.update({f"test::{k}": v for k, v in test_missing_report.items()})
    steps.append({"step": "missing_values", "repaired": missing_report})

    # -- step 4: constant columns -------------------------------------------------
    removed_constants: list[str] = []
    if drop_constant:
        train, test, removed_constants = remove_constant_columns(train, test)
        steps.append({"step": "constant_columns", "removed": removed_constants})

    # -- step 5: split --------------------------------------------------------------
    if test is None:
        train, test = split_dataset(train, test_size=test_size, random_state=random_state)
        split_mode = "stratified_split"
    else:
        split_mode = "external_test_file"
    steps.append(
        {
            "step": "split",
            "mode": split_mode,
            "train_rows": int(len(train)),
            "test_rows": int(len(test)),
        }
    )

    # -- step 6: categorical encoding --------------------------------------------------
    train, test, label_encoders = encode_categorical_features(
        train, test, drop_original=drop_categoricals
    )
    steps.append(
        {
            "step": "encode_categoricals",
            "columns": list(NSL_KDD_CATEGORICAL_FIELDS),
            "dropped_originals": drop_categoricals,
        }
    )

    # -- step 7: normalization ------------------------------------------------------------
    scaler_params: dict[str, Any] = {"method": "none", "columns": []}
    if scale:
        train, test, scaler_params = normalize_numeric_features(train, test)
        steps.append(
            {"step": "normalize", "method": "minmax", "columns": scaler_params["columns"]}
        )

    # -- step 8: persist ---------------------------------------------------------------------
    resolved_output = Path(output_dir) if output_dir else data_processed_dir()
    outputs = save_processed_data(train, test, resolved_output)

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "train_path": str(resolved_train),
            "test_path": str(resolved_test) if resolved_test else None,
            "split_mode": split_mode,
            "max_rows": max_rows,
        },
        "rows": {"train": int(len(train)), "test": int(len(test))},
        "features": {
            "original": len(NSL_KDD_FEATURE_FIELDS),
            "removed_constant": removed_constants,
            "scaled_columns": scaler_params.get("columns", []),
            "encoded_columns": [f"{c}_encoded" for c in NSL_KDD_CATEGORICAL_FIELDS],
        },
        "class_distribution": {
            "train": _class_distribution(train),
            "test": _class_distribution(test),
        },
        "missing_values": missing_report,
        "steps": steps,
        "outputs": outputs,
        "duration_seconds": round(time.monotonic() - started, 2),
        "notes": [
            "Encoders and the scaler are fitted on the training split only "
            "(no test leakage).",
            "Unseen test categories are mapped to the reserved code "
            "len(classes) per categorical feature.",
            "Scaled features use the suffix _scaled; raw values are preserved.",
        ],
    }

    artifacts = save_artifacts(
        resolved_output,
        label_encoders=label_encoders,
        scaler=scaler_params,
        report=report,
    )
    report["outputs"].update(artifacts)

    logger.info(
        "preprocessing_complete",
        train_rows=report["rows"]["train"],
        test_rows=report["rows"]["test"],
        outputs=report["outputs"],
        duration_seconds=report["duration_seconds"],
    )
    return report


# =============================================================================
# CLI
# =============================================================================


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="preprocess",
        description="Preprocess NSL-KDD into training-ready Parquet artifacts.",
    )
    parser.add_argument("--train-path", default=None, help="Raw training file.")
    parser.add_argument(
        "--test-path",
        default=None,
        help="Raw test file. Default: data/raw/KDDTest+.txt when present, else a "
        "stratified split of the training data.",
    )
    parser.add_argument("--output-dir", default=None, help="Artifact directory.")
    parser.add_argument("--test-size", type=float, default=DEFAULT_TEST_SIZE)
    parser.add_argument("--random-state", type=int, default=DEFAULT_RANDOM_STATE)
    parser.add_argument("--max-rows", type=int, default=None, help="Subsample for quick runs.")
    parser.add_argument("--drop-duplicates", action="store_true")
    parser.add_argument(
        "--keep-constant", action="store_true", help="Keep zero-variance features."
    )
    parser.add_argument(
        "--drop-categoricals",
        action="store_true",
        help="Remove raw categorical text columns after encoding.",
    )
    parser.add_argument("--no-scale", action="store_true", help="Skip normalization.")
    parser.add_argument("--log-level", default=None)
    parser.add_argument("--json-logs", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""

    args = build_arg_parser().parse_args(argv)
    configure_logging(level=args.log_level, json_logs=True if args.json_logs else None)
    load_env()

    try:
        report = run_preprocessing(
            train_path=args.train_path,
            test_path=args.test_path,
            output_dir=args.output_dir,
            test_size=args.test_size,
            random_state=args.random_state,
            drop_duplicates=args.drop_duplicates,
            drop_constant=not args.keep_constant,
            drop_categoricals=args.drop_categoricals,
            scale=not args.no_scale,
            max_rows=args.max_rows,
        )
    except FileNotFoundError as exc:
        logger.error("preprocessing_input_missing", error=str(exc))
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        logger.exception("preprocessing_failed", error=str(exc))
        return 2

    logger.info("preprocessing_summary", report=report)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
