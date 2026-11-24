"""Regression: the arithmetic behind the Regression data operation.

Robust (RANSAC, Huber) and non-parametric (isotonic, random forest,
gradient boosting) regression of one series, predicted over a dense evenly
spaced grid across its own x range - so a forest does not read as a jagged
line through exactly the input points. Plain arrays in, no Qt, nothing
logged (todo R-01).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import HuberRegressor, RANSACRegressor

from app.analysis import NUMERICAL_FAILURES
from app.analysis.models import CONTINUOUS, PICKLED, Feature, SavedModel
from app.utils.config import get_constant

KIND_RANSAC = "ransac"
KIND_HUBER = "huber"
KIND_ISOTONIC = "isotonic"
KIND_RANDOM_FOREST = "random_forest"
KIND_GRADIENT_BOOSTING = "gradient_boosting"

#: Points in the dense evaluation grid every model predicts over.
GRID_POINTS = get_constant("regression_curve_points", 200)


@dataclass(frozen=True, slots=True)
class RegressionSettings:
    """What a model reads besides the data; each kind reads its own."""

    #: RANSAC: random subsets tried before the best is kept.
    max_trials: int = 100
    #: Huber: robustness/efficiency trade-off, and the ridge penalty.
    epsilon: float = 1.35
    alpha: float = 0.0001
    #: Isotonic: "auto", "true" (increasing) or "false" (decreasing).
    increasing: str = "auto"
    #: Forest and boosting: trees, depth (0 = the library's default) and, for
    #: boosting, the learning rate.
    n_estimators: int = 100
    max_depth: int = 0
    learning_rate: float = 0.1


@dataclass(frozen=True, slots=True)
class Regression:
    """The fitted curve over the grid, and what the fit can say about itself."""

    x: np.ndarray
    y: np.ndarray
    #: "inliers" (RANSAC), "outliers" (Huber), "r2" where the model scores.
    details: dict[str, Any] = field(default_factory=dict)
    #: The fitted scikit-learn estimator, for a model kept for later (RegressionModel).
    estimator: Any = None


def fit_regression(
    kind: str,
    x: np.ndarray,
    y: np.ndarray,
    settings: RegressionSettings | None = None,
) -> Regression:
    """Fit *kind* to ``(x, y)`` and predict it over :data:`GRID_POINTS` points."""
    settings = settings or RegressionSettings()
    x_grid = np.linspace(float(x.min()), float(x.max()), GRID_POINTS)
    details: dict[str, Any] = {}

    if kind == KIND_ISOTONIC:
        increasing: bool | str = (
            settings.increasing if settings.increasing == "auto" else settings.increasing == "true"
        )
        estimator = IsotonicRegression(increasing=increasing, out_of_bounds="clip")
        estimator.fit(x, y)
        return Regression(x_grid, np.asarray(estimator.predict(x_grid), dtype=float), details, estimator)

    features = x.reshape(-1, 1)
    features_grid = x_grid.reshape(-1, 1)

    if kind == KIND_RANSAC:
        estimator = RANSACRegressor(max_trials=int(settings.max_trials), random_state=0)
        estimator.fit(features, y)
        inlier_mask = getattr(estimator, "inlier_mask_", None)
        if inlier_mask is not None:
            details["inliers"] = f"{int(np.count_nonzero(inlier_mask))}/{inlier_mask.size}"

    elif kind == KIND_HUBER:
        estimator = HuberRegressor(epsilon=float(settings.epsilon), alpha=float(settings.alpha))
        estimator.fit(features, y)
        outliers = getattr(estimator, "outliers_", None)
        if outliers is not None:
            details["outliers"] = int(np.count_nonzero(outliers))

    elif kind == KIND_RANDOM_FOREST:
        estimator = RandomForestRegressor(
            n_estimators=int(settings.n_estimators),
            max_depth=int(settings.max_depth) or None,
            random_state=0,
        )
        estimator.fit(features, y)

    elif kind == KIND_GRADIENT_BOOSTING:
        estimator = GradientBoostingRegressor(
            n_estimators=int(settings.n_estimators),
            learning_rate=float(settings.learning_rate),
            max_depth=int(settings.max_depth) or 3,
            random_state=0,
        )
        estimator.fit(features, y)

    else:
        raise ValueError(f"Unsupported regression: {kind}")

    y_grid = estimator.predict(features_grid)
    try:
        details["r2"] = float(estimator.score(features, y))
    except NUMERICAL_FAILURES:  # a degenerate sample cannot be scored
        pass
    return Regression(x_grid, np.asarray(y_grid, dtype=float), details, estimator)


# ----------------------------------------------------------------------
# The model kept for later (ID01)
# ----------------------------------------------------------------------
@SavedModel.register
class RegressionModel(SavedModel):
    """A series' regression that scores new rows: y from one x column, by the estimator that drew the curve.

    A pickled kind (a scikit-learn estimator): kept in the project and run on a computer that trusts it. Outside
    the x range it was fitted on, an isotonic model holds its end value and a forest its last leaf; the linear
    ones (RANSAC, Huber) extend their line.
    """

    KIND = "series_regression"
    FORM = PICKLED

    def __init__(self, response: str, predictor: str, estimator: Any, kind: str, *,
                 summary: dict[str, Any] | None = None, source_table: str = "") -> None:
        super().__init__(response, [Feature(predictor, CONTINUOUS)], summary=summary, source_table=source_table)
        self.estimator = estimator
        self.kind = kind

    def predict_matrix(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(columns=["Prediction"])
        x = pd.to_numeric(frame[self.features[0].name], errors="coerce").to_numpy(dtype=float)
        values = self.estimator.predict(x if self.kind == KIND_ISOTONIC else x.reshape(-1, 1))
        return pd.DataFrame({"Prediction": np.asarray(values, dtype=float)}, index=frame.index)
