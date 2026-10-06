"""Risk Scoring Engine.

Computes a composite 0-100 risk score for a security event::

    risk = attack_severity  * 0.30
         + ml_confidence    * 0.25
         + anomaly_score    * 0.20
         + event_frequency  * 0.15
         + source_reputation* 0.10

where every input is normalized to ``[0, 1]`` before weighting:

* ``attack_severity`` - category weight (Normal=0, Probe=0.5, DoS=0.7,
  R2L=0.8, U2R=0.9; Unknown=0.6).
* ``ml_confidence`` - classifier confidence.
* ``anomaly_score`` - unsupervised detector score.
* ``event_frequency`` - events/minute normalized against
  :attr:`RiskScoringEngine.frequency_normalizer` (default 100).
* ``source_reputation`` - reputation *risk* weight (0 = clean, 1 = known
  malicious).

Risk bands (configurable):
``Low [0, 20)``, ``Guarded [20, 40)``, ``Medium [40, 60)``,
``High [60, 80)``, ``Critical [80, 100]``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

#: Category weight applied to the attack-severity component.
DEFAULT_SEVERITY_WEIGHTS: dict[str, float] = {
    "Normal": 0.0,
    "Probe": 0.5,
    "DoS": 0.7,
    "R2L": 0.8,
    "U2R": 0.9,
    "Unknown": 0.6,
}

#: Component weights - must sum to 1.0.
DEFAULT_COMPONENT_WEIGHTS: dict[str, float] = {
    "attack_severity": 0.30,
    "ml_confidence": 0.25,
    "anomaly_score": 0.20,
    "event_frequency": 0.15,
    "source_reputation": 0.10,
}

#: Band name -> exclusive upper bound (the last band is inclusive).
DEFAULT_BAND_THRESHOLDS: dict[str, float] = {
    "Low": 20.0,
    "Guarded": 40.0,
    "Medium": 60.0,
    "High": 80.0,
    "Critical": 100.0,
}

#: Band -> alert severity used when promoting to alerts.
BAND_TO_SEVERITY: dict[str, str] = {
    "Low": "info",
    "Guarded": "low",
    "Medium": "medium",
    "High": "high",
    "Critical": "critical",
}


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------


@dataclass
class RiskComponent:
    """One weighted component of the risk score."""

    name: str
    raw_value: float
    normalized_value: float
    weight: float
    contribution: float


@dataclass
class RiskResult:
    """Outcome of :meth:`RiskScoringEngine.calculate_risk`."""

    score: float
    band: str
    severity: str
    components: list[RiskComponent] = field(default_factory=list)
    explanation: str = ""

    def as_dict(self) -> dict[str, Any]:
        """JSON-friendly representation."""

        return {
            "score": self.score,
            "band": self.band,
            "severity": self.severity,
            "explanation": self.explanation,
            "components": [asdict(component) for component in self.components],
        }

    def top_factors(self, limit: int = 3) -> list[str]:
        """Names of the highest-contributing components."""

        ranked = sorted(self.components, key=lambda c: c.contribution, reverse=True)
        return [component.name for component in ranked[:limit] if component.contribution > 0]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class RiskScoringEngine:
    """Configurable implementation of the composite risk formula."""

    def __init__(
        self,
        *,
        component_weights: Mapping[str, float] | None = None,
        severity_weights: Mapping[str, float] | None = None,
        band_thresholds: Mapping[str, float] | None = None,
        frequency_normalizer: float = 100.0,
    ) -> None:
        self.component_weights = dict(DEFAULT_COMPONENT_WEIGHTS)
        if component_weights:
            self.component_weights.update(component_weights)
        total_weight = sum(self.component_weights.values())
        if total_weight <= 0:
            raise ValueError("component weights must sum to a positive value")
        # Normalize so custom weights always produce a 0-100 scale.
        self.component_weights = {
            key: value / total_weight for key, value in self.component_weights.items()
        }

        self.severity_weights = dict(DEFAULT_SEVERITY_WEIGHTS)
        if severity_weights:
            self.severity_weights.update(severity_weights)

        self.band_thresholds = dict(DEFAULT_BAND_THRESHOLDS)
        if band_thresholds:
            self.band_thresholds.update(band_thresholds)

        self.frequency_normalizer = max(1.0, float(frequency_normalizer))

    # ------------------------------------------------------------------ API

    def severity_weight(self, attack_category: str | None) -> float:
        """Category weight used in the attack-severity component."""

        if not attack_category:
            return 0.0
        # Accept both "DoS" and "dos" / enum instances.
        key = getattr(attack_category, "value", attack_category)
        key = str(key)
        if key in self.severity_weights:
            return self.severity_weights[key]
        for name, weight in self.severity_weights.items():
            if name.lower() == key.lower():
                return weight
        return self.severity_weights.get("Unknown", 0.6)

    def band_for(self, score: float) -> str:
        """Map a 0-100 score onto its band name."""

        for band, upper in sorted(self.band_thresholds.items(), key=lambda kv: kv[1]):
            if score < upper:
                return band
        return "Critical"

    def severity_for(self, score: float) -> str:
        """Map a 0-100 score onto the alert severity vocabulary."""

        return BAND_TO_SEVERITY.get(self.band_for(score), "info")

    def calculate_risk(
        self,
        event: Mapping[str, Any] | object | None = None,
        *,
        attack_category: str | None = None,
        ml_confidence: float | None = None,
        anomaly_score: float = 0.0,
        event_frequency: float = 0.0,
        source_reputation: float = 0.0,
    ) -> RiskResult:
        """Compute the composite risk score.

        ``event`` may be a mapping (or object with attributes) carrying any of
        ``attack_category``/``predicted_category``, ``confidence``/
        ``ml_confidence``, ``anomaly_score``, ``event_frequency`` and
        ``source_reputation``. Explicit keyword arguments take precedence.
        """

        if event is not None:
            attack_category = attack_category or _pick(
                event, "attack_category", "predicted_category", "category"
            )
            if ml_confidence is None:
                ml_confidence = _pick(event, "ml_confidence", "confidence") or 0.0
            anomaly_score = anomaly_score or float(_pick(event, "anomaly_score") or 0.0)
            event_frequency = event_frequency or float(
                _pick(event, "event_frequency", "events_per_minute") or 0.0
            )
            source_reputation = source_reputation or float(
                _pick(event, "source_reputation") or 0.0
            )

        severity_component = self.severity_weight(attack_category)
        confidence_component = _clamp01(ml_confidence if ml_confidence is not None else 0.0)
        anomaly_component = _clamp01(anomaly_score)
        frequency_component = _clamp01(float(event_frequency) / self.frequency_normalizer)
        reputation_component = _clamp01(source_reputation)

        components = [
            _component(
                name="attack_severity",
                raw=severity_component,
                normalized=severity_component,
                weight=self.component_weights["attack_severity"],
            ),
            _component(
                name="ml_confidence",
                raw=float(ml_confidence or 0.0),
                normalized=confidence_component,
                weight=self.component_weights["ml_confidence"],
            ),
            _component(
                name="anomaly_score",
                raw=float(anomaly_score),
                normalized=anomaly_component,
                weight=self.component_weights["anomaly_score"],
            ),
            _component(
                name="event_frequency",
                raw=float(event_frequency),
                normalized=frequency_component,
                weight=self.component_weights["event_frequency"],
            ),
            _component(
                name="source_reputation",
                raw=float(source_reputation),
                normalized=reputation_component,
                weight=self.component_weights["source_reputation"],
            ),
        ]

        score = round(min(100.0, max(0.0, sum(c.contribution for c in components))), 2)
        band = self.band_for(score)
        result = RiskResult(
            score=score,
            band=band,
            severity=BAND_TO_SEVERITY.get(band, "info"),
            components=components,
        )
        top = result.top_factors(2)
        result.explanation = (
            f"Risk {score:.1f}/100 ({band}) driven by "
            + " and ".join(top or ["no strong signal"])
            + f"; category={attack_category or 'Unknown'}, confidence={float(ml_confidence or 0.0):.2f}."
        )
        return result


def _component(*, name: str, raw: float, normalized: float, weight: float) -> RiskComponent:
    return RiskComponent(
        name=name,
        raw_value=round(float(raw), 4),
        normalized_value=round(float(normalized), 4),
        weight=round(float(weight), 4),
        contribution=round(float(normalized) * float(weight) * 100.0, 4),
    )


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _pick(source: Mapping[str, Any] | object, *names: str) -> Any:
    """Return the first present key/attribute from ``source`` (or ``None``)."""

    for name in names:
        if isinstance(source, Mapping):
            if name in source and source[name] is not None:
                return source[name]
        else:
            value = getattr(source, name, None)
            if value is not None:
                return value
    return None


#: Shared default engine (services reuse this instance).
risk_engine = RiskScoringEngine()


def get_risk_engine() -> RiskScoringEngine:
    """FastAPI-friendly accessor for the shared engine."""

    return risk_engine
