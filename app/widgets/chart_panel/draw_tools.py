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
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QInputDialog, QToolButton

from app.logs.logger import applogger
from app.plugin_api.charts.path_geometry import (
    Node,
    build_path,
    ellipse_nodes,
    format_nodes,
    parse_nodes,
    rectangle_nodes,
    snap_angle,
)
from app import SVG
from app.styles.style import TidyMenu, field_label, icon_from_svg_source
from app.utils.i18n import _

#: The colour of what is being drawn, and of the objects it creates (the ruler's, the paths' default).
DRAW_COLOR: Final[str] = "#d62728"
#: The colour of the nodes and handles shown while a path is edited.
HANDLE_COLOR: Final[str] = "#1f77b4"
#: A press this close (pixels) to the first node closes the path; a drag must go further than this to count.
SNAP_PX: Final[float] = 8.0
DRAG_PX: Final[float] = 3.0
#: How near (pixels) a click must be to a node, a handle or a path's line to take it.
EDIT_HIT_PX: Final[float] = 7.0
#: Opacity of an area's fill.
AREA_ALPHA: Final[float] = 0.3


@dataclass(frozen=True)
class DrawTool:
    """One entry of the drawing menu. *kind*: "pen" (click, drag a handle), "drag" (press, drag, release), "click",
    or "edit" (work on the paths already drawn)."""

    id: str
    kind: str


DRAW_TOOLS: Final[tuple[DrawTool | None, ...]] = (
    DrawTool("edit", "edit"),
    None,
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
        "edit": _("Edit shapes"),
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
        "edit": _("Click a path, an arrow, a note, a ruler or a line · drag nodes and handles · "
                  "double-click: add or smooth · Delete: remove · Esc"),
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
    """The tool's drawing (app.SVG.DRAW_TOOLS), inked in the theme's colour - or in *ink*."""
    return icon_from_svg_source(SVG.DRAW_TOOLS.get(tool_id), size=18, color=ink)


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
        #: The Edit tool: (axis id, index in the axis' "paths") of the selected path, its working nodes and whether
        #: it is closed, the selected node, the drag in progress (kind, node index) with where it started.
        self._edit_sel: tuple[int, int] | None = None
        #: The axis option the selection is in: "paths", or "annotations" (an arrow or a text note, whose nodes are
        #: its point and - for an arrow placed in data coordinates or as an offset - the arrow's tail).
        self._edit_what: str = "paths"
        self._edit_nodes: list[list[float | None]] = []
        self._edit_closed: bool = False
        self._edit_node: int | None = None
        self._edit_drag: tuple[str, int] | None = None
        self._edit_anchor: tuple[float, float] | None = None
        self._edit_orig: list[list[float | None]] = []
        self._edit_moved: bool = False

    def _discard_draw_tools(self) -> None:
        """After figure.clear(): the preview artists are gone with their axes; the active tool stays, and so does
        the Edit tool's selection (_edit_restore shows it again once the figure is drawn)."""
        selected, what = self._edit_sel, self._edit_what
        self._draw_reset_progress()
        self._edit_sel, self._edit_what = selected, what

    # ------------------------------------------------------------------
    # The button and its menu
    # ------------------------------------------------------------------
    def _build_draw_button(self, parent: Any) -> QToolButton:
        """The "Draw" button of the navigation pill: the last tool used, with the menu of all of them beside it."""
        button = QToolButton(parent)
        button.setObjectName("chartToolButton")
        button.setProperty("drawMenu", True)  # its own width and chevron in the style sheets
        button.setCheckable(True)
        button.setAutoRaise(True)
        button.setIconSize(QSize(18, 18))
        button.setFixedSize(QSize(46, 28))
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
            kind = _BY_ID[tool_id].kind
            self._canvas.setCursor(Qt.CursorShape.ArrowCursor if kind == "edit" else Qt.CursorShape.CrossCursor)
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
        if axis_id is None:
            return
        if tool.kind in ("edit", "pen", "drag") and getattr(axes, "name", "") == "3d":
            # Paths and shapes are 2D patches, which a 3D axes cannot draw (see BaseAxisRenderer.apply_path).
            self.selection_changed.emit(_("Paths and shapes are drawn on 2D axes only."))
            return
        if tool.kind == "edit":
            self._edit_press(event, axes, int(axis_id))
            return
        if self._draw_axes is not None and axes is not self._draw_axes:
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
        if self._draw_tool == "edit":
            self._edit_motion(event)
            return
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
        if tool.kind == "edit":
            self._edit_release(event)
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
        if self._draw_tool == "edit":
            self._edit_key(key)
            return
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
        self._draw_handles(nodes)

    def _draw_handles(self, nodes: list[Node], selected: int | None = None) -> None:
        """Show the nodes as small squares (the *selected* one filled) and the handles of the smooth ones."""
        if not nodes:
            return
        self._draw_add(Line2D([n[0] for n in nodes], [n[1] for n in nodes], linestyle="none", marker="s", markersize=5,
                              markerfacecolor="white", markeredgecolor=HANDLE_COLOR))
        if selected is not None and 0 <= selected < len(nodes):
            self._draw_add(Line2D([nodes[selected][0]], [nodes[selected][1]], linestyle="none", marker="s",
                                  markersize=5, color=HANDLE_COLOR))
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
    # The Edit tool: select a drawn path, drag its nodes and handles, add, smooth and remove nodes
    # ------------------------------------------------------------------
    def _edit_nodes_typed(self) -> list[Node]:
        return [(n[0], n[1], n[2], n[3]) for n in self._edit_nodes]  # type: ignore[misc]

    def _edit_load(self, axes: Any, axis_id: int, index: int, what: str = "paths") -> bool:
        """Select item *index* of the axis option *what*: read its nodes from the stored option. False if there is none."""
        if what != "paths":
            return self._edit_load_item(axes, axis_id, index, what)
        paths = (self._repo.get_axis_options(int(axis_id)) or {}).get("paths") or []
        if not 0 <= index < len(paths) or not isinstance(paths[index], dict):
            return False
        nodes = parse_nodes(paths[index].get("points"))
        if len(nodes) < 2:
            return False
        self._edit_sel, self._edit_what = (int(axis_id), index), "paths"
        self._edit_nodes = [[x, y, hx, hy] for x, y, hx, hy in nodes]
        self._edit_closed = str(paths[index].get("closed", "yes") or "yes").lower() not in ("no", "false", "0")
        self._edit_node, self._edit_drag, self._edit_moved = None, None, False
        self._draw_axes, self._draw_axis_id = axes, int(axis_id)
        return True

    def _edit_item_nodes(self, axes: Any, what: str, entry: Any) -> list[tuple[float, float]]:
        """The points of an annotation (its point, then its arrow's tail when it can be placed) or of a measurement
        (its two ends), in data coordinates; empty when the entry has none that can be used."""
        if not isinstance(entry, dict):
            return []
        try:
            if what == "lines":
                value = float(entry["value"])
                if not math.isfinite(value):
                    return []
                if self._line_is_horizontal(entry):
                    return [(sum(axes.get_xlim()) / 2.0, value)]
                return [(value, sum(axes.get_ylim()) / 2.0)]
            if what == "measurements":
                return [(float(entry["x0"]), float(entry["y0"])), (float(entry["x1"]), float(entry["y1"]))]
            head = (float(entry.get("x", 0.0)), float(entry.get("y", 0.0)))
        except (KeyError, TypeError, ValueError):
            return []
        tail = self._annotation_tail(axes, entry, head)
        return [head] if tail is None else [head, tail]

    @staticmethod
    def _line_is_horizontal(entry: dict[str, Any]) -> bool:
        """As BaseAxisRenderer.apply_reference_line reads it: "h..." is horizontal, anything else vertical."""
        return str(entry.get("orientation", "vertical") or "vertical").lower().startswith("h")

    def _edit_load_item(self, axes: Any, axis_id: int, index: int, what: str) -> bool:
        """Select annotation or measurement *index*: its points become the nodes that can be dragged."""
        items = (self._repo.get_axis_options(int(axis_id)) or {}).get(what) or []
        if not 0 <= index < len(items):
            return False
        points = self._edit_item_nodes(axes, what, items[index])
        if not points:
            return False
        self._edit_sel, self._edit_what = (int(axis_id), index), what
        self._edit_nodes = [[x, y, None, None] for x, y in points]
        self._edit_closed = False
        self._edit_node, self._edit_drag, self._edit_moved = None, None, False
        self._draw_axes, self._draw_axis_id = axes, int(axis_id)
        return True

    @staticmethod
    def _annotation_tail(axes: Any, entry: dict[str, Any], head: tuple[float, float]) -> tuple[float, float] | None:
        """Where an arrow annotation's tail (its text) is, in data coordinates; None for a note or a tail in other
        coordinates (axes fraction...). Offsets are turned into data the way Matplotlib places them."""
        if str(entry.get("type", "text") or "text").lower() != "arrow":
            return None
        kwargs = entry.get("kwargs") if isinstance(entry.get("kwargs"), dict) else {}
        try:
            tx, ty = (float(v) for v in kwargs.get("xytext", (10, 10)))
        except (TypeError, ValueError):
            return None
        coords = str(kwargs.get("textcoords", "offset points") or "offset points")
        if coords == "data":
            return tx, ty
        if coords not in ("offset points", "offset pixels"):
            return None
        scale = axes.figure.dpi / 72.0 if coords == "offset points" else 1.0
        px, py = axes.transData.transform(head)
        x, y = axes.transData.inverted().transform((px + tx * scale, py + ty * scale))
        return float(x), float(y)

    def _edit_annotation_artist(self) -> Any | None:
        """The drawn artist of the selected annotation, on the selection's axes."""
        if self._draw_axes is None or self._edit_sel is None:
            return None
        return next((t for t in self._draw_axes.texts
                     if getattr(t, "_chartlibre_annotation_index", None) == self._edit_sel[1]), None)

    def _edit_restore(self) -> None:
        """After a render: show the selected path's nodes again, or forget it if it is gone."""
        if self._draw_tool != "edit" or self._edit_sel is None:
            return
        axis_id, index = self._edit_sel
        axes = next((a for a in self._figure.axes if getattr(a, "_chartlibre_axis_id", None) == axis_id), None)
        if axes is None or not self._edit_load(axes, axis_id, index, self._edit_what):
            self._edit_sel = None
            return
        self._edit_refresh()

    def _edit_deselect(self) -> None:
        self._draw_clear_artists()
        self._draw_reset_progress()
        self._canvas.draw_idle()

    def _edit_refresh(self) -> None:
        """Show the selection: its nodes and handles, and the shape being dragged as a dashed outline."""
        self._draw_clear_artists()
        if self._draw_axes is None or self._edit_sel is None:
            self._canvas.draw_idle()
            return
        nodes = self._edit_nodes_typed()
        if self._edit_what != "paths":
            if self._edit_drag is not None and self._edit_moved:
                if self._edit_what == "annotations":
                    self._edit_move_annotation_artist(nodes)
                if self._edit_what == "lines":
                    horizontal = self._edit_line_horizontal()
                    low, high = (self._draw_axes.get_xlim() if horizontal else self._draw_axes.get_ylim())
                    xs, ys = ([low, high], [nodes[0][1]] * 2) if horizontal else ([nodes[0][0]] * 2, [low, high])
                    self._draw_add(Line2D(xs, ys, color=HANDLE_COLOR, linewidth=1.2, linestyle="--"))
                elif len(nodes) > 1:
                    self._draw_add(Line2D([n[0] for n in nodes], [n[1] for n in nodes], color=HANDLE_COLOR,
                                          linewidth=1.2, linestyle="--"))
        elif self._edit_drag is not None and self._edit_moved:
            self._draw_add(PathPatch(build_path(nodes, self._edit_closed), facecolor="none", edgecolor=HANDLE_COLOR,
                                     linewidth=1.2, linestyle="--"))
        self._draw_handles(nodes, self._edit_node)
        self._canvas.draw_idle()

    def _edit_line_horizontal(self) -> bool:
        """Whether the selected reference line is horizontal (read from the store: the nodes do not say)."""
        if self._edit_sel is None:
            return False
        lines = (self._repo.get_axis_options(self._edit_sel[0]) or {}).get("lines") or []
        index = self._edit_sel[1]
        return 0 <= index < len(lines) and isinstance(lines[index], dict) and self._line_is_horizontal(lines[index])

    def _edit_move_annotation_artist(self, nodes: list[Node]) -> None:
        """While dragging: put the drawn annotation where its nodes are now (it is redrawn from the store on release)."""
        artist = self._edit_annotation_artist()
        if artist is None:
            return
        head = (nodes[0][0], nodes[0][1])
        if hasattr(artist, "xyann"):
            artist.xy = head
            if len(nodes) > 1:
                artist.anncoords = "data"
                artist.xyann = (nodes[1][0], nodes[1][1])
        else:
            artist.set_position(head)

    @staticmethod
    def _polyline_nearest(polygon: Any, point: tuple[float, float]) -> tuple[float, tuple[float, float]]:
        """(distance, nearest point) from *point* to the polyline *polygon* (an N x 2 array), in its own units."""
        import numpy as np

        best = (math.inf, (0.0, 0.0))
        p = np.asarray(point, dtype=float)
        for a, b in zip(polygon[:-1], polygon[1:]):
            ab = b - a
            length = float(ab @ ab)
            t = 0.0 if length == 0 else min(1.0, max(0.0, float((p - a) @ ab) / length))
            nearest = a + t * ab
            distance = float(np.hypot(*(p - nearest)))
            if distance < best[0]:
                best = (distance, (float(nearest[0]), float(nearest[1])))
        return best

    def _edit_path_at(self, axes: Any, event: Any) -> int | None:
        """The index of the stored path drawn under the pointer (on its line, or inside a filled one), topmost first."""
        point = (float(event.x), float(event.y))
        for patch in reversed(axes.patches):
            index = getattr(patch, "_chartlibre_path_index", None)
            if index is None:
                continue
            path = patch.get_path().transformed(patch.get_transform())
            for polygon in path.to_polygons(closed_only=False):
                if len(polygon) > 1 and self._polyline_nearest(polygon, point)[0] <= EDIT_HIT_PX:
                    return int(index)
            filled = patch.get_facecolor()
            if len(filled) and filled[3] > 0 and path.contains_point(point):
                return int(index)
        return None

    def _edit_item_at(self, axes: Any, axis_id: int, event: Any) -> tuple[str, int] | None:
        """(option, index) of the annotation, measurement or reference line under the pointer: near its line or its
        point, or on an annotation's text. Annotations first, then measurements, then lines; last stored first."""
        import numpy as np

        point = (float(event.x), float(event.y))
        options = self._repo.get_axis_options(int(axis_id)) or {}
        texts = {getattr(t, "_chartlibre_annotation_index", None): t for t in axes.texts}
        for what in ("annotations", "measurements", "lines"):
            items = options.get(what) or []
            for index in range(len(items) - 1, -1, -1):
                points = self._edit_item_nodes(axes, what, items[index])
                if not points:
                    continue
                pixels = np.asarray(axes.transData.transform(points), dtype=float)
                if what == "lines":  # across the whole axes: only the distance across the line counts
                    across = 1 if self._line_is_horizontal(items[index]) else 0
                    near = abs(pixels[0][across] - point[across]) <= EDIT_HIT_PX
                elif len(pixels) > 1:
                    near = self._polyline_nearest(pixels, point)[0] <= EDIT_HIT_PX
                else:
                    near = math.hypot(*(pixels[0] - point)) <= EDIT_HIT_PX
                artist = texts.get(index) if what == "annotations" else None
                try:
                    on_text = bool(artist is not None and artist.get_text()
                                   and artist.get_window_extent().contains(*point))
                except Exception:
                    on_text = False
                if near or on_text:
                    return what, index
        return None

    def _edit_target_at(self, axes: Any, axis_id: int, event: Any) -> tuple[str, int] | None:
        """(option, index) of what is under the pointer - notes, arrows, rulers and lines first, they sit on top."""
        target = self._edit_item_at(axes, axis_id, event)
        if target is not None:
            return target
        index = self._edit_path_at(axes, event)
        return None if index is None else ("paths", index)

    def _edit_hit(self, axes: Any, event: Any) -> tuple[str, int] | None:
        """The handle ("out"/"in") or node under the pointer, handles first as they sit on top of the nodes."""
        point = (float(event.x), float(event.y))
        spots: list[tuple[str, int, float, float]] = []
        for i, (x, y, hx, hy) in enumerate(self._edit_nodes_typed()):
            if hx is not None and hy is not None:
                spots.append(("out", i, hx, hy))
                spots.append(("in", i, 2 * x - hx, 2 * y - hy))
        spots += [("node", i, n[0], n[1]) for i, n in enumerate(self._edit_nodes)]  # type: ignore[misc]
        for kind, i, x, y in spots:
            px, py = axes.transData.transform((x, y))
            if math.hypot(px - point[0], py - point[1]) <= EDIT_HIT_PX:
                return kind, i
        return None

    def _edit_press(self, event: Any, axes: Any, axis_id: int) -> None:
        point = (float(event.xdata), float(event.ydata))
        if self._edit_sel is not None and axes is self._draw_axes:
            hit = self._edit_hit(axes, event)
            if hit is not None:
                kind, i = hit
                if self._edit_what != "paths":
                    self._edit_begin("node", i, point, event)
                    return
                if event.dblclick and kind == "node":
                    self._edit_toggle_smooth(i)
                    return
                if kind == "node" and "shift" in str(event.key or "") and self._edit_nodes[i][2] is None:
                    kind = "pull"  # Shift on a corner: drag its handles out
                self._edit_begin(kind, i, point, event)
                return
            if self._edit_target_at(axes, axis_id, event) == (self._edit_what, self._edit_sel[1]):
                if event.dblclick and self._edit_what == "paths":
                    self._edit_add_node(axes, event)
                else:
                    self._edit_node = None
                    self._edit_begin("move", -1, point, event)
                return
        target = self._edit_target_at(axes, axis_id, event)
        if target is None:
            self._edit_deselect()
        elif self._edit_load(axes, axis_id, target[1], target[0]):
            self._edit_refresh()

    def _edit_begin(self, kind: str, index: int, point: tuple[float, float], event: Any) -> None:
        self._edit_drag = (kind, index)
        self._edit_anchor = point
        self._edit_orig = [list(n) for n in self._edit_nodes]
        self._draw_press_px = (float(event.x), float(event.y))
        self._edit_moved = False
        if kind in ("node", "out", "in", "pull"):
            self._edit_node = index
        self._edit_refresh()

    def _edit_motion(self, event: Any) -> None:
        if self._edit_drag is None or self._edit_anchor is None or self._draw_press_px is None:
            return
        if event.inaxes is not self._draw_axes or event.xdata is None or event.ydata is None:
            return
        if not self._edit_moved and math.hypot(event.x - self._draw_press_px[0], event.y - self._draw_press_px[1]) <= DRAG_PX:
            return
        self._edit_moved = True
        kind, i = self._edit_drag
        x, y = float(event.xdata), float(event.ydata)
        dx, dy = x - self._edit_anchor[0], y - self._edit_anchor[1]
        nodes = self._edit_nodes
        if kind in ("node", "move"):
            for j, original in enumerate(self._edit_orig):
                if kind == "node" and j != i:
                    continue
                nodes[j] = [original[0] + dx, original[1] + dy,  # type: ignore[operator]
                            None if original[2] is None else original[2] + dx,  # type: ignore[operator]
                            None if original[3] is None else original[3] + dy]  # type: ignore[operator]
        elif kind in ("out", "pull"):
            nodes[i][2], nodes[i][3] = x, y
        elif kind == "in":
            nodes[i][2], nodes[i][3] = 2 * float(nodes[i][0] or 0.0) - x, 2 * float(nodes[i][1] or 0.0) - y
        self._edit_refresh()

    def _edit_release(self, _event: Any) -> None:
        moved = self._edit_moved and self._edit_drag is not None
        self._edit_drag, self._edit_anchor, self._edit_moved = None, None, False
        if moved:
            self._edit_commit({"annotations": _("Move annotation"), "measurements": _("Move measurement"),
                               "lines": _("Move line")}
                              .get(self._edit_what, _("Edit path")))
        else:
            self._edit_refresh()

    def _edit_toggle_smooth(self, i: int) -> None:
        """Double-click on a node: a corner becomes smooth (handles along its neighbours), a smooth one a corner."""
        node = self._edit_nodes[i]
        if node[2] is not None:
            node[2] = node[3] = None
        else:
            count = len(self._edit_nodes)
            before = self._edit_nodes[(i - 1) % count] if i > 0 or self._edit_closed else node
            after = self._edit_nodes[(i + 1) % count] if i < count - 1 or self._edit_closed else node
            tx, ty = float(after[0] or 0.0) - float(before[0] or 0.0), float(after[1] or 0.0) - float(before[1] or 0.0)
            norm = math.hypot(tx, ty)
            if norm == 0.0:
                return
            reach = min((math.hypot(float(n[0] or 0.0) - float(node[0] or 0.0), float(n[1] or 0.0) - float(node[1] or 0.0))
                         for n in (before, after) if n is not node), default=norm) / 3.0
            node[2], node[3] = float(node[0] or 0.0) + tx / norm * reach, float(node[1] or 0.0) + ty / norm * reach
        self._edit_node = i
        self._edit_commit(_("Edit path"))

    def _edit_add_node(self, axes: Any, event: Any) -> None:
        """Double-click on the selected path's line: a corner node where the line is, between its two neighbours."""
        nodes = self._edit_nodes_typed()
        pairs = [(i, i + 1) for i in range(len(nodes) - 1)]
        if self._edit_closed and len(nodes) > 2:
            pairs.append((len(nodes) - 1, 0))
        best: tuple[float, int, tuple[float, float]] | None = None
        for a, b in pairs:
            segment = build_path([nodes[a], nodes[b]], False).transformed(axes.transData)
            for polygon in segment.to_polygons(closed_only=False):
                if len(polygon) < 2:
                    continue
                distance, nearest = self._polyline_nearest(polygon, (float(event.x), float(event.y)))
                if best is None or distance < best[0]:
                    best = (distance, a, nearest)
        if best is None or best[0] > 2 * EDIT_HIT_PX:
            return
        x, y = axes.transData.inverted().transform(best[2])
        self._edit_nodes.insert(best[1] + 1, [float(x), float(y), None, None])
        self._edit_node = best[1] + 1
        self._edit_commit(_("Add node"))

    def _edit_key(self, key: str) -> None:
        """Esc: deselect, then put the tool down. Delete/Backspace: the selected node, or the whole path."""
        if key == "escape":
            if self._edit_sel is not None:
                self._edit_deselect()
            else:
                self.set_draw_tool(None)
        elif key in ("delete", "backspace") and self._edit_sel is not None:
            least = 3 if self._edit_closed else 2
            if self._edit_what == "paths" and self._edit_node is not None and len(self._edit_nodes) > least:
                del self._edit_nodes[self._edit_node]
                self._edit_node = None
                self._edit_commit(_("Remove node"))
            else:
                self._edit_remove_path()

    def _edit_write(self, label: str, change: Any) -> bool:
        """Apply *change(items, index)* to the axis' stored paths or annotations, undoably, then redraw the chart."""
        if self._edit_sel is None:
            return False
        axis_id, index = self._edit_sel
        key = self._edit_what
        try:
            self._repo.snapshot_for_undo(self._repo.DESCRIPTOR_TABLES, label=label)
            options = dict(self._repo.get_axis_options(int(axis_id)) or {})
            items = list(options.get(key) or [])
            change(items, index)
            options[key] = items
            self._repo.set_axis_options(int(axis_id), options)
        except Exception:
            applogger.exception("Could not edit the %s.", key)
            return False
        self.reload()
        self.figure_edited.emit()
        return True

    def _edit_commit(self, label: str) -> None:
        """Store the working nodes as the selected path's points, or as the annotation's point and arrow tail."""
        if self._edit_what != "paths":
            nodes = self._edit_nodes_typed()

            def place(items: list[Any], index: int) -> None:
                if self._edit_what == "lines":
                    horizontal = self._line_is_horizontal(items[index])
                    items[index] = {**items[index], "value": float(nodes[0][1] if horizontal else nodes[0][0])}
                    return
                if self._edit_what == "measurements":
                    (x0, y0, _h0, _v0), (x1, y1, _h1, _v1) = nodes[0], nodes[1]
                    items[index] = {**items[index], "x0": float(x0), "y0": float(y0), "x1": float(x1), "y1": float(y1)}
                    return
                entry = {**items[index], "x": float(nodes[0][0]), "y": float(nodes[0][1])}
                if len(nodes) > 1:
                    kwargs = dict(entry.get("kwargs") or {})
                    kwargs["xytext"], kwargs["textcoords"] = [float(nodes[1][0]), float(nodes[1][1])], "data"
                    entry["kwargs"] = kwargs
                items[index] = entry

            self._edit_write(label, place)
            return
        points = format_nodes(self._edit_nodes_typed())

        def change(paths: list[Any], index: int) -> None:
            paths[index] = {**paths[index], "points": points}

        self._edit_write(label, change)

    def _edit_remove_path(self) -> None:
        def change(paths: list[Any], index: int) -> None:
            del paths[index]

        selected = self._edit_sel
        label = {"annotations": _("Delete annotation"), "measurements": _("Delete measurement"),
                 "lines": _("Delete line")}.get(
            self._edit_what, _("Delete path"))
        if self._edit_write(label, change) and selected is not None:
            self._edit_sel = None  # the paths after it moved up: nothing is selected any more
            self._edit_deselect()

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
