"""An axis is named after its column's Column Info label and unit, when nothing else names it (R-08)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from matplotlib.figure import Figure

from app.data import column_metadata as cm
from app.data.sqlite_repo import SqliteRepo
from app.plugin_api.charts.render_figure import render_figure_from_descriptor


@pytest.mark.parametrize(("sql", "table"), [
    ("SELECT x, y FROM t", "t"),
    ('SELECT "Time" AS x FROM "My Table" WHERE y > 0', "My Table"),
    ("select x from `weird name`", "weird name"),
    ("SELECT a.x FROM a JOIN b ON a.id = b.id", None),
    ("SELECT x FROM (SELECT x FROM t)", None),
    ("WITH q AS (SELECT 1) SELECT * FROM q", None),
    ("not sql", None),
])
def test_the_table_of_a_plain_select(sql: str, table: str | None) -> None:
    assert cm.source_table_of(sql) == table


def test_the_label_and_the_unit_make_the_axis_name() -> None:
    assert cm.axis_label_of("v", cm.ColumnInfo(label="Voltage", unit="V")) == "Voltage (V)"
    assert cm.axis_label_of("v", cm.ColumnInfo(label="Voltage")) == "Voltage"
    assert cm.axis_label_of("v", cm.ColumnInfo(unit="V")) == "v (V)"
    assert cm.axis_label_of("v", cm.ColumnInfo(notes="only a note")) == ""
    assert cm.axis_label_of("v", None) == ""


def _render(repo: SqliteRepo, *, sql: str = "SELECT x, y FROM t", x_label: str = "", y_label: str = "", chart: str = "Scatter Plot") -> Any:
    figure_id = int(repo.create_figure_descriptor(name="f"))
    axis_id = int(repo.create_axis_descriptor(figure_id=figure_id, axis_index=0, chart_type=chart, title="",
                                              x_label=x_label, y_label=y_label, options={}))
    repo.create_series_descriptor(axis_id=axis_id, series_index=0, name="s", sql_query=sql,
                                  roles={"x": "x", "y": "y"}, style={})
    figure = Figure()
    render_figure_from_descriptor(figure=figure, descriptor=repo.load_figure_descriptor(figure_id), repo=repo)
    return figure.axes[0]


@pytest.fixture
def repo(tmp_path: Path):
    database = SqliteRepo(db_path=tmp_path / "labels.dhub")
    database.import_dataframe(pd.DataFrame({"x": np.arange(5.0), "y": np.arange(5.0) ** 2}), table_name="t",
                              normalize_columns=False)
    yield database
    database.close()


def test_an_unlabelled_axis_takes_the_columns_label_and_unit(repo: SqliteRepo) -> None:
    cm.set_column_info(repo, "t", "x", cm.ColumnInfo(label="Time", unit="s"))
    cm.set_column_info(repo, "t", "y", cm.ColumnInfo(label="Distance", unit="m"))
    axes = _render(repo)
    assert (axes.get_xlabel(), axes.get_ylabel()) == ("Time (s)", "Distance (m)")


def test_a_typed_label_wins_and_a_column_without_a_description_leaves_the_axis_alone(repo: SqliteRepo) -> None:
    cm.set_column_info(repo, "t", "x", cm.ColumnInfo(label="Time", unit="s"))
    axes = _render(repo, y_label="My own")
    assert axes.get_xlabel() == "Time (s)"
    assert axes.get_ylabel() == "My own"
    typed = _render(repo, x_label="Typed")
    assert typed.get_xlabel() == "Typed"
    assert typed.get_ylabel() == ""  # y has no description


def test_a_query_that_is_not_a_plain_select_gives_no_name(repo: SqliteRepo) -> None:
    cm.set_column_info(repo, "t", "x", cm.ColumnInfo(label="Time", unit="s"))
    axes = _render(repo, sql="SELECT x, y FROM (SELECT x, y FROM t)")
    assert axes.get_xlabel() == ""


def test_a_date_pattern_is_read_in_the_two_notations() -> None:
    from datetime import datetime

    from app.utils.date_format import is_valid_pattern, localized_strftime

    moment = datetime(2024, 12, 31, 13, 5, 9)
    assert localized_strftime(moment, "DD/MM/YYYY HH:mm") == "31/12/2024 13:05"
    assert localized_strftime(moment, "%Y-%m-%d") == "2024-12-31"
    assert is_valid_pattern("YYYY")
    assert cm.axis_date_pattern(cm.ColumnInfo(format="datetime", pattern="YYYY")) == "YYYY"
    assert cm.axis_date_pattern(cm.ColumnInfo(format="fixed")) == ""  # only the date format sets one
    assert cm.axis_date_pattern(None) == ""


def test_a_date_axis_shows_its_columns_pattern(tmp_path: Path) -> None:
    database = SqliteRepo(db_path=tmp_path / "dates.dhub")
    try:
        database.import_dataframe(
            pd.DataFrame({"x": pd.date_range("2024-01-01", periods=60, freq="D").strftime("%Y-%m-%d"),
                          "y": np.arange(60.0)}),
            table_name="t", normalize_columns=False)
        axes = _render(database)
        assert axes.xaxis.get_major_formatter().__class__.__name__ != "FuncFormatter"  # matplotlib's own, adaptive
        cm.set_column_info(database, "t", "x", cm.ColumnInfo(format="datetime", pattern="DD/MM/YYYY"))
        axes = _render(database)
        axes.figure.canvas.draw()
        labels = [text.get_text() for text in axes.get_xticklabels() if text.get_text()]
        assert labels and all(len(label) == 10 and label[2] == "/" and label[5] == "/" for label in labels), labels
    finally:
        database.close()
