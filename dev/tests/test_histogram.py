"""Tests of histogram, one section per former file:

* histogram_fit_cleared: A fit cleared in the axis' properties stays cleared, though a report figure stored it in the axis' own options.
* histogram_binning: Histogram bin methods: a typed count, or NumPy's rules worked out once over every data set.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.charts.histogram import BIN_METHODS, MAX_BINS, shared_bins
from app.charts.histogram import HistogramAxisRenderer
from app.data.sqlite_repo import SqliteRepo
from app.widgets.chart_properties.axis_properties import AxisPropertiesWidget


# --- histogram_fit_cleared: A fit cleared in the axis' properties stays cleared, though a report figure stored it in the axis' own options.
def _report_histogram(repo: SqliteRepo) -> tuple[int, int]:
    """A histogram as Distribution draws one: its fit in the axis' own options, not in axis_kwargs."""
    figure_id = int(repo.create_figure_descriptor(name="Distribution"))
    axis_id = int(repo.create_axis_descriptor(figure_id=figure_id, axis_index=0, chart_type="Histogram",
                                              title="", x_label="", y_label="",
                                              options={"distribution_fit": "norm"}))
    return figure_id, axis_id


def test_clearing_the_fit_does_not_bring_the_normal_back(qapp, repo: SqliteRepo) -> None:
    figure_id, axis_id = _report_histogram(repo)
    widget = AxisPropertiesWidget()
    try:
        widget.set_connected_figure(repo, figure_id, None)
        widget.rebuild_kwargs_editor(axis_id)
        editor = widget._kwargs_editor
        assert editor is not None and editor.value_for_key("distribution_fit") == "norm"  # shown as drawn
        editor.set_value_for_key("distribution_fit", "")  # the empty choice: no fit
        kwargs = widget.clean_kwargs()
        assert kwargs["distribution_fit"] == ""  # said explicitly, so the stored "norm" is not read
        options = {**(repo.get_axis_options(axis_id) or {}), "axis_kwargs": kwargs}
        assert HistogramAxisRenderer().opt("distribution_fit", options) == ""  # nothing to draw
    finally:
        widget.deleteLater()


def test_an_empty_value_with_nothing_stored_is_still_left_out(qapp, repo: SqliteRepo) -> None:
    figure_id = int(repo.create_figure_descriptor(name="Plain"))
    axis_id = int(repo.create_axis_descriptor(figure_id=figure_id, axis_index=0, chart_type="Histogram",
                                              title="", x_label="", y_label="", options={}))
    widget = AxisPropertiesWidget()
    try:
        widget.set_connected_figure(repo, figure_id, None)
        widget.rebuild_kwargs_editor(axis_id)
        assert widget._kwargs_editor is not None
        widget._kwargs_editor.set_value_for_key("distribution_fit", "")
        assert "distribution_fit" not in widget.clean_kwargs()
    finally:
        widget.deleteLater()


# --- histogram_binning: Histogram bin methods: a typed count, or NumPy's rules worked out once over every data set.
RNG = np.random.default_rng(7)
A = RNG.normal(0, 1, 500)
B = RNG.normal(2, 1, 300)


def test_count_is_the_typed_number_and_the_default() -> None:
    assert shared_bins([A, B], "count", 20, None) == 20
    assert shared_bins([A, B], "count", 5000, None) == MAX_BINS  # never more than the most


@pytest.mark.parametrize("method", [m for m, estimator in BIN_METHODS.items() if estimator])
def test_each_rule_gives_numpys_edges_over_all_the_values(method: str) -> None:
    edges = shared_bins([A, B], method, 20, None)
    expected = np.histogram_bin_edges(np.concatenate([A, B]), bins=BIN_METHODS[method])
    assert isinstance(edges, np.ndarray) and np.allclose(edges, expected)


def test_the_rules_follow_the_range_and_nothing_breaks_on_too_little_data() -> None:
    edges = shared_bins([A, B], "freedman-diaconis", 20, (0.0, 2.0))
    assert edges[0] == 0.0 and edges[-1] == 2.0
    assert shared_bins([np.array([3.0, 3.0, 3.0])], "scott", 12, None) == 12  # no spread: the count
    assert shared_bins([np.array([1.0])], "auto", 12, None) == 12
    assert shared_bins([A], "no such rule", 12, None) == 12


def test_a_rule_asking_for_too_many_bins_is_capped() -> None:
    spike = np.concatenate([np.zeros(10_000), np.linspace(0, 1e6, 50)])  # IQR nearly zero: tiny bins
    edges = shared_bins([spike], "freedman-diaconis", 20, None)
    assert isinstance(edges, np.ndarray) and edges.size - 1 <= MAX_BINS


def test_the_renderer_draws_with_a_rule(qapp=None) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from app.charts.histogram import HistogramAxisRenderer
    from app.data.series_frame import SeriesFrame
    from app.plugin_api.charts.base import SeriesData

    figure, ax = plt.subplots()
    series = SeriesData(name="a", df=SeriesFrame({"value": A}), style={})
    HistogramAxisRenderer().render_axis(ax, [series], {"axis_kwargs": {"bin_method": "sturges"}})
    bars = [patch for patch in ax.patches]
    assert len(bars) == np.histogram_bin_edges(A, bins="sturges").size - 1
    plt.close(figure)
