"""A Partition model scores new rows the way its own report scored the training rows."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis import models
from app.analysis.partition import CONTINUOUS, NOMINAL, PartitionModel, PartitionSpec, partition
from app.data.sqlite_repo import SqliteRepo


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(11)
    n = 160
    x = rng.uniform(0, 10, n)
    group = rng.choice(["red", "green", "blue"], n)
    shift = pd.Series(group).map({"red": 0.0, "green": 4.0, "blue": 8.0}).to_numpy()
    mass = 2.0 * x + shift + rng.normal(0, 0.5, n)
    species = np.where(mass > 12, "big", np.where(mass > 6, "mid", "small"))
    return pd.DataFrame({"x": x, "group": group, "mass": mass, "species": species})


@pytest.mark.parametrize("method", ["tree", "forest", "boosted"])
def test_a_continuous_model_reproduces_the_reports_predictions(method) -> None:
    frame = _frame()
    spec = PartitionSpec(response="mass", factors=["x", "group"], kinds={"mass": CONTINUOUS, "x": CONTINUOUS,
                                                                         "group": NOMINAL},
                         splits=6, method=method, trees=20)
    result = partition(frame, spec)
    assert isinstance(result.model, PartitionModel)
    again = result.model.predict(frame)
    assert again.notes == []
    np.testing.assert_allclose(again.table["Prediction"].to_numpy(), result.predicted.reindex(frame.index).to_numpy())


@pytest.mark.parametrize("method", ["tree", "forest"])
def test_a_category_model_gives_the_same_classes_and_probabilities(method) -> None:
    frame = _frame()
    spec = PartitionSpec(response="species", factors=["x", "group"],
                         kinds={"species": NOMINAL, "x": CONTINUOUS, "group": NOMINAL}, splits=5, method=method,
                         trees=20)
    result = partition(frame, spec)
    table = result.model.predict(frame).table
    assert table["Prediction"].tolist() == result.predicted.reindex(frame.index).tolist()
    for column in result.probabilities.columns:
        np.testing.assert_allclose(table[column].to_numpy(), result.probabilities[column].reindex(frame.index).to_numpy())


def test_the_model_survives_the_project_and_meets_new_rows(tmp_path, monkeypatch) -> None:
    trusted: list[str] = []
    monkeypatch.setattr(models, "get_value", lambda key, default=None: list(trusted) if key == models.TRUST_KEY else default)
    monkeypatch.setattr(models, "set_value", lambda key, value: (trusted.clear(), trusted.extend(value)))
    frame = _frame()
    result = partition(frame, PartitionSpec(response="mass", factors=["x", "group"],
                                            kinds={"mass": CONTINUOUS, "x": CONTINUOUS, "group": NOMINAL}, splits=6))
    repo = SqliteRepo(db_path=tmp_path / "p.dhub")
    try:
        models.save_model(repo, "birds", result.model)
        new = pd.DataFrame({"x": [1.0, 5.0, np.nan, 3.0], "group": ["red", "blue", "green", "purple"]})
        prediction = models.predict_table(repo, "birds", new)
        assert prediction.table["Prediction"].notna().tolist() == [True, True, False, False]
        assert any("purple" in note for note in prediction.notes)
        reloaded = models.load_model(repo, "birds")
        assert reloaded.describe()["response"] == "mass" and reloaded.describe()["summary"]["Splits"] >= 1
    finally:
        repo.close()


def test_a_partition_model_is_fitted_kept_and_applied_through_the_api(qapp, tmp_path, monkeypatch) -> None:
    from app import analysis_api

    trusted: list[str] = []
    monkeypatch.setattr(models, "get_value", lambda key, default=None: list(trusted) if key == models.TRUST_KEY else default)
    monkeypatch.setattr(models, "set_value", lambda key, value: (trusted.clear(), trusted.extend(value)))
    repo = SqliteRepo(db_path=tmp_path / "api.dhub")
    try:
        repo.import_dataframe(_frame(), table_name="Birds", normalize_columns=False)
        analysis, _chart, model = analysis_api.make_callables(lambda: repo)
        result = analysis("Partition", "Birds", roles={"response": ["mass"], "factor": ["x", "group"]})
        assert result.fitted is not None and result.fitted.source_table == "Birds"
        result.save_model("birds_mass")
        handle = model("birds_mass")
        assert "partition of mass from x, group" in repr(handle)
        predicted = handle.predict("Birds", into="Birds_scored")
        assert predicted.attrs["notes"] == [] and len(predicted) == 160
        assert "Prediction" in repo.query_df('SELECT * FROM "Birds_scored"').columns
        with pytest.raises(analysis_api.AnalysisError, match="No model called"):
            model("nope")
    finally:
        repo.close()
