"""Series Regression kept as a model: it gives the curve's own values, and reads the series' x column of a table."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis import models
from app.analysis.regression import (
    KIND_GRADIENT_BOOSTING,
    KIND_HUBER,
    KIND_ISOTONIC,
    KIND_RANDOM_FOREST,
    KIND_RANSAC,
    RegressionModel,
    fit_regression,
)
from app.data.sqlite_repo import SqliteRepo
from app.data_operations.regression_dialog import source_names


@pytest.mark.parametrize("kind", [KIND_RANSAC, KIND_HUBER, KIND_ISOTONIC, KIND_RANDOM_FOREST, KIND_GRADIENT_BOOSTING])
def test_the_model_gives_the_values_of_the_curve_it_drew(kind: str) -> None:
    rng = np.random.default_rng(3)
    x = np.linspace(0.0, 10.0, 60)
    y = 2.0 * x + 1.0 + rng.normal(0.0, 0.3, x.size)
    fitted = fit_regression(kind, x, y)
    model = RegressionModel("mass", "length", fitted.estimator, kind)
    prediction = model.predict(pd.DataFrame({"length": fitted.x}))
    assert np.allclose(prediction.table["Prediction"].to_numpy(float), fitted.y)


def test_it_survives_the_project_and_counts_what_it_cannot_read(tmp_path, monkeypatch) -> None:
    trusted: list[str] = []
    monkeypatch.setattr(models, "get_value", lambda key, default=None: list(trusted) if key == models.TRUST_KEY else default)
    monkeypatch.setattr(models, "set_value", lambda key, value: (trusted.clear(), trusted.extend(value)))
    x = np.linspace(0.0, 10.0, 40)
    fitted = fit_regression(KIND_HUBER, x, 3.0 * x)
    repo = SqliteRepo(db_path=tmp_path / "r.dhub")
    try:
        models.save_model(repo, "mass_line", RegressionModel("mass", "length", fitted.estimator, KIND_HUBER))
        loaded = models.load_model(repo, "mass_line")
        prediction = loaded.predict(pd.DataFrame({"length": [1.0, None, 4.0]}))
        values = prediction.table["Prediction"]
        assert values.iloc[0] == pytest.approx(3.0, abs=1e-3) and values.iloc[2] == pytest.approx(12.0, abs=1e-3)
        assert pd.isna(values.iloc[1]) and prediction.notes
        with pytest.raises(models.ModelError):
            loaded.predict(pd.DataFrame({"other": [1.0]}))
    finally:
        repo.close()


def test_the_columns_of_a_series_query() -> None:
    assert source_names('SELECT "month" AS "x", "co2_ppm" AS "y", "_id" FROM "co2_mauna_loa" WHERE "Hide" = 0',
                        "CO2") == ("month", "co2_ppm", "co2_mauna_loa")
    assert source_names("SELECT t AS x, v AS y FROM runs", "v") == ("t", "v", "runs")
    # An expression has no column to ask a table for: the role's own name, and the series' for y.
    assert source_names('SELECT log("t") AS "x", "v" * 2 AS "y" FROM "runs"', "doubled") == ("x", "doubled", "runs")
