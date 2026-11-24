"""The analyses that draw one figure per series (Is it normal?, Distribution, In control, Has it changed): all of them."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.data.sqlite_repo import SqliteRepo
from app.data_operations.change_dialog import ChangeDialog
from app.data_operations.distribution_dialog import DistributionDialog
from app.data_operations.in_control_dialog import InControlDialog
from app.data_operations.normality_dialog import NormalityDialog


@pytest.fixture
def three_series(repo: SqliteRepo) -> int:
    rng = np.random.default_rng(3)
    frame = pd.DataFrame({"x": np.arange(90.0), "y": rng.normal(10, 1, 90), "g": ["a", "b", "c"] * 30})
    repo.import_dataframe(frame, table_name="t", normalize_columns=False)
    figure_id = int(repo.create_figure_descriptor(name="F"))
    axis_id = int(repo.create_axis_descriptor(figure_id=figure_id, axis_index=0, chart_type="Scatter Plot",
                                              title="t", x_label="x", y_label="y", options={}))
    for index, name in enumerate("abc"):
        repo.create_series_descriptor(axis_id=axis_id, series_index=index, name=name,
                                      sql_query=f"SELECT x, y FROM t WHERE g = '{name}'",
                                      roles={"x": "x", "y": "y"}, style={})
    return figure_id


@pytest.mark.parametrize("dialog_class", [NormalityDialog, DistributionDialog, InControlDialog, ChangeDialog])
def test_every_series_gets_its_figure_in_the_preview_and_after_ok(qapp, repo, three_series, dialog_class) -> None:
    dialog = dialog_class(repo=repo, figure_id=three_series)
    shown: list[int] = []
    dialog.preview_drawn.connect(shown.append)
    try:
        dialog.preview()
        figures = [row[0] for row in repo._con.execute("SELECT id FROM __figure_descriptors__").fetchall()]
        assert len(figures) == 1 + 1, (dialog_class.__name__, figures)  # the chart and ONE figure for all series
        dialog.ok()
        figures = [row[0] for row in repo._con.execute("SELECT id FROM __figure_descriptors__").fetchall()]
        assert len(figures) == 1 + 1
    finally:
        dialog.close()


def test_the_figure_has_a_panel_per_series(qapp, repo, three_series) -> None:
    dialog = NormalityDialog(repo=repo, figure_id=three_series)
    try:
        dialog.ok()
        (figure_id,) = dialog.created_figure_ids
        assert len(repo.load_figure_descriptor(figure_id).axes) == 3
    finally:
        dialog.close()
