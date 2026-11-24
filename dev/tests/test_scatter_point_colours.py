"""A scatter's per-point colour column: empty means the series' own colour, not invisible points."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.charts.scatter import ScatterAxisRenderer


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
