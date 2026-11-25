"""The chart's drawing tools: one toolbar button with a drop-down menu of what can be drawn on the chart.

Path, Area, Rectangle, Ellipse, Arrow, Annotation, Ruler, and a horizontal or vertical Line. Choosing one makes it
the active tool of the chart - exclusive with pan, zoom and point selection - until Esc is pressed twice or the
button is clicked again. What is drawn is stored on the axis, exactly as the Overlay panel's tabs store it
(``paths``, ``annotations``, ``measurements``, ``lines``), so it is edited, restyled and deleted there.

The drawing itself is Matplotlib's: a pen path is a ``Path`` of ``CURVE4`` segments in a ``PathPatch``
(charts.path_geometry), an arrow is ``Axes.annotate`` with an ``arrowstyle``, a rectangle and an ellipse are paths too.

Pen tools (Path, Area): click adds a corner, click and drag adds a smooth node and pulls its handles out
(as the pen of a vector editor does); Shift keeps the segment at a multiple of 45 degrees; Backspace takes the last
node back; Enter or a double click finishes; C, or a click on the first node, closes; Esc cancels.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Final

from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, PathPatch
from matplotlib.text import Text
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QInputDialog, QToolButton

from app.logs.logger import applogger
from app.plugin_api.charts.path_geometry import (
    Node,
    build_path,
    ellipse_nodes,
    format_nodes,
    rectangle_nodes,
    snap_angle,
)
from app.styles.style import TidyMenu, field_label, theme_is_dark
from app.utils.i18n import _

#: The colour of what is being drawn, and of the objects it creates (the ruler's, the paths' default).
DRAW_COLOR: Final[str] = "#d62728"
#: The colour of the nodes and handles shown while a path is edited.
HANDLE_COLOR: Final[str] = "#1f77b4"
#: A press this close (pixels) to the first node closes the path; a drag must go further than this to count.
SNAP_PX: Final[float] = 8.0
DRAG_PX: Final[float] = 3.0
#: Opacity of an area's fill.
AREA_ALPHA: Final[float] = 0.3


@dataclass(frozen=True)
class DrawTool:
    """One entry of the drawing menu. *kind*: "pen" (click, drag a handle), "drag" (press, drag, release) or "click"."""

    id: str
    kind: str


DRAW_TOOLS: Final[tuple[DrawTool | None, ...]] = (
    DrawTool("path", "pen"), DrawTool("area", "pen"), DrawTool("rectangle", "drag"), DrawTool("ellipse", "drag"),
    None,
    DrawTool("arrow", "drag"), DrawTool("annotation", "drag"), DrawTool("ruler", "drag"),
    None,
    DrawTool("hline", "click"), DrawTool("vline", "click"),
)
_BY_ID: Final[dict[str, DrawTool]] = {tool.id: tool for tool in DRAW_TOOLS if tool is not None}


def tool_label(tool_id: str) -> str:
    """The menu text of a tool (translated)."""
    return {
        "path": _("Path (line and curve)"),
        "area": _("Area (filled shape)"),
        "rectangle": _("Rectangle"),
        "ellipse": _("Ellipse"),
        "arrow": _("Arrow"),
        "annotation": _("Annotation"),
        "ruler": _("Ruler"),
        "hline": _("Horizontal line"),
        "vline": _("Vertical line"),
    }.get(tool_id, tool_id)


def tool_hint(tool_id: str) -> str:
    """What the tool does with the mouse and keys, one line (translated)."""
    return {
        "path": _("Click: corner · drag: curve · Enter: finish · C: close · Esc: cancel"),
        "area": _("Click: corner · drag: curve · Enter: finish · Esc: cancel"),
        "rectangle": _("Drag from one corner to the opposite one · Esc: cancel"),
        "ellipse": _("Drag across the box the ellipse fits in · Esc: cancel"),
        "arrow": _("Drag from the tail to the head · Esc: cancel"),
        "annotation": _("Click: a note here · drag from the point to where the note goes · Esc: cancel"),
        "ruler": _("Drag between two points to measure them · Esc: cancel"),
        "hline": _("Click: a line across the chart at this y"),
        "vline": _("Click: a line across the chart at this x"),
    }.get(tool_id, "")


def tool_icon(tool_id: str, ink: str | None = None) -> QIcon:
    """A small drawing of the tool, in *ink* (the theme's text colour by default), at 1x and 2x."""
    colour = QColor(ink or ("#c9ced6" if theme_is_dark() else "#4a5263"))
    icon = QIcon()
    for ratio in (1, 2):
        size = 18 * ratio
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.scale(ratio, ratio)
            pen = QPen(colour, 1.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            _paint_tool(painter, tool_id, colour)
        finally:
            painter.end()
        icon.addPixmap(pixmap)
    return icon


def _paint_tool(painter: QPainter, tool_id: str, colour: QColor) -> None:
    """Draw tool *tool_id* in the 18x18 square of *painter*."""
    from PySide6.QtGui import QPainterPath

    fill = QColor(colour)
    fill.setAlpha(70)
    if tool_id in ("path", "area"):
        curve = QPainterPath(QPointF(3, 14))
        curve.cubicTo(QPointF(5, 2), QPointF(11, 2), QPointF(13, 10))
        if tool_id == "area":
            curve.lineTo(QPointF(15, 15))
            curve.closeSubpath()
            painter.setBrush(fill)
        painter.drawPath(curve)
        painter.setBrush(colour)
        for point in ((3, 14), (13, 10)):
            painter.drawEllipse(QPointF(*point), 1.4, 1.4)
    elif tool_id == "rectangle":
        painter.setBrush(fill)
        painter.drawRect(QRectF(3, 4, 12, 10))
    elif tool_id == "ellipse":
        painter.setBrush(fill)
        painter.drawEllipse(QRectF(2.5, 4, 13, 10))
    elif tool_id == "arrow":
        painter.drawLine(QPointF(3, 15), QPointF(14, 4))
        painter.drawLine(QPointF(14, 4), QPointF(8.5, 4.5))
        painter.drawLine(QPointF(14, 4), QPointF(13.5, 9.5))
    elif tool_id == "annotation":
        painter.setBrush(fill)
        painter.drawRoundedRect(QRectF(3, 3, 12, 9), 2, 2)
        painter.drawLine(QPointF(7, 12), QPointF(6, 16))
        painter.drawLine(QPointF(7, 6.5), QPointF(11, 6.5))
        painter.drawLine(QPointF(7, 9), QPointF(10, 9))
    elif tool_id == "ruler":
        painter.drawLine(QPointF(3, 14), QPointF(15, 4))
        painter.drawLine(QPointF(3, 11.5), QPointF(3, 16.5))
        painter.drawLine(QPointF(15, 1.5), QPointF(15, 6.5))
    elif tool_id == "hline":
        painter.drawLine(QPointF(2, 9), QPointF(16, 9))
        painter.drawLine(QPointF(2, 6), QPointF(2, 12))
        painter.drawLine(QPointF(16, 6), QPointF(16, 12))
    elif tool_id == "vline":
        painter.drawLine(QPointF(9, 2), QPointF(9, 16))
        painter.drawLine(QPointF(6, 2), QPointF(12, 2))
        painter.drawLine(QPointF(6, 16), QPointF(12, 16))


class DrawToolsMixin:
    """The drawing tools of a ChartPanel (see the module's text). Needs the panel's ``_canvas``, ``_toolbar``,
    ``_repo``, ``reload``, ``figure_edited`` and the box-selection state."""

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    def _init_draw_tools(self) -> None:
        """Reset the drawing tools to "none active, nothing in progress"."""
        #: The id of the active tool, None when no drawing tool owns the mouse.
        self._draw_tool: str | None = None
        #: The tool the button brings back when it is clicked, and what its icon shows.
        self._draw_last_tool: str = "path"
        self._draw_reset_progress()
        self._draw_button: QToolButton | None = None
        self._draw_actions: dict[str, QAction] = {}

    def _draw_reset_progress(self) -> None:
        """Forget what is being drawn (the artists are removed by _draw_clear_artists)."""
        #: Pen tools: the nodes so far, as mutable [x, y, hx, hy] lists.
        self._draw_nodes: list[list[float | None]] = []
        #: The axes and axis id the drawing is on, and the press that started a drag (data point, pixel).
        self._draw_axes: Any | None = None
        self._draw_axis_id: int | None = None
        self._draw_anchor: tuple[float, float] | None = None
        self._draw_press_px: tuple[float, float] | None = None
        #: A pen press is down: moving the mouse pulls the new node's handle.
        self._draw_dragging: bool = False
        #: The pointer's last position in data coordinates, on the drawing's axes.
        self._draw_cursor: tuple[float, float] | None = None
        self._draw_artists: list[Any] = []

    def _discard_draw_tools(self) -> None:
        """After figure.clear(): the preview artists are gone with their axes; the active tool stays."""
        self._draw_reset_progress()

    # ------------------------------------------------------------------
    # The button and its menu
    # ------------------------------------------------------------------
    def _build_draw_button(self, parent: Any) -> QToolButton:
        """The "Draw" button of the navigation pill: the last tool used, with the menu of all of them beside it."""
        button = QToolButton(parent)
        button.setObjectName("chartToolButton")
        button.setCheckable(True)
        button.setAutoRaise(True)
        button.setIconSize(QSize(18, 18))
        button.setFixedSize(QSize(40, 28))
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        menu = TidyMenu(button)
        for tool in DRAW_TOOLS:
            if tool is None:
                menu.addSeparator()
                continue
            action = menu.addAction(tool_icon(tool.id), tool_label(tool.id))
            action.setCheckable(True)
            action.setToolTip(tool_hint(tool.id))
            action.triggered.connect(lambda _checked=False, tool_id=tool.id: self.set_draw_tool(tool_id))
            self._draw_actions[tool.id] = action
        button.setMenu(menu)
        button.clicked.connect(lambda checked: self.set_draw_tool(self._draw_last_tool if checked else None))
        self._draw_button = button
        # Pan and zoom own the mouse too: turning one on puts the drawing tool down.
        for name in ("pan", "zoom"):
            action = getattr(self._toolbar, "_actions", {}).get(name)
            if action is not None:
                action.toggled.connect(lambda checked: self.set_draw_tool(None) if checked else None)
        self._sync_draw_button()
        return button

    def _sync_draw_button(self) -> None:
        """Make the button and the menu show the active tool, and the icon the last one used."""
        button = self._draw_button
        if button is None:
            return
        tool_id = self._draw_last_tool
        button.setIcon(tool_icon(tool_id))
        button.setToolTip(_("Draw: {tool}").format(tool=tool_label(tool_id)))
        button.blockSignals(True)
        button.setChecked(self._draw_tool is not None)
        button.blockSignals(False)
        for key, action in self._draw_actions.items():
            action.setChecked(key == self._draw_tool)

    @property
    def draw_tool(self) -> str | None:
        """The id of the active drawing tool, or None."""
        return self._draw_tool

    def set_draw_tool(self, tool_id: str | None) -> None:
        """Make *tool_id* the active tool (None: put the tool down), ending any drawing in progress."""
        if tool_id is not None and tool_id not in _BY_ID:
            tool_id = None
        self._draw_clear_artists()
        self._draw_reset_progress()
        self._draw_tool = tool_id
        if tool_id is not None:
            self._draw_last_tool = tool_id
            # One tool at a time: pan, zoom and point selection give the mouse up.
            mode = str(getattr(self._toolbar, "mode", ""))
            if "pan" in mode:
                self._toolbar.pan()
            elif "zoom" in mode:
                self._toolbar.zoom()
            if getattr(self, "_select_mode_enabled", False):
                self._select_mode_enabled = False
                self._discard_box_selection()
            self._discard_hover_annotation_view()
            self._canvas.setCursor(Qt.CursorShape.CrossCursor)
            self._canvas.setFocus()
        else:
            self._canvas.unsetCursor()
        self._sync_draw_button()
        self._show_navigation_message("")
        self._canvas.draw_idle()

    def _discard_hover_annotation_view(self) -> None:
        """Hide the hover readout and the crosshair: they repaint over what is being drawn."""
        try:
            self._hide_hover_annotation()
            self._hide_crosshair()
        except Exception:
            applogger.debug("Could not hide the hover readout.", exc_info=True)

    def _draw_hint(self) -> str:
        """The active tool's one-line help, for the line beside the coordinates; empty when none is active."""
        return tool_hint(self._draw_tool) if self._draw_tool else ""

    # ------------------------------------------------------------------
    # Mouse and keys
    # ------------------------------------------------------------------
    def _draw_point(self, event: Any) -> tuple[float, float]:
        """The pointer in data coordinates, with Shift keeping the segment from the last node at 45-degree steps."""
        point = (float(event.xdata), float(event.ydata))
        if "shift" in str(event.key or "") and self._draw_nodes and self._draw_tool in ("path", "area"):
            last = self._draw_nodes[-1]
            point = snap_angle((float(last[0] or 0.0), float(last[1] or 0.0)), point, self._screen_ratio(event.inaxes))
        elif "shift" in str(event.key or "") and self._draw_anchor is not None:
            point = snap_angle(self._draw_anchor, point, self._screen_ratio(event.inaxes))
        return point

    @staticmethod
    def _screen_ratio(axes: Any) -> float:
        """Screen pixels of one y unit over those of one x unit (1.0 when it cannot be told)."""
        try:
            (x0, y0), (x1, y1) = axes.transData.transform([(0.0, 0.0), (1.0, 1.0)])
            return abs((y1 - y0) / (x1 - x0)) or 1.0
        except Exception:
            return 1.0

    def _on_draw_press(self, event: Any) -> None:
        """A press with a drawing tool active: a pen node, the start of a drag, or the whole of a click."""
        tool = _BY_ID.get(self._draw_tool or "")
        if tool is None or event.button != 1 or event.inaxes is None:
            return
        if event.xdata is None or event.ydata is None:
            return
        axes = event.inaxes
        axis_id = getattr(axes, "_chartlibre_axis_id", None)
        if axis_id is None or (self._draw_axes is not None and axes is not self._draw_axes):
            return
        if tool.kind == "pen":
            self._pen_press(event, axes, int(axis_id))
        elif tool.kind == "drag":
            self._draw_axes, self._draw_axis_id = axes, int(axis_id)
            self._draw_anchor = (float(event.xdata), float(event.ydata))
            self._draw_press_px = (float(event.x), float(event.y))
            self._draw_cursor = self._draw_anchor
        else:
            x_value, y_value = float(event.xdata), float(event.ydata)
            if tool.id == "hline":
                self._add_reference_line(int(axis_id), "horizontal", y_value)
            else:
                self._add_reference_line(int(axis_id), "vertical", x_value)

    def _pen_press(self, event: Any, axes: Any, axis_id: int) -> None:
        if event.dblclick and self._draw_nodes:
            self._pen_finish(closed=False)
            return
        if len(self._draw_nodes) >= 3 and self._near_first_node(event):
            self._pen_finish(closed=True)
            return
        x_value, y_value = self._draw_point(event)
        self._draw_axes, self._draw_axis_id = axes, axis_id
        self._draw_nodes.append([x_value, y_value, None, None])
        self._draw_press_px = (float(event.x), float(event.y))
        self._draw_dragging = True
        self._draw_cursor = (x_value, y_value)
        self._draw_refresh()

    def _near_first_node(self, event: Any) -> bool:
        first = self._draw_nodes[0]
        px, py = self._draw_axes.transData.transform((first[0], first[1]))
        return math.hypot(px - event.x, py - event.y) <= SNAP_PX

    def _on_draw_motion(self, event: Any) -> None:
        """The pointer moves: the rubber band follows it, or the new pen node's handle is pulled out."""
        if self._draw_tool is None or self._draw_axes is None:
            return
        if event.inaxes is not self._draw_axes or event.xdata is None or event.ydata is None:
            return
        point = self._draw_point(event)
        if self._draw_dragging and self._draw_nodes and self._draw_press_px is not None:
            if math.hypot(event.x - self._draw_press_px[0], event.y - self._draw_press_px[1]) > DRAG_PX:
                node = self._draw_nodes[-1]
                node[2], node[3] = point
        else:
            self._draw_cursor = point
        self._draw_refresh()

    def _on_draw_release(self, event: Any) -> None:
        """The button comes up: a pen node is set, or a dragged shape is made."""
        tool = _BY_ID.get(self._draw_tool or "")
        if tool is None or event.button != 1:
            return
        if tool.kind == "pen":
            self._draw_dragging = False
            return
        if tool.kind != "drag" or self._draw_anchor is None or self._draw_axes is None:
            return
        anchor, axes, axis_id = self._draw_anchor, self._draw_axes, self._draw_axis_id
        press = self._draw_press_px or (event.x, event.y)
        moved = math.hypot(event.x - press[0], event.y - press[1]) > DRAG_PX
        end = self._draw_point(event) if event.inaxes is axes and event.xdata is not None else self._draw_cursor
        self._draw_clear_artists()
        self._draw_reset_progress()
        if axis_id is None or end is None:
            return
        if tool.id == "annotation":
            self._commit_annotation(axis_id, anchor, end if moved else None)
        elif moved:
            self._commit_dragged(tool.id, axis_id, anchor, end)
        self._canvas.draw_idle()

    def _on_draw_key(self, event: Any) -> None:
        """Enter or C finish a pen drawing, Backspace takes a node back, Esc cancels it - or puts the tool down."""
        if self._draw_tool is None:
            return
        key = str(event.key or "").lower()
        working = bool(self._draw_nodes) or self._draw_anchor is not None
        if key == "escape":
            if working:
                self._draw_clear_artists()
                self._draw_reset_progress()
                self._canvas.draw_idle()
            else:
                self.set_draw_tool(None)
        elif key in ("enter", "return", "ctrl+enter", "ctrl+return") and self._draw_nodes:
            self._pen_finish(closed=key.startswith("ctrl"))
        elif key == "c" and self._draw_nodes:
            self._pen_finish(closed=True)
        elif key in ("backspace", "delete") and self._draw_nodes:
            self._draw_nodes.pop()
            if not self._draw_nodes:
                self._draw_axes = self._draw_axis_id = None
            self._draw_dragging = False
            self._draw_refresh()

    # ------------------------------------------------------------------
    # The preview: Matplotlib artists on the axes, replaced at every move
    # ------------------------------------------------------------------
    def _draw_clear_artists(self) -> None:
        for artist in self._draw_artists:
            try:
                artist.remove()
            except Exception:
                pass  # removed already, with its axes
        self._draw_artists = []

    def _draw_add(self, artist: Any) -> Any:
        """Put a preview artist on the drawing's axes without letting it change the axes' limits."""
        axes = self._draw_axes
        axes.add_artist(artist)
        artist.set_clip_path(axes.patch)
        artist.set_zorder(20_000)
        self._draw_artists.append(artist)
        return artist

    def _draw_refresh(self) -> None:
        """Redraw the preview for the tool and the state it is in."""
        self._draw_clear_artists()
        axes, tool, cursor = self._draw_axes, self._draw_tool, self._draw_cursor
        if axes is None or tool is None:
            return
        if tool in ("path", "area"):
            self._preview_pen(axes, area=tool == "area")
        elif self._draw_anchor is not None and cursor is not None:
            self._preview_dragged(axes, tool, self._draw_anchor, cursor)
        self._canvas.draw_idle()

    def _preview_pen(self, axes: Any, *, area: bool) -> None:
        nodes: list[Node] = [(n[0], n[1], n[2], n[3]) for n in self._draw_nodes]  # type: ignore[misc]
        shown = list(nodes)
        if self._draw_cursor is not None and not self._draw_dragging and nodes:
            shown.append((self._draw_cursor[0], self._draw_cursor[1], None, None))
        if len(shown) >= 2:
            self._draw_add(PathPatch(
                build_path(shown, area and len(shown) > 2), facecolor=_rgba(DRAW_COLOR, AREA_ALPHA) if area else "none",
                edgecolor=DRAW_COLOR, linewidth=1.4, linestyle="--",
            ))
        if not nodes:
            return
        self._draw_add(Line2D([n[0] for n in nodes], [n[1] for n in nodes], linestyle="none", marker="s", markersize=5,
                              markerfacecolor="white", markeredgecolor=HANDLE_COLOR))
        for x_value, y_value, hx, hy in nodes:
            if hx is None or hy is None:
                continue
            ends = [(2 * x_value - hx, 2 * y_value - hy), (hx, hy)]
            self._draw_add(Line2D([p[0] for p in ends], [p[1] for p in ends], color=HANDLE_COLOR, linewidth=0.9))
            self._draw_add(Line2D([p[0] for p in ends], [p[1] for p in ends], linestyle="none", marker="o",
                                  markersize=3.5, color=HANDLE_COLOR))

    def _preview_dragged(self, axes: Any, tool: str, anchor: tuple[float, float], cursor: tuple[float, float]) -> None:
        (x0, y0), (x1, y1) = anchor, cursor
        shape = {"rectangle": rectangle_nodes, "ellipse": ellipse_nodes}.get(tool)
        if shape is not None:
            self._draw_add(PathPatch(build_path(shape(x0, y0, x1, y1), True), facecolor=_rgba(DRAW_COLOR, AREA_ALPHA),
                                     edgecolor=DRAW_COLOR, linewidth=1.4, linestyle="--"))
        elif tool == "ruler":
            self._draw_add(Line2D([x0, x1], [y0, y1], color=DRAW_COLOR, linewidth=1.4, marker="+", markersize=11))
            self._draw_add(Text(x1, y1, f"  Δx {x1 - x0:.4g}\n  Δy {y1 - y0:.4g}", fontsize=8, color=DRAW_COLOR,
                                va="bottom"))
        elif tool in ("arrow", "annotation"):
            tail, head = ((x0, y0), (x1, y1)) if tool == "arrow" else ((x1, y1), (x0, y0))
            self._draw_add(FancyArrowPatch(tail, head, arrowstyle="-|>", mutation_scale=12, color=DRAW_COLOR,
                                           transform=axes.transData))

    # ------------------------------------------------------------------
    # What is stored
    # ------------------------------------------------------------------
    def _draw_store(self, axis_id: int, key: str, entry: dict[str, Any], label: str) -> bool:
        """Append *entry* to the axis option *key* (undoably), redraw the chart and say it was edited."""
        try:
            self._repo.snapshot_for_undo(self._repo.DESCRIPTOR_TABLES, label=label)
            options = dict(self._repo.get_axis_options(int(axis_id)) or {})
            items = list(options.get(key) or [])
            items.append(entry)
            options[key] = items
            self._repo.set_axis_options(int(axis_id), options)
        except Exception:
            applogger.exception("Could not add to %s.", key)
            return False
        self.reload()
        self.figure_edited.emit()
        return True

    def _pen_finish(self, *, closed: bool) -> None:
        """Store the pen drawing as a path (an area is always closed and filled), if it has enough nodes."""
        axis_id, tool = self._draw_axis_id, self._draw_tool
        nodes: list[Node] = [(n[0], n[1], n[2], n[3]) for n in self._draw_nodes]  # type: ignore[misc]
        self._draw_clear_artists()
        self._draw_reset_progress()
        area = tool == "area"
        if axis_id is None or len(nodes) < (3 if area else 2):
            self._canvas.draw_idle()
            return
        self._store_path(axis_id, nodes, closed or area, area, _("Add area") if area else _("Add path"))

    def _store_path(self, axis_id: int, nodes: list[Node], closed: bool, area: bool, label: str) -> None:
        kwargs: dict[str, Any] = {"facecolor": DRAW_COLOR, "alpha": AREA_ALPHA} if area else {}
        entry = {"points": format_nodes(nodes), "closed": "yes" if closed else "no", "kwargs": kwargs}
        if self._draw_store(axis_id, "paths", entry, label):
            applogger.info("Added a path of %d nodes on axis %s", len(nodes), axis_id)

    def _commit_dragged(self, tool_id: str, axis_id: int, start: tuple[float, float], end: tuple[float, float]) -> None:
        (x0, y0), (x1, y1) = start, end
        if tool_id in ("rectangle", "ellipse"):
            nodes = (rectangle_nodes if tool_id == "rectangle" else ellipse_nodes)(x0, y0, x1, y1)
            self._store_path(axis_id, nodes, True, True, _("Add rectangle") if tool_id == "rectangle" else _("Add ellipse"))
        elif tool_id == "ruler":
            self._draw_store(axis_id, "measurements", {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "kwargs": {}},
                             _("Add measurement"))
        elif tool_id == "arrow":
            # Matplotlib's annotate: the head at (x, y), the tail at xytext, both in data coordinates.
            self._draw_store(axis_id, "annotations", {
                "x": x1, "y": y1, "type": "arrow", "text": "",
                "kwargs": {"xytext": [x0, y0], "textcoords": "data",
                           "arrowprops": {"arrowstyle": "-|>", "color": DRAW_COLOR}},
            }, _("Add arrow"))

    def _commit_annotation(self, axis_id: int, point: tuple[float, float], text_at: tuple[float, float] | None) -> None:
        """A click makes a text note at the point; a drag makes the note at the drag's end with an arrow to the point."""
        text, accepted = QInputDialog.getText(self, _("Add annotation"), field_label(_("Annotation text")))  # type: ignore[call-overload]
        if not accepted or not text.strip():
            return
        entry: dict[str, Any] = {"x": point[0], "y": point[1], "type": "text", "text": text.strip(), "kwargs": {}}
        if text_at is not None:
            entry["type"] = "arrow"
            entry["kwargs"] = {"xytext": list(text_at), "textcoords": "data",
                               "arrowprops": {"arrowstyle": "->", "color": DRAW_COLOR}}
        self._draw_store(axis_id, "annotations", entry, _("Add annotation"))


def _rgba(colour: str, alpha: float) -> tuple[float, float, float, float]:
    """*colour* ("#rrggbb") as a Matplotlib RGBA tuple with *alpha*."""
    from matplotlib.colors import to_rgb

    red, green, blue = to_rgb(colour)
    return red, green, blue, alpha
