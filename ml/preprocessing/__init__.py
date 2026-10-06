"""Feature engineering and dataset adapters (NSL-KDD, CICIDS) for model training.

Exports are resolved lazily (PEP 562) so importing the package stays cheap
until the preprocessing functions are actually used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import-time typing only
    from ml.preprocessing.preprocess import (
        ATTACK_CATEGORY_CODES,
        add_attack_labels,
        encode_categorical_features,
        handle_missing_values,
        load_raw_dataset,
        normalize_numeric_features,
        remove_constant_columns,
        run_preprocessing,
        save_processed_data,
        split_dataset,
    )

__all__ = [
    "run_preprocessing",
    "load_raw_dataset",
    "add_attack_labels",
    "handle_missing_values",
    "remove_constant_columns",
    "split_dataset",
    "encode_categorical_features",
    "normalize_numeric_features",
    "save_processed_data",
    "ATTACK_CATEGORY_CODES",
]

_LAZY_IMPORTS: dict[str, str] = {
    name: "ml.preprocessing.preprocess" for name in __all__
}


def __getattr__(name: str) -> Any:
    try:
        module_name = _LAZY_IMPORTS[name]
    except KeyError as exc:  # pragma: no cover - standard module behaviour
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    import importlib

    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:  # pragma: no cover - introspection helper
    return sorted(__all__)
