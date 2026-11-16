"""A Preview on a table's columns shows the figure it was drawn on (Same figure / Same axis)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.data.sqlite_repo import SqliteRepo
from app.data_operations.smoothing_dialog import SeriesSmoothingDialog


@pytest.fixture
def figure_id(repo: SqliteRepo) -> int:
    t = np.linspace(0.0, 12.0, 60)
    repo.import_dataframe(pd.DataFrame({"t": t, "a": np.sin(t)}), table_name="sig", normalize_columns=False)
    figure = int(repo.create_figure_descriptor(name="f"))
    axis = int(repo.create_axis_descriptor(figure_id=figure, axis_index=0, chart_type="Scatter Plot",
                                           title="t", x_label="t", y_label="y", options={}))
    repo.create_series_descriptor(axis_id=axis, series_index=0, name="a", sql_query="SELECT t AS x, a AS y FROM sig",
                                  roles={"x": "x", "y": "y"}, style={})
    return figure


def test_the_table_figure_is_announced(qapp, repo: SqliteRepo, figure_id: int) -> None:
    dialog = SeriesSmoothingDialog(repo=repo, figure_id=figure_id, parent=None)
    shown: list[int] = []
    dialog.preview_drawn.connect(shown.append)
    dialog.source_table_radio.setChecked(True)
    dialog.table_source.set_spec("sig", "t", ["a"])
    assert dialog._table_figure_id is not None
    assert shown and shown[-1] == dialog._table_figure_id
