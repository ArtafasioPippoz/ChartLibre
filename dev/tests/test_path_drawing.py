"""Drawing a path point by point from the chart's context menu (ChartToolsMixin._path_*)."""
from __future__ import annotations

from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from app.widgets.chart_panel.tools import ChartToolsMixin


class _Repo:
    DESCRIPTOR_TABLES = ()

    def __init__(self) -> None:
        self.options: dict[str, Any] = {}

    def snapshot_for_undo(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def get_axis_options(self, _axis_id: int) -> dict[str, Any]:
        return self.options

    def set_axis_options(self, _axis_id: int, options: dict[str, Any]) -> None:
        self.options = options


class _Canvas:
    def draw_idle(self) -> None:
        pass


class _Panel:
    RULER_COLOR = "#d62728"
    _init_path = ChartToolsMixin._init_path
    _clear_path = ChartToolsMixin._clear_path
    _path_add_point = ChartToolsMixin._path_add_point
    _path_finish = ChartToolsMixin._path_finish

    def __init__(self) -> None:
        self._repo = _Repo()
        self._canvas = _Canvas()
        self.reloaded = 0
        self.figure_edited = type("S", (), {"emit": lambda _self: None})()
        self._init_path()

    def reload(self) -> None:
        self.reloaded += 1


def test_a_path_is_stored_on_its_axis_and_a_short_one_is_dropped() -> None:
    figure, ax = plt.subplots()
    try:
        panel = _Panel()
        for point in ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)):
            panel._path_add_point(ax, 3, *point)
        assert len(ax.lines) == 1  # the one line that shows the path so far
        panel._path_finish(True)
        assert panel.reloaded == 1 and not ax.lines
        assert panel._repo.options["paths"] == [{"points": "0,0; 1,0; 1,1", "closed": "yes", "kwargs": {}}]
        panel._path_add_point(ax, 3, 2.0, 2.0)
        panel._path_finish(False)  # one point is not a path
        assert len(panel._repo.options["paths"]) == 1 and panel.reloaded == 1
    finally:
        plt.close(figure)


def test_a_point_on_another_axis_starts_a_new_path() -> None:
    figure, (ax1, ax2) = plt.subplots(1, 2)
    try:
        panel = _Panel()
        panel._path_add_point(ax1, 1, 0.0, 0.0)
        panel._path_add_point(ax2, 2, 5.0, 5.0)
        assert panel._path_points == [(5.0, 5.0)] and panel._path_axis_id == 2
        panel._clear_path()
        assert not panel._path_points and not ax2.lines
    finally:
        plt.close(figure)
