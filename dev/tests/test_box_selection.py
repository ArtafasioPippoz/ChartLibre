"""Tests of box selection, one section per former file:

* box_selects_dated_lines: A box on a Time Series selects the rows of the dates it covers: its line is read in the units its axis draws.
* box_selection_follows_the_pointer: A box selection is drawn without redrawing the figure, and ends at the edge of its chart when the pointer leaves it.
* box_follows_style: boxplot.notch, showmeans and meanline in a style reach the box plot.
* box_series_style: A box plot series: its Line style draws the box's lines, its Marker style the outliers.
"""
from __future__ import annotations

from types import SimpleNamespace

from matplotlib.dates import date2num
from matplotlib.figure import Figure
import matplotlib
import numpy as np
import pandas as pd

from app.charts.box import BoxAxisRenderer
from app.data.sqlite_repo import SqliteRepo
from app.plugin_api.charts.kwarg_spec import DEFAULT
from app.widgets.chart_panel import ChartPanel


# --- box_selects_dated_lines: A box on a Time Series selects the rows of the dates it covers: its line is read in the units its axis draws.
def test_a_box_on_dated_points_selects_their_rows_and_show_only_draws_them(qapp, tmp_path) -> None:
    repo = SqliteRepo(db_path=tmp_path / "dates.dhub")
    dates = pd.date_range("1960-01-01", periods=600, freq="MS")
    frame = pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "v": np.sin(np.arange(600) / 10.0)})
    repo.import_dataframe(frame, table_name="t", normalize_columns=False)
    repo.ensure_row_id("t")
    figure_id = repo.create_figure_descriptor(name="f")
    axis_id = repo.create_axis_descriptor(figure_id=figure_id, axis_index=0, chart_type="Time Series",
                                          title="f", x_label="x", y_label="y", options={})
    repo.create_series_descriptor(axis_id=axis_id, series_index=0, name="f",
                                  sql_query='SELECT "_id", "date" AS x, "v" AS y FROM "t"',
                                  roles={"x": "x", "y": "y"}, style={})
    panel = ChartPanel(repo, figure_id)
    try:
        panel.resize(600, 400)
        panel.ensure_rendered()
        axes = panel._canvas.figure.axes[0]
        start, end = (float(date2num(pd.Timestamp(day).to_pydatetime())) for day in ("1961-01-01", "1961-12-31"))
        selection = panel._collect_selection(int(axes._chartlibre_axis_id), axes, start, end, -2.0, 2.0)
        assert selection is not None  # the box covers twelve months of the line
        panel._select_table_rows(selection)
        assert len(repo.selected_row_ids("t")) == 12

        repo.set_selected_only("t", True)
        panel.reload()
        drawn = np.unique(np.concatenate([np.asarray(line.get_xdata(orig=False), dtype=float)
                                          for line in panel._canvas.figure.axes[0].lines]))
        assert len(drawn) == 12 and start <= drawn.min() and drawn.max() <= end
    finally:
        panel.close()
        repo.close()


# --- box_selection_follows_the_pointer: A box selection is drawn without redrawing the figure, and ends at the edge of its chart when the pointer leaves it.
def _two_charts(repo: SqliteRepo) -> int:
    figure_id = repo.create_figure_descriptor(name="f")
    repo.update_figure_layout(figure_id, nrows=1, ncols=2) if hasattr(repo, "update_figure_layout") else None
    for index, name in enumerate(("a", "b")):
        axis_id = repo.create_axis_descriptor(figure_id=figure_id, axis_index=index, chart_type="Scatter Plot",
                                              title=name, x_label="x", y_label="y", options={})
        repo.create_series_descriptor(axis_id=axis_id, series_index=0, name=name,
                                      sql_query='SELECT "_id", "a" AS x, "b" AS y FROM "t"',
                                      roles={"x": "x", "y": "y"}, style={})
    return figure_id


def _event(panel: ChartPanel, axes, x: float, y: float, *, inaxes=None):
    px, py = axes.transData.transform((x, y))
    return SimpleNamespace(button=1, x=px, y=py, xdata=x, ydata=y, inaxes=inaxes if inaxes is not None else axes, key=None)


def test_the_drag_does_not_redraw_the_figure_and_a_release_elsewhere_ends_at_the_edge(qapp, tmp_path) -> None:
    repo = SqliteRepo(db_path=tmp_path / "box.dhub")
    x = np.arange(20, dtype=float)
    repo.import_dataframe(pd.DataFrame({"a": x, "b": x}), table_name="t", normalize_columns=False)
    repo.ensure_row_id("t")
    panel = ChartPanel(repo, _two_charts(repo))
    try:
        panel.resize(800, 400)
        panel.ensure_rendered()
        panel._on_toggle_select_mode(True)
        axes = panel._canvas.figure.axes[0]
        panel._on_box_select_press(_event(panel, axes, 9.5, -1.0))
        drawn: list[int] = []
        panel._canvas.mpl_connect("draw_event", lambda _event: drawn.append(1))
        panel._on_box_select_motion(_event(panel, axes, 15.0, 30.0))
        assert drawn == []  # the rectangle is blitted on the saved picture, not the whole figure drawn again
        assert panel._selection_rect_artist.get_width() > 0

        far = _event(panel, axes, 1_000.0, 30.0, inaxes=None)  # over the other chart, right of this one
        panel._on_box_select_release(far)
        assert sorted(repo.selected_row_ids("t")) == list(range(11, 21))  # x 10..19: up to the edge, not dropped
    finally:
        panel.close()
        repo.close()


# --- box_follows_style: boxplot.notch, showmeans and meanline in a style reach the box plot.
matplotlib.use("Agg")
import matplotlib as mpl
import numpy as np
from matplotlib.figure import Figure

from app.charts.box import BoxAxisRenderer
from app.data.series_frame import SeriesFrame
from app.plugin_api.charts.base import SeriesData


def _draw(options: dict, rc: dict):
    with mpl.rc_context(rc):
        ax = Figure().add_subplot()
        frame = SeriesFrame({"value": np.random.default_rng(1).normal(0, 1, 60)})
        BoxAxisRenderer().render_axis(ax, [SeriesData(name="s", df=frame, style={})], options)
    return ax


def _mean_lines(ax) -> int:
    return sum(1 for line in ax.lines if line.get_linestyle() == "--")


def test_the_style_decides_when_the_chart_does_not() -> None:
    plain = _draw({}, {})
    styled = _draw({}, {"boxplot.showmeans": True, "boxplot.meanline": True, "boxplot.notch": True})
    assert _mean_lines(plain) == 0
    assert _mean_lines(styled) == 1
    # A notched box has more vertices than a plain rectangle.
    assert len(styled.patches[0].get_path().vertices) > len(plain.patches[0].get_path().vertices)


def test_the_chart_s_own_choice_wins_over_the_style() -> None:
    ax = _draw({"showmeans": False}, {"boxplot.showmeans": True, "boxplot.meanline": True})
    assert _mean_lines(ax) == 0


# --- box_series_style: A box plot series: its Line style draws the box's lines, its Marker style the outliers.
def _box():
    ax = Figure().add_subplot()
    return ax.boxplot([np.r_[np.arange(20.0), 60.0]], patch_artist=True)


def test_line_style_and_marker_reach_the_box_and_the_outliers() -> None:
    result = _box()
    BoxAxisRenderer._style_box(BoxAxisRenderer.__new__(BoxAxisRenderer), result, "", 1, None, None, None,
                               linestyle="--", marker="s", markersize=7)
    assert all(line.get_linestyle() == "--" for line in result["whiskers"] + result["medians"])
    assert result["boxes"][0].get_linestyle() == "--"
    assert result["fliers"][0].get_marker() == "s" and result["fliers"][0].get_markersize() == 7


def test_default_leaves_the_style_sheet_alone() -> None:
    result = _box()
    before = result["fliers"][0].get_marker()
    BoxAxisRenderer._style_box(BoxAxisRenderer.__new__(BoxAxisRenderer), result, "", 1, None, None, None,
                               linestyle=DEFAULT, marker=DEFAULT)
    assert result["fliers"][0].get_marker() == before and result["whiskers"][0].get_linestyle() == "-"
