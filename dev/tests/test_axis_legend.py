"""The axis' legend properties: hide, show, place, columns, title (Axis properties, Legend)."""
from __future__ import annotations

import matplotlib

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
