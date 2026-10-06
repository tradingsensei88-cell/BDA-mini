"""One-off import sweep for the CyberShield backend (verification only)."""

from __future__ import annotations

import importlib
import pkgutil
import sys
import traceback

sys.path.insert(0, ".")

import app  # noqa: E402

modules = ["app"]
for module_info in pkgutil.walk_packages(app.__path__, "app."):
    modules.append(module_info.name)

failures: list[tuple[str, str]] = []
for name in sorted(set(modules)):
    try:
        importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 - report, don't stop
        failures.append((name, f"{type(exc).__name__}: {exc}"))

print(f"IMPORT_SWEEP modules={len(set(modules))} failures={len(failures)}")
for name, error in failures:
    print(f"FAIL {name} -> {error}")

# Extra: service singletons instantiate correctly
from app.services.alert_engine import get_alert_engine  # noqa: E402
from app.services.analytics_service import get_analytics_service  # noqa: E402
from app.services.event_service import get_event_service  # noqa: E402
from app.services.investigation_service import get_investigation_service  # noqa: E402
from app.services.ml_service import get_ml_service  # noqa: E402
from app.services.risk_scoring import get_risk_engine  # noqa: E402
from app.services.simulation_service import get_simulation_service  # noqa: E402
from app.services.system_service import get_system_service  # noqa: E402
from app.websocket import get_event_streamer, get_ws_manager  # noqa: E402

singletons = [
    get_alert_engine(),
    get_analytics_service(),
    get_event_service(),
    get_investigation_service(),
    get_ml_service(),
    get_risk_engine(),
    get_simulation_service(),
    get_system_service(),
    get_event_streamer(),
    get_ws_manager(),
]
print("SINGLETONS_OK", len(singletons))

# Extra: risk engine sanity (spec formula thresholds)
engine = get_risk_engine()
result = engine.calculate_risk(
    {
        "attack_category": "Normal",
        "ml_confidence": 0.0,
        "anomaly_score": 0.0,
        "event_frequency": 0.0,
        "source_reputation": 0.0,
    }
)
score_zero = result.risk_score if hasattr(result, "risk_score") else result
print("RISK_NORMAL_ZERO", score_zero)

sys.exit(1 if failures else 0)
