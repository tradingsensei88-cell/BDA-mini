"""ML intelligence routes.

Serve the trained model's identity, evaluation metrics, feature importance,
confusion matrix and live prediction statistics. Falls back to built-in
sample data when ``ml/models/*.json`` artifacts are not present, so the
dashboard always renders.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import MLDep
from app.schemas.ml import (
    ConfusionMatrixResponse,
    FeatureImportanceResponse,
    ModelInfo,
    ModelMetrics,
    PredictionsResponse,
)

router = APIRouter(tags=["ml"])


@router.get(
    "/model",
    response_model=ModelInfo,
    summary="Model information",
    description="Name, version, algorithm, training dataset, classes and input feature names.",
)
async def model_info(ml: MLDep) -> ModelInfo:
    return ModelInfo.model_validate(ml.get_model_info())


@router.get(
    "/metrics",
    response_model=ModelMetrics,
    summary="Model metrics",
    description=(
        "Global accuracy / precision / recall / F1 plus per-class metrics "
        "derived from the confusion matrix (kept internally consistent)."
    ),
)
async def model_metrics(ml: MLDep) -> ModelMetrics:
    return ModelMetrics.model_validate(ml.get_metrics())


@router.get(
    "/feature-importance",
    response_model=FeatureImportanceResponse,
    summary="Feature importance",
    description="Ranked NSL-KDD feature importances (normalized to sum to 1) with feature families.",
)
async def feature_importance(
    ml: MLDep,
    limit: int | None = Query(
        default=None, ge=1, le=41, description="Return only the top-N features."
    ),
) -> FeatureImportanceResponse:
    return FeatureImportanceResponse.model_validate(ml.get_feature_importance(limit=limit))


@router.get(
    "/confusion-matrix",
    response_model=ConfusionMatrixResponse,
    summary="Confusion matrix",
    description="5x5 confusion matrix (Normal/DoS/Probe/R2L/U2R): raw counts + row-normalized.",
)
async def confusion_matrix(ml: MLDep) -> ConfusionMatrixResponse:
    return ConfusionMatrixResponse.model_validate(ml.get_confusion_matrix())


@router.get(
    "/predictions",
    response_model=PredictionsResponse,
    summary="Recent predictions",
    description=(
        "Most recent model predictions with aggregate statistics and a "
        "per-class confidence histogram."
    ),
)
async def predictions(
    ml: MLDep,
    limit: int = Query(50, ge=1, le=200, description="Number of recent predictions."),
) -> PredictionsResponse:
    return PredictionsResponse.model_validate(ml.get_predictions(limit=limit))
