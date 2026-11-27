"""Tests of axes, one section per former file:

* axis_title_removed: An emptied Title field means no title - not the title the axis was created with.
* axis_legend: The axis' legend properties: hide, show, place, columns, title (Axis properties, Legend).
* axis_interval_render: Scale: Interval - a major tick every step on a linear axis; left automatic where a step means nothing.
* broken_axis: Broken axis: the gap between two values takes no room, its ticks are dropped, marks are drawn.
* secondary_axis: A secondary axis as the primary one in other units.
* reciprocal_scale: The 1/x axis scale (issue #9).
* fit_tick_labels: x labels that would overlap are wrapped or turned, and set back when there is room again.
"""
from __future__ import annotations

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
import matplotlib
import numpy as np
import pandas as pd
import pytest

from app.plugin_api.charts import render_figure as rf
from app.plugin_api.charts import secondary_axis
from app.plugin_api.charts.axis_options import axis_title
from app.plugin_api.charts.broken_axis import apply_breaks, parse_break
from app.plugin_api.charts.render_figure import _fit_x_tick_labels
from app.plugin_api.charts.render_figure import render_figure_from_descriptor


# --- axis_title_removed: An emptied Title field means no title - not the title the axis was created with.
def test_the_options_title_wins_even_empty() -> None:
    assert axis_title({"title": ""}, "Created") == ""
    assert axis_title({"title": " Mine "}, "Created") == "Mine"
    assert axis_title({}, "Created") == "Created"  # never edited: the descriptor's own
    assert axis_title({"label": "Old style"}, "Created") == "Old style"


def test_an_emptied_title_draws_none(qapp, repo) -> None:
    repo.import_dataframe(pd.DataFrame({"a": [1.0, 2.0]}), table_name="t", normalize_columns=False)
    figure_id = repo.create_figure_descriptor(name="f")
    axis_id = repo.create_axis_descriptor(figure_id=figure_id, axis_index=0, chart_type="Scatter Plot",
                                          title="Created", x_label="", y_label="", options={"title": ""})
    repo.create_series_descriptor(axis_id=axis_id, series_index=0, name="s", sql_query="SELECT a AS x, a AS y FROM t",
                                  roles={"x": "x", "y": "y"}, style={})
    figure = Figure()
    render_figure_from_descriptor(figure=figure, descriptor=repo.load_figure_descriptor(figure_id), repo=repo)
    assert figure.axes[0].get_title() == ""


# --- axis_legend: The axis' legend properties: hide, show, place, columns, title (Axis properties, Legend).
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from app.plugin_api.charts.render_figure import _apply_axis_legend


def test_axis_legend_options() -> None:
    figure, ax = plt.subplots()
    try:
        ax.plot([1, 2], label="a")
        ax.plot([2, 1], label="b")
        ax.legend()
        _apply_axis_legend(ax, {"legend_columns": 2, "legend_title": "T", "legend_frame": False})
        legend = ax.get_legend()
        assert legend.get_title().get_text() == "T" and [t.get_text() for t in legend.get_texts()] == ["a", "b"]
        _apply_axis_legend(ax, {"legend_show": "hide"})
        assert ax.get_legend() is None
        _apply_axis_legend(ax, {"legend_show": "show"})
        assert ax.get_legend() is not None
    finally:
        plt.close(figure)


def test_figure_sketch_is_applied() -> None:
    from types import SimpleNamespace

    from app.plugin_api.charts.render_figure import _apply_sketch

    figure, ax = plt.subplots()
    try:
        (line,) = ax.plot([1, 2])
        _apply_sketch(figure, SimpleNamespace(options={}))
        assert line.get_sketch_params() is None
        _apply_sketch(figure, SimpleNamespace(options={"sketch": "xkcd"}))
        assert line.get_sketch_params() == (1.0, 100.0, 2.0)
        assert ax.spines["left"].get_sketch_params() == (1.0, 100.0, 2.0)
    finally:
        plt.close(figure)


# --- axis_interval_render: Scale: Interval - a major tick every step on a linear axis; left automatic where a step means nothing.
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import MultipleLocator

from app.plugin_api.charts import axis_options
from app.plugin_api.charts.render_figure import _apply_intervals


def test_the_interval_is_read_as_a_positive_step() -> None:
    assert axis_options.manual_interval({"x_interval": "2.5"}, "x") == 2.5
    for no_step in (None, "", 0, -1, "ten", float("inf")):
        assert axis_options.manual_interval({"x_interval": no_step}, "x") is None
    assert axis_options.defaults()["y_interval"] is None


def test_ticks_every_interval_on_a_linear_axis() -> None:
    figure, ax = plt.subplots()
    ax.plot([0, 10], [0, 100])
    ax.set_xlim(0, 10)
    _apply_intervals(ax, {"x_interval": 2.5})
    assert isinstance(ax.xaxis.get_major_locator(), MultipleLocator)
    shown = [tick for tick in ax.get_xticks() if 0 <= tick <= 10]  # Matplotlib keeps one beyond each end
    assert np.allclose(shown, [0, 2.5, 5, 7.5, 10])
    assert not isinstance(ax.yaxis.get_major_locator(), MultipleLocator)  # y left automatic
    plt.close(figure)


def test_no_interval_on_a_log_axis_categories_or_too_many_ticks() -> None:
    figure, ax = plt.subplots()
    ax.bar(["a", "b", "c"], [1, 10, 100])
    ax.set_yscale("log")
    _apply_intervals(ax, {"x_interval": 1, "y_interval": 5})
    assert not isinstance(ax.xaxis.get_major_locator(), MultipleLocator)  # categories keep their ticks
    assert not isinstance(ax.yaxis.get_major_locator(), MultipleLocator)  # a log scale keeps its own
    plt.close(figure)

    figure, ax = plt.subplots()
    ax.set_xlim(0, 1e6)
    _apply_intervals(ax, {"x_interval": 1})  # a million ticks: left automatic
    assert not isinstance(ax.xaxis.get_major_locator(), MultipleLocator)
    plt.close(figure)


# --- broken_axis: Broken axis: the gap between two values takes no room, its ticks are dropped, marks are drawn.
def test_the_ends_are_read_in_either_spelling() -> None:
    assert parse_break("10, 90") == (10.0, 90.0)
    assert parse_break("1,5; 2,5") == (1.5, 2.5)
    assert parse_break("90, 10") is None and parse_break("") is None and parse_break("x") is None


def test_the_gap_takes_no_room_and_has_no_ticks() -> None:
    figure = Figure()
    ax = figure.add_subplot()
    ax.plot([0, 1, 2, 3], [1.0, 5.0, 101.0, 105.0])
    apply_breaks(ax, {"y_break": "10, 100"})
    figure.canvas.draw()
    to_pixels = ax.transData.transform
    # 5 -> 101 is as far as 1 -> 5 plus 1: the 90 between them is gone.
    gap = to_pixels((0, 101))[1] - to_pixels((0, 5))[1]
    unit = (to_pixels((0, 5))[1] - to_pixels((0, 1))[1]) / 4
    assert abs(gap - 6 * unit) < 1.0
    ticks = ax.yaxis.get_majorticklocs()
    assert not np.any((ticks > 10) & (ticks < 100))
    assert len(ax.lines) == 2  # the data and the marks


def test_a_log_axis_is_left_unbroken() -> None:
    figure = Figure()
    ax = figure.add_subplot()
    ax.plot([1, 2], [1.0, 100.0])
    ax.set_yscale("log")
    apply_breaks(ax, {"y_break": "10, 50", "y_scale": "log"})
    assert ax.get_yscale() == "log"


# --- secondary_axis: A secondary axis as the primary one in other units.
@pytest.mark.parametrize("key", list(secondary_axis.CONVERSIONS))
def test_every_conversion_round_trips(key: str) -> None:
    _label, forward, inverse, _caption = secondary_axis.CONVERSIONS[key]
    values = np.array([1.0, 20.0, 300.0])
    assert np.allclose(inverse(forward(values)), values)


def test_known_conversions() -> None:
    forward = secondary_axis.CONVERSIONS["degC_degF"][1]
    assert forward(100.0) == pytest.approx(212.0)
    assert secondary_axis.CONVERSIONS["nm_eV"][1](620.0) == pytest.approx(2.0, rel=1e-3)
    assert secondary_axis.CONVERSIONS["degC_K"][1](0.0) == pytest.approx(273.15)


def test_applied_once_per_render_and_replaced_on_a_redraw() -> None:
    ax = Figure().add_subplot()
    ax.plot([0, 100], [0, 1])
    options = {"secondary_x": "degC_degF", "secondary_y": "kg_lb"}
    secondary_axis.apply_secondary_axes(ax, options)
    secondary_axis.apply_secondary_axes(ax, options)
    assert len(ax._chartlibre_secondary_axes) == 2
    assert len([child for child in ax.child_axes]) == 2
    secondary_axis.apply_secondary_axes(ax, {})
    assert ax._chartlibre_secondary_axes == [] and not ax.child_axes


def test_a_polar_axes_refuses_and_is_left_alone() -> None:
    ax = Figure().add_subplot(projection="polar")
    secondary_axis.apply_secondary_axes(ax, {"secondary_x": "degC_degF"})
    assert ax._chartlibre_secondary_axes == []


# --- reciprocal_scale: The 1/x axis scale (issue #9).
def test_reciprocal_is_a_supported_scale_with_a_readable_label() -> None:
    assert "reciprocal" in rf.SUPPORTED_AXIS_SCALES
    assert rf.AXIS_SCALE_LABELS["reciprocal"] == "1/x"


def test_the_x_axis_maps_values_to_their_reciprocals_and_back() -> None:
    ax = Figure().subplots()
    ax.plot([1.0, 2.0, 4.0], [1.0, 2.0, 3.0])
    rf._apply_scales(ax, {"x_scale": "reciprocal"})
    transform = ax.xaxis.get_transform()
    np.testing.assert_allclose(transform.transform([1.0, 2.0, 4.0]), [1.0, 0.5, 0.25])
    np.testing.assert_allclose(transform.inverted().transform([1.0, 0.5, 0.25]), [1.0, 2.0, 4.0])


def test_zero_is_not_drawn_and_nothing_raises() -> None:
    ax = Figure().subplots()
    ax.plot([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    rf._apply_scales(ax, {"x_scale": "reciprocal", "y_scale": "reciprocal"})
    ax.figure.canvas.draw()  # a zero x or y must not break the draw


def test_the_other_scales_are_unchanged() -> None:
    ax = Figure().subplots()
    rf._apply_scales(ax, {"x_scale": "log", "y_scale": "symlog"})
    assert ax.get_xscale() == "log" and ax.get_yscale() == "symlog"


# --- fit_tick_labels: x labels that would overlap are wrapped or turned, and set back when there is room again.
_CAUSES = ["Solder bridge", "Missing component", "Misalignment", "Cold joint", "Wrong value",
           "Scratched surface", "Other"]


def _figure(width: float, labels: list[str]) -> tuple[Figure, object]:
    figure = Figure(figsize=(width, 4), dpi=100)
    FigureCanvasAgg(figure)
    ax = figure.add_subplot()
    ax.bar(labels, range(len(labels), 0, -1))
    return figure, ax


def _texts(ax) -> list[str]:
    return [label.get_text() for label in ax.get_xticklabels()]


def test_room_enough_leaves_them_level() -> None:
    figure, ax = _figure(14, _CAUSES)
    _fit_x_tick_labels(figure, ax, {})
    assert _texts(ax) == _CAUSES and not any(label.get_rotation() for label in ax.get_xticklabels())


def test_wrapped_at_the_spaces_then_turned_when_narrower() -> None:
    figure, ax = _figure(9.5, _CAUSES)
    _fit_x_tick_labels(figure, ax, {})
    assert "Solder\nbridge" in _texts(ax) and not any(label.get_rotation() for label in ax.get_xticklabels())
    figure, ax = _figure(4.5, _CAUSES)
    _fit_x_tick_labels(figure, ax, {})
    assert {label.get_rotation() for label in ax.get_xticklabels()} == {30.0}
    assert _texts(ax)[0] == "Solder bridge"


def test_a_resize_fits_them_again() -> None:
    figure, ax = _figure(4.5, _CAUSES)
    _fit_x_tick_labels(figure, ax, {})
    figure.set_size_inches(14, 4)
    from matplotlib.backend_bases import ResizeEvent
    ResizeEvent("resize_event", figure.canvas)._process()
    assert not any(label.get_rotation() for label in ax.get_xticklabels())


def test_a_chosen_angle_is_kept() -> None:
    figure, ax = _figure(4.5, _CAUSES)
    _fit_x_tick_labels(figure, ax, {"x_tick_rotation": 45})
    assert not any(label.get_rotation() for label in ax.get_xticklabels())
