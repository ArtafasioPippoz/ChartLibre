"""The chart's drawing tools: the Bezier geometry, how a stored path is drawn, and the pen / drag tools' mouse and keys."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch, Polygon
from matplotlib.path import Path

from app.plugin_api.charts.base import BaseAxisRenderer
from app.plugin_api.charts.path_geometry import (
    build_path,
    ellipse_nodes,
    format_nodes,
    has_curves,
    parse_nodes,
    rectangle_nodes,
    snap_angle,
)
from app.widgets.chart_panel.draw_tools import DrawToolsMixin


# ---------------------------------------------------------------- geometry
def test_nodes_round_trip_and_old_two_number_paths_still_read() -> None:
    assert parse_nodes("0,0; 1,0; 1,1") == [(0, 0, None, None), (1, 0, None, None), (1, 1, None, None)]
    nodes = parse_nodes("0,0,0,1; 2,0")
    assert nodes[0] == (0, 0, 0, 1) and has_curves(nodes)
    assert parse_nodes(format_nodes(nodes)) == nodes
    assert BaseAxisRenderer.parse_path_points("0,0,0,1; 2,0") == [(0, 0), (2, 0)]  # the old reader takes x, y


def test_a_smooth_node_makes_a_cubic_segment_and_corners_a_line() -> None:
    line = build_path(parse_nodes("0,0; 1,1"), False)
    assert list(line.codes) == [Path.MOVETO, Path.LINETO]
    curve = build_path(parse_nodes("0,0,0,1; 2,0"), False)
    assert list(curve.codes) == [Path.MOVETO, Path.CURVE4, Path.CURVE4, Path.CURVE4]
    assert tuple(curve.vertices[1]) == (0, 1)  # the outgoing handle is the first control point
    closed = build_path(parse_nodes("0,0; 1,0; 1,1"), True)
    assert closed.codes[-1] == Path.CLOSEPOLY


def test_an_ellipse_is_four_smooth_nodes_that_stay_inside_its_box() -> None:
    path = build_path(ellipse_nodes(0, 0, 4, 2), True)
    box = path.get_extents()
    assert abs(box.x0) < 1e-9 and abs(box.x1 - 4) < 1e-9 and abs(box.y0) < 1e-9 and abs(box.y1 - 2) < 1e-9
    assert len(rectangle_nodes(0, 0, 1, 1)) == 4 and not has_curves(rectangle_nodes(0, 0, 1, 1))


def test_shift_snaps_to_forty_five_degrees() -> None:
    x, y = snap_angle((0, 0), (10, 1))
    assert abs(y) < 1e-9 and abs(x - (101 ** 0.5)) < 1e-9
    x, y = snap_angle((0, 0), (5, 6))
    assert abs(x - y) < 1e-9


def test_a_stored_curve_is_drawn_as_a_path_patch_and_a_straight_path_as_before() -> None:
    figure, ax = plt.subplots()
    try:
        renderer = BaseAxisRenderer.__new__(BaseAxisRenderer)
        renderer.apply_path(ax, {"points": "0,0,0,1; 2,0", "closed": "no", "kwargs": {}})
        renderer.apply_path(ax, {"points": "0,0; 1,0; 1,1", "closed": "yes", "kwargs": {"facecolor": "red", "alpha": 0.3}})
        assert isinstance(ax.patches[0], PathPatch) and isinstance(ax.patches[1], Polygon)
    finally:
        plt.close(figure)


# ---------------------------------------------------------------- the tools
class _Repo:
    DESCRIPTOR_TABLES = ()

    def __init__(self) -> None:
        self.options: dict[str, Any] = {}
        self.labels: list[str] = []

    def snapshot_for_undo(self, _tables: Any, label: str = "") -> None:
        self.labels.append(label)

    def get_axis_options(self, _axis_id: int) -> dict[str, Any]:
        return self.options

    def set_axis_options(self, _axis_id: int, options: dict[str, Any]) -> None:
        self.options = options


class _Canvas:
    def draw_idle(self) -> None:
        pass

    def setCursor(self, *_a: Any) -> None:
        pass

    def unsetCursor(self) -> None:
        pass

    def setFocus(self) -> None:
        pass


class _Panel(DrawToolsMixin):
    def __init__(self) -> None:
        self._repo, self._canvas = _Repo(), _Canvas()
        self._toolbar = SimpleNamespace(mode="")
        self._select_mode_enabled = False
        self.reloaded = 0
        self.figure_edited = SimpleNamespace(emit=lambda: None)
        self.references: list[tuple[str, float]] = []
        self._init_draw_tools()

    def reload(self) -> None:
        self.reloaded += 1
        self._discard_draw_tools()

    def _show_navigation_message(self, _text: str) -> None:
        pass

    def _discard_box_selection(self) -> None:
        pass

    def _hide_hover_annotation(self) -> None:
        pass

    def _hide_crosshair(self) -> None:
        pass

    def _add_reference_line(self, _axis_id: int, orientation: str, value: float) -> None:
        self.references.append((orientation, value))


def _setup(tool: str) -> tuple[Any, Any, _Panel]:
    figure, ax = plt.subplots()
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax._chartlibre_axis_id = 7
    figure.canvas.draw()
    panel = _Panel()
    panel.set_draw_tool(tool)
    return figure, ax, panel


def _event(ax: Any, x: float, y: float, **extra: Any) -> Any:
    px, py = ax.transData.transform((x, y))
    return SimpleNamespace(inaxes=ax, xdata=x, ydata=y, x=px, y=py, button=1, key=None, dblclick=False, **extra)


def _click(panel: _Panel, ax: Any, x: float, y: float) -> None:
    panel._on_draw_press(_event(ax, x, y))
    panel._on_draw_release(_event(ax, x, y))


def _key(panel: _Panel, key: str) -> None:
    panel._on_draw_key(SimpleNamespace(key=key))


def test_the_pen_stores_a_path_on_enter_and_escape_cancels_then_puts_the_tool_down() -> None:
    figure, ax, panel = _setup("path")
    try:
        _click(panel, ax, 1, 1)
        panel._on_draw_motion(_event(ax, 4, 2))
        assert ax.patches and panel._draw_artists  # the rubber band is on the axes
        _click(panel, ax, 5, 5)
        _key(panel, "enter")
        assert panel._repo.options["paths"] == [{"points": "1,1; 5,5", "closed": "no", "kwargs": {}}]
        assert panel.reloaded == 1 and panel.draw_tool == "path"  # the tool stays for the next path
        _click(panel, ax, 2, 2)
        _key(panel, "escape")  # cancels what is drawn ...
        assert not panel._draw_nodes and panel.draw_tool == "path" and len(panel._repo.options["paths"]) == 1
        _key(panel, "escape")  # ... and a second one puts the tool down
        assert panel.draw_tool is None
    finally:
        plt.close(figure)


def test_dragging_a_pen_node_pulls_out_its_handle_and_makes_a_curve() -> None:
    figure, ax, panel = _setup("path")
    try:
        panel._on_draw_press(_event(ax, 1, 1))
        panel._on_draw_motion(_event(ax, 3, 4))
        panel._on_draw_release(_event(ax, 3, 4))
        _click(panel, ax, 8, 1)
        _key(panel, "enter")
        assert panel._repo.options["paths"][0]["points"] == "1,1,3,4; 8,1"
    finally:
        plt.close(figure)


def test_an_area_is_closed_and_filled_and_needs_three_nodes() -> None:
    figure, ax, panel = _setup("area")
    try:
        _click(panel, ax, 1, 1)
        _click(panel, ax, 5, 1)
        _key(panel, "enter")
        assert "paths" not in panel._repo.options  # two nodes are not an area
        for point in ((1, 1), (5, 1), (5, 5)):
            _click(panel, ax, *point)
        _key(panel, "enter")
        entry = panel._repo.options["paths"][0]
        assert entry["closed"] == "yes" and entry["kwargs"]["facecolor"] and entry["kwargs"]["alpha"] < 1
    finally:
        plt.close(figure)


def test_clicking_the_first_node_closes_and_backspace_takes_a_node_back() -> None:
    figure, ax, panel = _setup("path")
    try:
        for point in ((1, 1), (5, 1), (5, 5), (9, 9)):
            _click(panel, ax, *point)
        _key(panel, "backspace")
        assert len(panel._draw_nodes) == 3
        _click(panel, ax, 1, 1)  # on the first node
        assert panel._repo.options["paths"][0]["closed"] == "yes"
    finally:
        plt.close(figure)


def test_a_drag_makes_a_rectangle_an_ellipse_an_arrow_and_a_measurement() -> None:
    figure, ax, panel = _setup("rectangle")
    try:
        for tool in ("rectangle", "ellipse"):
            panel.set_draw_tool(tool)
            panel._on_draw_press(_event(ax, 1, 1))
            panel._on_draw_motion(_event(ax, 5, 4))
            panel._on_draw_release(_event(ax, 5, 4))
        paths = panel._repo.options["paths"]
        assert paths[0]["points"] == "1,1; 5,1; 5,4; 1,4" and has_curves(parse_nodes(paths[1]["points"]))
        panel.set_draw_tool("arrow")
        panel._on_draw_press(_event(ax, 1, 1))
        panel._on_draw_release(_event(ax, 6, 6))
        arrow = panel._repo.options["annotations"][0]
        assert arrow["type"] == "arrow" and (arrow["x"], arrow["y"]) == (6, 6) and arrow["kwargs"]["xytext"] == [1, 1]
        panel.set_draw_tool("ruler")
        panel._on_draw_press(_event(ax, 1, 1))
        panel._on_draw_release(_event(ax, 3, 2))
        assert panel._repo.options["measurements"] == [{"x0": 1, "y0": 1, "x1": 3, "y1": 2, "kwargs": {}}]
        panel._on_draw_press(_event(ax, 1, 1))
        panel._on_draw_release(_event(ax, 1, 1))  # a click without a drag makes nothing
        assert len(panel._repo.options["measurements"]) == 1
    finally:
        plt.close(figure)


def test_a_click_with_a_line_tool_adds_a_reference_line() -> None:
    figure, ax, panel = _setup("hline")
    try:
        _click(panel, ax, 2, 7)
        panel.set_draw_tool("vline")
        _click(panel, ax, 4, 1)
        assert panel.references == [("horizontal", 7), ("vertical", 4)]
    finally:
        plt.close(figure)


def test_choosing_a_tool_puts_the_other_tools_down_and_nothing_draws_without_one() -> None:
    figure, ax, panel = _setup("path")
    try:
        panel._select_mode_enabled = True
        panel._toolbar.mode = ""
        panel.set_draw_tool("area")
        assert panel._select_mode_enabled is False and panel.draw_tool == "area"
        panel.set_draw_tool(None)
        _click(panel, ax, 1, 1)
        assert not panel._draw_nodes and not ax.patches
        panel.set_draw_tool("no-such-tool")
        assert panel.draw_tool is None
    finally:
        plt.close(figure)


# ---------------------------------------------------------------- in the real chart panel
import time  # noqa: E402
from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from matplotlib.backend_bases import KeyEvent, MouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QToolButton  # noqa: E402

from app.data.sqlite_repo import SqliteRepo  # noqa: E402
from app.widgets.chart_panel import ChartPanel  # noqa: E402
from dev.tests._figure_factory import create_renderer_showcase_db  # noqa: E402


@pytest.fixture
def real_panel(qapp, tmp_path) -> Iterator[ChartPanel]:
    path = tmp_path / "draw.dhub"
    ids = create_renderer_showcase_db(path, n_points=50)
    repo = SqliteRepo(db_path=path)
    widget = ChartPanel(repo, ids["Scatter Plot"])
    widget.set_resize_mode("FIT", persist=False)
    widget.resize(900, 600)
    widget.show()
    end = time.monotonic() + 0.3
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.005)
    yield widget
    widget.hide()
    widget.deleteLater()
    repo.close()


def _mouse(panel: ChartPanel, name: str, x: float, y: float) -> None:
    ax = panel.figure.axes[0]
    px, py = ax.transData.transform((x, y))
    MouseEvent(name, panel.canvas, px, py, button=1)._process()


def test_the_pill_has_the_draw_button_with_every_tool_in_its_menu(real_panel: ChartPanel) -> None:
    button = real_panel._draw_button
    assert isinstance(button, QToolButton) and button.menu() is not None
    assert set(real_panel._draw_actions) == {"path", "area", "rectangle", "ellipse", "arrow", "annotation", "ruler", "hline", "vline"}
    real_panel._draw_actions["area"].trigger()
    assert real_panel.draw_tool == "area" and button.isChecked() and real_panel._draw_actions["area"].isChecked()
    button.click()  # clicking the checked button puts the tool down
    assert real_panel.draw_tool is None and not button.isChecked()
    button.click()  # and again brings back the last one
    assert real_panel.draw_tool == "area"


def test_drawing_a_curved_path_in_the_real_panel_stores_it_and_redraws_it(real_panel: ChartPanel) -> None:
    ax = real_panel.figure.axes[0]
    low, high = ax.get_xlim(), ax.get_ylim()
    x0, x1, y0, y1 = (low[0] + 0.2 * (low[1] - low[0]), low[0] + 0.7 * (low[1] - low[0]),
                      high[0] + 0.2 * (high[1] - high[0]), high[0] + 0.7 * (high[1] - high[0]))
    real_panel._draw_actions["path"].trigger()
    _mouse(real_panel, "button_press_event", x0, y0)
    _mouse(real_panel, "motion_notify_event", x0, y1)  # drag: the node becomes smooth
    _mouse(real_panel, "button_release_event", x0, y1)
    _mouse(real_panel, "button_press_event", x1, y1)
    _mouse(real_panel, "button_release_event", x1, y1)
    KeyEvent("key_press_event", real_panel.canvas, "enter")._process()
    options = real_panel._repo.get_axis_options(real_panel.figure.axes[0]._chartlibre_axis_id)
    (stored,) = options["paths"]
    assert has_curves(parse_nodes(stored["points"])) and stored["closed"] == "no"
    assert any(isinstance(patch, PathPatch) for patch in real_panel.figure.axes[0].patches)  # drawn back by the renderer
    assert real_panel.draw_tool == "path"


def test_pan_puts_the_drawing_tool_down_and_the_tool_puts_pan_down(real_panel: ChartPanel) -> None:
    real_panel._draw_actions["ruler"].trigger()
    real_panel._toolbar._actions["pan"].trigger()
    assert real_panel.draw_tool is None and "pan" in str(real_panel._toolbar.mode)
    real_panel._draw_actions["ruler"].trigger()
    assert str(real_panel._toolbar.mode) == "" and real_panel.draw_tool == "ruler"
