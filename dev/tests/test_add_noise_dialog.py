"""The Add noise window (app/data_operations/add_noise_dialog.py)."""
from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from app.data.sqlite_repo import SqliteRepo
from app.data_operations.add_noise_dialog import KIND_OF_MODEL, AddNoiseDialog


def _dialog(repo: SqliteRepo, **values: Any):
    repo.import_dataframe(__import__("pandas").DataFrame({"x": np.linspace(0, 10, 2000),
                                                           "y": 5 + np.sin(np.linspace(0, 20, 2000))}),
                          table_name="Data", normalize_columns=False)
    figure_id = repo.create_figure_descriptor(name="F")
    axis_id = repo.create_axis_descriptor(figure_id=figure_id, axis_index=0, chart_type="Scatter Plot", title="F",
                                          x_label="x", y_label="y", options={})
    repo.create_series_descriptor(axis_id=axis_id, series_index=0, name="Signal",
                                  sql_query='SELECT "x" AS x, "y" AS y FROM "Data"', roles={"x": "x", "y": "y"},
                                  style={})
    dialog = AddNoiseDialog(repo=repo, figure_id=figure_id, parent=None)
    dialog.series_selector.reload(select_all_series=True)
    dialog._parameter_form_spec.set_values(values)
    return dialog, axis_id


def _results(dialog: AddNoiseDialog) -> list[Any]:
    return list(dialog.compute_results())


def test_every_model_is_a_kind_the_engine_knows() -> None:
    from app.analysis import random_data as rd
    assert set(KIND_OF_MODEL.values()) == set(rd.NOISE_KINDS)


def test_the_window_adds_additive_noise_of_the_size_asked(qapp, repo: SqliteRepo) -> None:
    dialog, _axis = _dialog(repo, amount=0.3, seed=5)
    try:
        [result] = _results(dialog)
        assert result.noise.std() == pytest.approx(0.3, rel=0.1) and result.metadata["seed"] == 5
        again = _results(dialog)[0]
        assert np.array_equal(again.y, result.y)  # the same seed, the same noise
        assert "Signal" in dialog.format_results([result])
    finally:
        dialog.deleteLater()


def test_ok_draws_the_noisy_series_beside_the_original(qapp, repo: SqliteRepo) -> None:
    dialog, axis_id = _dialog(repo, amount=0.2, seed=2)
    try:
        dialog.ok()
    finally:
        dialog.deleteLater()
    names = [s["name"] for s in repo.get_series(axis_id)]
    assert "Signal" in names and len(names) >= 2


def test_each_kind_runs_through_the_window(qapp, repo: SqliteRepo) -> None:
    dialog, _axis = _dialog(repo, seed=1)
    try:
        for model, values in (("Proportional", {"amount": 0.1}), ("Growing with X", {"amount": 1.0, "power": 2.0}),
                              ("Outliers", {"amount": 6.0, "fraction": 0.1}), ("Random walk", {"amount": 0.1}),
                              ("Missing values", {"fraction": 0.2}), ("Additive", {"shape": "t", "df": 4.0}),
                              ("Additive", {"shape": "gamma", "shape_k": 3.0})):
            dialog.model_combo.setCurrentIndex(max(0, dialog.model_combo.findText(model)))
            dialog._parameter_form_spec.set_values(values)
            [result] = _results(dialog)
            assert len(result.y) == 2000, model
            if model == "Missing values":
                assert np.isnan(result.y).mean() == pytest.approx(0.2, abs=0.04)
    finally:
        dialog.deleteLater()


def test_a_signal_to_noise_amount_is_the_one_obtained(qapp, repo: SqliteRepo) -> None:
    dialog, _axis = _dialog(repo, amount_mode="snr", amount=15.0, seed=3)
    try:
        [result] = _results(dialog)
        assert result.snr_db == pytest.approx(15.0, abs=1.0)
        assert "15.0" in dialog.format_results([result]) or "14." in dialog.format_results([result])
    finally:
        dialog.deleteLater()


def test_two_series_get_independent_noise_or_the_same_noise_term(qapp, repo: SqliteRepo) -> None:
    dialog, axis_id = _dialog(repo, amount=0.5, seed=7)
    repo.create_series_descriptor(axis_id=axis_id, series_index=1, name="Other",
                                  sql_query='SELECT "x" AS x, "y" AS y FROM "Data"', roles={"x": "x", "y": "y"},
                                  style={})
    dialog.series_selector.reload(select_all_series=True)
    try:
        first, second = _results(dialog)
        assert not np.allclose(first.noise, second.noise)
        dialog._parameter_form_spec.set_values({"shared": True})
        first, second = _results(dialog)
        assert np.allclose(first.noise, second.noise)
    finally:
        dialog.deleteLater()
