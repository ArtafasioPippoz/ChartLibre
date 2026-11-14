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


def test_the_predict_dialog_writes_a_new_table_and_counts_what_it_could_not_read(qapp, tmp_path, monkeypatch) -> None:
    from app.dialogs.predict_dialog import PredictDialog

    trusted: list[str] = []
    monkeypatch.setattr(models, "get_value", lambda key, default=None: list(trusted) if key == models.TRUST_KEY else default)
    monkeypatch.setattr(models, "set_value", lambda key, value: (trusted.clear(), trusted.extend(value)))
    frame = _frame()
    result = partition(frame, PartitionSpec(response="mass", factors=["x", "group"],
                                            kinds={"mass": CONTINUOUS, "x": CONTINUOUS, "group": NOMINAL}, splits=6))
    repo = SqliteRepo(db_path=tmp_path / "d.dhub")
    try:
        repo.import_dataframe(frame, table_name="Birds", normalize_columns=False)
        new = pd.DataFrame({"x": [1.0, 2.0, np.nan], "group": ["red", "blue", "green"]})
        repo.import_dataframe(new, table_name="Fresh", normalize_columns=False)
        models.save_model(repo, "birds", result.model)
        dialog = PredictDialog(repo, None, table="Fresh")
        assert dialog._apply.isEnabled() and "Reads: x, group" in dialog._about.text()
        assert dialog._name_edit.text() == "Fresh_birds"
        dialog.apply()
        written = repo.query_df('SELECT * FROM "Fresh_birds"')
        assert list(written.columns)[-1] == "Prediction" and len(written) == 3
        assert written["Prediction"].notna().tolist() == [True, True, False]
        assert dialog.created_table_name == "Fresh_birds" and "missing value" in dialog._result.text()
        dialog._table_combo.setCurrentIndex(dialog._table_combo.findData("Birds"))
        assert dialog._apply.isEnabled()  # Birds has x and group too
        dialog.done(0)
    finally:
        repo.close()


def test_the_predict_dialog_says_what_the_table_lacks(qapp, tmp_path, monkeypatch) -> None:
    from app.dialogs.predict_dialog import PredictDialog

    trusted: list[str] = []
    monkeypatch.setattr(models, "get_value", lambda key, default=None: list(trusted) if key == models.TRUST_KEY else default)
    monkeypatch.setattr(models, "set_value", lambda key, value: (trusted.clear(), trusted.extend(value)))
    frame = _frame()
    result = partition(frame, PartitionSpec(response="mass", factors=["x", "group"],
                                            kinds={"mass": CONTINUOUS, "x": CONTINUOUS, "group": NOMINAL}, splits=4))
    repo = SqliteRepo(db_path=tmp_path / "e.dhub")
    try:
        repo.import_dataframe(pd.DataFrame({"x": [1.0]}), table_name="Short", normalize_columns=False)
        models.save_model(repo, "birds", result.model)
        dialog = PredictDialog(repo, None)
        assert not dialog._apply.isEnabled() and "Missing in the table: group" in dialog._about.text()
        dialog.done(0)
    finally:
        repo.close()


def test_save_as_model_keeps_what_the_window_fitted(qapp, tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QInputDialog

    from app import analysis_api

    trusted: list[str] = []
    monkeypatch.setattr(models, "get_value", lambda key, default=None: list(trusted) if key == models.TRUST_KEY else default)
    monkeypatch.setattr(models, "set_value", lambda key, value: (trusted.clear(), trusted.extend(value)))
    repo = SqliteRepo(db_path=tmp_path / "s.dhub")
    try:
        repo.import_dataframe(_frame(), table_name="Birds", normalize_columns=False)
        dialog, _name, _casting = analysis_api._filled_dialog(
            repo, "Partition", "Birds", {"response": ["mass"], "factor": ["x", "group"]}, {}, "", "new_figure",
            lambda: None)
        assert type(dialog).__name__ == "PartitionDialog" and not dialog._save_model_button.isEnabled()
        result = partition(_frame(), PartitionSpec(response="mass", factors=["x"], kinds={"mass": CONTINUOUS,
                                                                                         "x": CONTINUOUS}))
        dialog.format_results(result)
        assert dialog._save_model_button.isEnabled()
        monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("mine", True)))
        dialog.save_model()
        assert [row["name"] for row in repo.models()] == ["mine"]
        dialog.close()
    finally:
        repo.close()


def test_a_least_squares_model_reproduces_the_fit_and_gives_an_interval(tmp_path, monkeypatch) -> None:
    from app.analysis import linear_model as lm

    frame = _frame()
    factors = [lm.Factor("x", CONTINUOUS), lm.Factor("group", NOMINAL)]
    spec = lm.ModelSpec(factors=factors, responses=["mass"], terms=lm.main_effects(factors))
    fit = lm.fit_models(frame, spec)[0]
    assert fit.model is not None and fit.model.KIND == "linear"
    again = fit.model.predict(frame)
    assert again.notes == []
    np.testing.assert_allclose(again.table["Prediction"].to_numpy(), fit.predicted.reindex(frame.index).to_numpy())
    assert (again.table["Lower (95%)"] < again.table["Prediction"]).all()
    assert (again.table["Upper (95%)"] > again.table["Prediction"]).all()
    new = pd.DataFrame({"x": [2.0, 7.0], "group": ["red", "purple"]})
    table = fit.model.predict(new).table
    assert table["Prediction"].notna().tolist() == [True, False]

    trusted: list[str] = []
    monkeypatch.setattr(models, "get_value", lambda key, default=None: list(trusted) if key == models.TRUST_KEY else default)
    monkeypatch.setattr(models, "set_value", lambda key, value: (trusted.clear(), trusted.extend(value)))
    repo = SqliteRepo(db_path=tmp_path / "l.dhub")
    try:
        models.save_model(repo, "lin", fit.model)
        reloaded = models.load_model(repo, "lin")
        np.testing.assert_allclose(reloaded.predict(frame).table["Prediction"].to_numpy(),
                                   again.table["Prediction"].to_numpy())
    finally:
        repo.close()


def test_a_pls_model_reproduces_its_predictions() -> None:
    from app.analysis.pls import pls

    rng = np.random.default_rng(5)
    x = rng.normal(size=(80, 6))
    y = x @ np.array([1.0, 0.5, 0.0, 0.0, -1.0, 2.0]) + rng.normal(0, 0.1, 80)
    frame = pd.DataFrame(x, columns=[f"w{i}" for i in range(6)])
    frame["y"] = y
    result = pls(frame, ["y"], [f"w{i}" for i in range(6)], components=3)
    again = result.model.predict(frame)
    assert again.notes == []
    np.testing.assert_allclose(again.table["Prediction"].to_numpy(), result.predicted["Predicted y"].to_numpy())
    new = frame.drop(columns="y").copy()
    new.loc[0, "w1"] = np.nan
    assert result.model.predict(new).table["Prediction"].isna().tolist()[:2] == [True, False]
