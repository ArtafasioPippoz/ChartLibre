"""Tests of scatter colours, one section per former file:

* scatter_color_categories: A colour column of text that is not colour names is a set of categories.
* scatter_point_colours: A scatter's per-point colour column: empty means the series' own colour, not invisible points.
"""
from __future__ import annotations

from types import SimpleNamespace

import matplotlib
import numpy as np
import pandas as pd
import pytest

from app.charts.scatter import ScatterAxisRenderer


# --- scatter_color_categories: A colour column of text that is not colour names is a set of categories.
matplotlib.use("Agg")
from matplotlib.figure import Figure

from app.charts.scatter import ScatterAxisRenderer
from app.data.series_frame import SeriesFrame
from app.plugin_api.charts.base import SeriesData


def _draw(colors: list[str]):
    ax = Figure().add_subplot()
    frame = SeriesFrame({"x": [1.0, 2.0, 3.0], "y": [1.0, 2.0, 3.0], "color": colors})
    ScatterAxisRenderer().render_axis(ax, [SeriesData(name="s", df=frame, style={})], {})
    return ax.collections[0].get_facecolors()


def test_text_labels_become_one_colour_per_category() -> None:
    faces = _draw(["major", "minor", "major"])
    assert (faces[0] == faces[2]).all() and not (faces[0] == faces[1]).all()


def test_real_colour_names_are_still_used_as_given() -> None:
    faces = _draw(["red", "red", "blue"])
    assert tuple(faces[0][:3]) == (1.0, 0.0, 0.0)


# --- scatter_point_colours: A scatter's per-point colour column: empty means the series' own colour, not invisible points.
def _colours(column: pd.Series):
    renderer = ScatterAxisRenderer.__new__(ScatterAxisRenderer)
    data = SimpleNamespace(df=pd.DataFrame({"color": column}))
    return renderer._point_colors(data, {}, 0, pd.Series([True] * len(column)))


@pytest.mark.parametrize("column", [pd.Series([np.nan] * 3), pd.Series([None] * 3, dtype=object),
                                    pd.Series(["", " ", None], dtype=object)])
def test_an_empty_colour_column_leaves_the_series_colour(column) -> None:
    assert _colours(column) == (None, False)  # Outlier "Colour" with no outliers: the points stay as they were


def test_some_coloured_points_still_colour_only_those(report_image) -> None:
    colours, _discrete = _colours(pd.Series([None, "#d62728", None], dtype=object))
    assert colours is not None and colours.shape == (3, 4)
    from matplotlib.figure import Figure  # shown in the HTML test report (dev/tools/test_report.py)
    figure = Figure(figsize=(3, 2))
    figure.subplots().scatter([1, 2, 3], [1, 3, 2], c=colours)
    report_image(figure, "Only the middle point has a colour; the others keep the series colour")
