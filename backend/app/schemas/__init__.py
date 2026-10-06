"""Pydantic request/response schemas for the CyberShield AI API.

Grouped by endpoint family:

* :mod:`app.schemas.common` - pagination, filters, errors
* :mod:`app.schemas.events` - ``/api/events``
* :mod:`app.schemas.threats` - ``/api/threats``
* :mod:`app.schemas.alerts` - ``/api/alerts``
* :mod:`app.schemas.analytics` - ``/api/analytics/*``
* :mod:`app.schemas.ml` - ``/api/ml/*``
* :mod:`app.schemas.system` - ``/api/health``, ``/api/system/*``
* :mod:`app.schemas.simulation` - ``/api/simulation/*``
* :mod:`app.schemas.investigations` - ``/api/investigations``
"""

from app.schemas.alerts import (
    AlertCreate,
    AlertFilters,
    AlertList,
    AlertResponse,
    AlertStats,
    AlertStatusCount,
    AlertUpdate,
    normalize_alert_status,
)
from app.schemas.analytics import (
    AttackDistributionItem,
    AttackDistributionResponse,
    HeatmapResponse,
    HeatmapRow,
    ProtocolDistributionItem,
    ProtocolDistributionResponse,
    TimelinePoint,
    TimelineResponse,
    TopSourceItem,
    TopSourcesResponse,
)
from app.schemas.common import (
    ErrorDetail,
    ErrorResponse,
    FilterParams,
    PaginatedResponse,
    PaginationParams,
    SortOrder,
    SortParams,
    TimeRange,
    parse_time_range,
    window_started_at,
)
from app.schemas.events import NetworkEventList, NetworkEventResponse
from app.schemas.investigations import (
    InvestigationCreate,
    InvestigationDetail,
    InvestigationList,
    InvestigationResponse,
)
from app.schemas.ml import (
    ClassMetric,
    ConfidenceBucket,
    ConfusionMatrixResponse,
    FeatureImportanceItem,
    FeatureImportanceResponse,
    ModelInfo,
    ModelMetrics,
    PredictionItem,
    PredictionStats,
    PredictionsResponse,
)
from app.schemas.simulation import (
    SimulationControl,
    SimulationControlResponse,
    SimulationStatus,
)
from app.schemas.system import (
    HealthResponse,
    PipelineStage,
    PipelineStatus,
    ServiceHealth,
    SystemStatusResponse,
)
from app.schemas.threats import (
    ThreatDetail,
    ThreatFilters,
    ThreatInvestigationSummary,
    ThreatList,
    ThreatResponse,
)

__all__ = [
    # alerts
    "AlertCreate",
    "AlertFilters",
    "AlertList",
    "AlertResponse",
    "AlertStats",
    "AlertStatusCount",
    "AlertUpdate",
    "normalize_alert_status",
    # analytics
    "AttackDistributionItem",
    "AttackDistributionResponse",
    "HeatmapResponse",
    "HeatmapRow",
    "ProtocolDistributionItem",
    "ProtocolDistributionResponse",
    "TimelinePoint",
    "TimelineResponse",
    "TopSourceItem",
    "TopSourcesResponse",
    # common
    "ErrorDetail",
    "ErrorResponse",
    "FilterParams",
    "PaginatedResponse",
    "PaginationParams",
    "SortOrder",
    "SortParams",
    "TimeRange",
    "parse_time_range",
    "window_started_at",
    # events
    "NetworkEventList",
    "NetworkEventResponse",
    # investigations
    "InvestigationCreate",
    "InvestigationDetail",
    "InvestigationList",
    "InvestigationResponse",
    # ml
    "ClassMetric",
    "ConfidenceBucket",
    "ConfusionMatrixResponse",
    "FeatureImportanceItem",
    "FeatureImportanceResponse",
    "ModelInfo",
    "ModelMetrics",
    "PredictionItem",
    "PredictionStats",
    "PredictionsResponse",
    # simulation
    "SimulationControl",
    "SimulationControlResponse",
    "SimulationStatus",
    # system
    "HealthResponse",
    "PipelineStage",
    "PipelineStatus",
    "ServiceHealth",
    "SystemStatusResponse",
    # threats
    "ThreatDetail",
    "ThreatFilters",
    "ThreatInvestigationSummary",
    "ThreatList",
    "ThreatResponse",
]
