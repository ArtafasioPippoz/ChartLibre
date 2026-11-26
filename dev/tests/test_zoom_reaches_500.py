"""The chart's zoom goes up to 500 %: a small figure (a journal's column) can fill the window."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.data.sqlite_repo import SqliteRepo
from app.widgets.chart_panel import ChartPanel


def test_the_zoom_slider_and_the_zoom_reach_500_percent(qapp, tmp_path) -> None:
    repo = SqliteRepo(db_path=tmp_path / "z.dhub")
    repo.import_dataframe(pd.DataFrame({"a": np.arange(5.0), "b": np.arange(5.0)}), table_name="t", normalize_columns=False)
    figure_id = repo.create_figure_descriptor(name="f")
    axis_id = repo.create_axis_descriptor(figure_id=figure_id, axis_index=0, chart_type="Scatter Plot",
                                          title="f", x_label="x", y_label="y", options={})
    repo.create_series_descriptor(axis_id=axis_id, series_index=0, name="f", sql_query='SELECT "a" AS x, "b" AS y FROM "t"',
                                  roles={"x": "x", "y": "y"}, style={})
    panel = ChartPanel(repo, figure_id)
    try:
        assert panel._zoom_slider.maximum() == 500
        assert panel._clamp_zoom(480) == 480 and panel._clamp_zoom(900) == 500
    finally:
        panel.close()
        repo.close()
