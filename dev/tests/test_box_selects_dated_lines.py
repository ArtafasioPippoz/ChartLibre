"""A box on a Time Series selects the rows of the dates it covers: its line is read in the units its axis draws."""
from __future__ import annotations

import numpy as np
import pandas as pd
from matplotlib.dates import date2num

from app.data.sqlite_repo import SqliteRepo
from app.widgets.chart_panel import ChartPanel


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
