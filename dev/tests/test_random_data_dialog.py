"""The Random data window (app/data_operations/random_data_dialog.py)."""
from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from app.analysis import random_data as rd
from app.data.sqlite_repo import SqliteRepo
from app.data_operations.random_data_dialog import CHARTS, RandomDataDialog, distribution_params


def _dialog(repo: SqliteRepo, **values: Any):
    figure_id = repo.create_figure_descriptor(name="F")
    axis_id = repo.create_axis_descriptor(figure_id=figure_id, axis_index=0, chart_type="Scatter Plot",
                                          title="F", x_label="x", y_label="y", options={})
    dialog = RandomDataDialog(repo=repo, figure_id=figure_id, parent=None)
    dialog._parameter_form_spec.set_values(values)
    dialog.chart_form.refresh_visibility()  # what the window does when the layout is changed
    return dialog, axis_id


def test_every_distribution_has_a_row_for_each_parameter_shown_only_while_it_is_chosen() -> None:
    params = distribution_params()
    by_name = {p.name: p for p in params}
    assert len(params) == sum(len(d.parameters) for d in rd.DISTRIBUTIONS.values())
    assert by_name["sd__normal"].visible_for["dist"] == ("normal",)
    second = {p.name: p for p in distribution_params(1)}["sd__normal__2"]
    assert second.visible_for == {"layout": ("XY", "XYZ"), "dist_2": ("normal",)}
    assert by_name["n__binomial"].minimum == 1 and by_name["p__binomial"].maximum <= 1.0
    assert by_name["sd__normal"].minimum > 0  # a scale is above zero, not zero


def test_the_window_draws_the_distribution_chosen_with_its_parameters(qapp, repo: SqliteRepo) -> None:
    dialog, _axis = _dialog(repo, dist="normal", mean__normal=50.0, sd__normal=2.0, n=4000, seed=7)
    try:
        [result] = dialog.compute_results()
        values = result.to_df()["X"].to_numpy()
        assert len(values) == 4000 and abs(values.mean() - 50) < 0.2 and abs(values.std() - 2) < 0.2
        assert result.generated.seed == 7 and result.check is not None
        again = dialog.compute_results()[0].to_df()
        assert again.equals(result.to_df())  # the same seed, the same numbers
    finally:
        dialog.deleteLater()


def test_a_seed_left_at_random_is_drawn_once_and_kept_until_a_setting_changes(qapp, repo: SqliteRepo) -> None:
    dialog, _axis = _dialog(repo, dist="uniform", n=100, seed=0)
    try:
        first = dialog.compute_results()[0]
        assert first.generated.seed > 0
        assert dialog.compute_results()[0].to_df().equals(first.to_df())  # Preview and OK agree
        dialog._parameter_form_spec.field("n").setValue(101)  # a change: a new seed
        assert dialog.compute_results()[0].generated.seed != first.generated.seed
    finally:
        dialog.deleteLater()


def test_a_line_has_an_even_x_a_random_y_and_its_trend_is_checked(qapp, repo: SqliteRepo) -> None:
    dialog, _axis = _dialog(repo, layout="LINE", dist="normal", x_start=0.0, x_stop=10.0, x_points=400,
                            trend_a=1.0, trend_b=2.0, seed=3)
    try:
        [result] = dialog.compute_results()
        table = result.to_df()
        assert list(table.columns) == ["X", "Y"] and len(table) == 400 and table["X"].iloc[-1] == 10
        assert np.polyfit(table["X"], table["Y"], 1) == pytest.approx([2.0, 1.0], abs=0.3)
        assert [r["test"][:5] for r in result.check.extra] == ["Slope", "Inter"]
    finally:
        dialog.deleteLater()


def test_the_report_gives_the_verdict_the_seed_and_the_tests(qapp, repo: SqliteRepo) -> None:
    dialog, _axis = _dialog(repo, dist="exponential", n=1500, seed=5)
    try:
        text = dialog.result_section(dialog.compute_results()[0])
        for word in ("Seed", "Exponential", "tests were run", "Kolmogorov-Smirnov", "Wald-Wolfowitz",
                     "Shapiro-Wilk", "Moments".lower(), "Skewness"):
            assert word in text, word
    finally:
        dialog.deleteLater()


def test_a_table_too_big_to_check_is_not_and_says_so(qapp, repo: SqliteRepo) -> None:
    dialog, _axis = _dialog(repo, dist="normal", n=100_001, seed=1)
    try:
        [result] = dialog.compute_results()
        assert result.check is None and "not checked" in result.notes[0]
        assert "not checked" in dialog.result_section(result)
    finally:
        dialog.deleteLater()


def test_ok_writes_the_table_and_draws_a_histogram_of_one_column(qapp, repo: SqliteRepo) -> None:
    dialog, _axis = _dialog(repo, dist="gamma", n=500, seed=2, check=False)
    before = set(repo.list_table_names())
    try:
        dialog.ok()
    finally:
        dialog.deleteLater()
    [table] = set(repo.list_table_names()) - before
    assert table.startswith("_") and len(repo.query_df(f'SELECT * FROM "{table}"')) == 500
    drawn = [a for a in _all_axes(repo) if a["chart_type"] == "Histogram"]
    assert len(drawn) == 1
    [one] = repo.get_series(drawn[0]["id"])
    assert repo.query_df(one["sql_query"])["value"].notna().all()


def test_ok_draws_a_scatter_of_y_against_x_for_a_line(qapp, repo: SqliteRepo) -> None:
    dialog, _axis = _dialog(repo, layout="LINE", dist="laplace", x_points=50, seed=4, check=False)
    try:
        dialog.ok()
    finally:
        dialog.deleteLater()
    drawn = [a for a in _all_axes(repo) if a["chart_type"] == "Scatter Plot" and repo.get_series(a["id"])]
    assert len(drawn) == 1
    frame = repo.query_df(repo.get_series(drawn[0]["id"])[0]["sql_query"])
    assert list(frame.columns) == ["x", "y"] and len(frame) == 50


def test_cancel_after_a_preview_takes_everything_back(qapp, repo: SqliteRepo) -> None:
    dialog, _axis = _dialog(repo, dist="normal", n=50, seed=1, check=False)
    before, axes_before = set(repo.list_table_names()), len(_all_axes(repo))
    try:
        dialog.preview()
        assert len(_all_axes(repo)) > axes_before
        dialog.close()
    finally:
        dialog.deleteLater()
    assert set(repo.list_table_names()) == before and len(_all_axes(repo)) == axes_before


def _all_axes(repo: SqliteRepo) -> list[dict[str, Any]]:
    frame = repo.query_df("SELECT id, chart_type FROM __axis_descriptors__")
    return frame.to_dict("records")


def test_ok_is_recorded_in_the_projects_history_with_the_seed_in_the_report(qapp, repo: SqliteRepo) -> None:
    dialog, _axis = _dialog(repo, dist="poisson", n=300, seed=11)
    try:
        dialog.ok()
    finally:
        dialog.deleteLater()
    [record] = repo.operations()
    assert record.operation == "Random data"
    assert "11" in record.report and "Poisson" in record.report


def test_two_columns_take_their_own_distribution_and_the_correlation_asked(qapp, repo: SqliteRepo) -> None:
    dialog, _axis = _dialog(repo, layout="XY", dist="normal", dist_2="exponential", scale__exponential__2=3.0,
                            corr=0.6, n=3000, seed=9)
    try:
        [result] = dialog.compute_results()
        table = result.to_df()
        assert list(table.columns) == ["X", "Y"] and abs(table["Y"].mean() - 3.0) < 0.3
        assert result.correlation == 0.6 and len(result.check.pairs) == 1
        assert result.check.pairs[0].requested == 0.6
        text = dialog.result_section(result)
        assert "X / Y" in text and "Spearman against the one asked" in text and "Correlation" in text
    finally:
        dialog.deleteLater()


def test_three_columns_take_the_three_correlations_and_refuse_an_impossible_set(qapp, repo: SqliteRepo) -> None:
    dialog, _axis = _dialog(repo, layout="XYZ", dist="normal", dist_2="uniform", dist_3="normal", n=4000, seed=2,
                            corr_xy=0.5, corr_xz=-0.3, corr_yz=0.2)
    try:
        [result] = dialog.compute_results()
        assert list(result.to_df().columns) == ["X", "Y", "Z"] and len(result.check.pairs) == 3
        assert result.check.pairs[1].requested == -0.3
        dialog._parameter_form_spec.set_values({"corr_xy": 0.9, "corr_xz": -0.9, "corr_yz": 0.9})
        with pytest.raises(ValueError, match="positive definite"):
            dialog.compute_results()
    finally:
        dialog.deleteLater()


def test_a_grid_is_noise_on_a_function_and_is_drawn_as_a_surface(qapp, repo: SqliteRepo) -> None:
    dialog, _axis = _dialog(repo, layout="GRID", dist="normal", sd__normal=0.1, x_points=20, y_points=15,
                            x_start=0.0, x_stop=1.0, y_start=0.0, y_stop=1.0, function="x + 2*y", seed=3)
    try:
        [result] = dialog.compute_results()
        table = result.to_df()
        assert list(table.columns) == ["X", "Y", "Z"] and len(table) == 300
        assert (table["Z"] - table["X"] - 2 * table["Y"]).std() == pytest.approx(0.1, rel=0.2)
        assert result.expression == "x + 2*y" and result.check.extra[0]["test"].startswith("Moran")
        assert "x + 2*y" in dialog.result_section(result) and "Neighbouring cells" in dialog.result_section(result)
        dialog.ok()
    finally:
        dialog.deleteLater()
    surfaces = [a for a in _all_axes(repo) if a["chart_type"] == "Surface Plot"]
    assert len(surfaces) == 1
    frame = repo.query_df(repo.get_series(surfaces[0]["id"])[0]["sql_query"])
    assert list(frame.columns) == ["x", "y", "z"] and len(frame) == 300


def test_a_wrong_function_is_refused_in_words(qapp, repo: SqliteRepo) -> None:
    dialog, _axis = _dialog(repo, layout="GRID", function="__import__('os').system('x')", check=False)
    try:
        with pytest.raises(ValueError, match="not allowed|not a function|not known"):
            dialog.compute_results()
    finally:
        dialog.deleteLater()


def test_ok_draws_two_and_three_columns_as_a_scatter_of_the_first_two(qapp, repo: SqliteRepo) -> None:
    for layout in ("XY", "XYZ"):
        dialog, _axis = _dialog(repo, layout=layout, n=80, seed=1, check=False)
        try:
            dialog.ok()
        finally:
            dialog.deleteLater()
    scatters = [a for a in _all_axes(repo) if a["chart_type"] == "Scatter Plot" and repo.get_series(a["id"])]
    assert len(scatters) == 2
    assert all(len(repo.query_df(repo.get_series(a["id"])[0]["sql_query"])) == 80 for a in scatters)


def _drawn_types(repo: SqliteRepo) -> list[str]:
    return sorted(a["chart_type"] for a in _all_axes(repo) if repo.get_series(a["id"]))


def test_each_layout_draws_its_own_panels(qapp, repo: SqliteRepo) -> None:
    expected = {
        "X": ["ECDF", "Histogram", "Q-Q Plot"],
        "XY": ["Joint Plot", "Scatter Plot"],
        "XYZ": ["Pair Plot", "Scatter Plot"],
        "LINE": ["Histogram", "Scatter Plot"],
        "GRID": ["Contour Plot", "Histogram", "Surface Plot"],
    }
    for layout, types in expected.items():
        dialog, _axis = _dialog(repo, layout=layout, n=60, x_points=12, y_points=8, seed=1, check=False)
        shown = sorted(c for c, _on, layouts in CHARTS if layout in layouts and dialog.chart_enabled(c))
        try:
            assert shown == types, layout
            panels = dialog.panels_for("T", dialog.compute_results()[0])
            assert sorted(p[0] for p in panels if dialog.chart_enabled(p[0])) == types, layout
        finally:
            dialog.deleteLater()


def test_a_chart_cleared_in_the_charts_tab_is_not_drawn_and_the_histogram_carries_its_curve(qapp, repo) -> None:
    dialog, _axis = _dialog(repo, dist="normal", n=200, seed=1, check=False)
    dialog.chart_form.field("Q-Q Plot").setChecked(False)
    dialog.chart_form.field("ECDF").setChecked(False)
    try:
        panels = dialog.panels_for("T", dialog.compute_results()[0])
        hist = next(p for p in panels if p[0] == "Histogram")
        assert hist[5]["distribution_fit"] == "norm"
        dialog.ok()
    finally:
        dialog.deleteLater()
    assert _drawn_types(repo) == ["Histogram"]


def test_a_discrete_distribution_has_no_fitted_curve_or_quantile_plot(qapp, repo: SqliteRepo) -> None:
    dialog, _axis = _dialog(repo, dist="poisson", n=100, seed=1, check=False)
    try:
        panels = dialog.panels_for("T", dialog.compute_results()[0])
        assert "Q-Q Plot" not in [p[0] for p in panels]
        assert "distribution_fit" not in next(p for p in panels if p[0] == "Histogram")[5]
    finally:
        dialog.deleteLater()


def test_repeat_draws_many_samples_and_shows_how_the_p_values_are_spread(qapp, repo: SqliteRepo) -> None:
    dialog, _axis = _dialog(repo, dist="normal", n=300, seed=10, repeat=30)
    try:
        [result] = dialog.compute_results()
        assert result.repeated is not None and result.repeated.repeats == 30
        assert result.generated.seed == 10  # the table shown is the first sample
        assert 0.0 < result.repeated.rejection_rate() < 0.2
        text = dialog.result_section(result)
        assert "30 samples were drawn (seeds 10 to 39)" in text and "Spread evenly" in text
        dialog.ok()
    finally:
        dialog.deleteLater()
    assert any(t.endswith("_P") for t in repo.list_table_names())
    assert _drawn_types(repo).count("Histogram") == 2
