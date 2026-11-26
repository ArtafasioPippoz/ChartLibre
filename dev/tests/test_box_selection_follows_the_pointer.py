"""A box selection is drawn without redrawing the figure, and ends at the edge of its chart when the pointer leaves it."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from app.data.sqlite_repo import SqliteRepo
from app.widgets.chart_panel import ChartPanel


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
