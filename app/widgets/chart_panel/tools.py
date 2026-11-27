"""The chart panel's tools and view: interactive tools (crosshair, dragged annotations, box selection,
live updates), resize modes, zoom, background and the figure's geometry, and what the panel
does to its chart (copy, save, export, delete)."""
from __future__ import annotations

import csv
import html
import json
from io import BytesIO
from typing import TYPE_CHECKING, Any, Final

import numpy as np
import pandas as pd
import PySide6.QtGui
from matplotlib import rcParams
from matplotlib.dates import AutoDateFormatter, ConciseDateFormatter, DateFormatter, DateLocator
from matplotlib.patches import Rectangle
from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QSizePolicy,
    QWidget,
)

from app.data.data_source import quote_identifier
from app.data.repo.function_sql import function_names
from app.data.sqlite_repo import ROW_ID
from app.utils.logger import applogger
from app.plugin_api.charts.descriptor_grid import (
    descriptor_axis_count,
    descriptor_prepared_for_render,
)
from app.plugin_api.data_operations.dialog_base import generated_table_name
from app.utils.coercion import coerce_axis
from app.utils.config import get_section, get_value
from app.utils.figure_metrics import (
    CM_PER_INCH,
    DEFAULT_FIGURE_DPI,
    DEFAULT_FIGURE_SIZE_IN,
    figure_metrics_from_options,
)
from app.utils.hidpi import apply_configured_dpi, inches_to_logical, logical_to_inches
from app.utils.i18n import _
from app.utils.messages import ask, show_message
from app.widgets.chart_panel.constants import (
    BACKGROUND_AUTO,
    CONFIG_COPY_DPI,
    CONFIG_SECTION,
    DEFAULT_ASPECT_RATIO,
    DESK_COLOURS,
    FIXED_MODE_SCREEN_DPI,
    LIVE_REFRESH_INTERVAL_MS,
)

if TYPE_CHECKING:
    from PySide6.QtCore import Signal

    class _Host(QFrame):
        """What this part uses of ChartPanel: copies of the signatures, for the type checker only."""

        figure_edited: Signal
        selection_changed: Signal
        rows_selected: Signal
        selected_only_changed: Signal
        functions_trusted: Signal
        def ensure_rendered(self) -> None:
            ...
        def close(self) -> bool:
            ...
        def reload(self) -> None:
            ...
        @staticmethod
        def _normalized_resize_mode(value: object) -> str:
            ...
        def _persist_view_state(self) -> None:
            ...
        def _persist_chart_panel_config(self) -> None:
            ...
        def _draw_state(self) -> tuple[Any, ...]:
            ...
        _drawn_state: tuple[Any, ...] | None
        _min_zoom_percent: int
        _max_zoom_percent: int
        _zoom_percent: int
        _background_color: str
        _repo: Any
        _figure_id: Any
        _deleted: Any
        _pending_canvas_sync: Any
        _pending_canvas_redraw: Any
        _last_canvas_size: Any
        _canvas_sync_timer: Any
        _canvas_late_sync_timer: Any
        _config: Any
        _resize_mode: Any
        _figure: Any
        _fixed_figure_size_inches: Any
        _fixed_figure_dpi: Any
        _canvas: Any
        _toolbar: Any
        _top_row: Any
        _fixed_scroll_area: Any
        _chart_area: Any
        _main_layout: Any
        _filter_note: Any
        _notes_view: Any
        _content_split: Any
        _zoom_label: Any
        _zoom_fit_button: Any
        _zoom_slider: Any
else:
    _Host = object


def _is_date_axis(axes: Any) -> bool:
    """Whether the x axis of *axes* holds dates: the renderer put a date locator or date formatter on it.

    A dated axis holds days since 1970 and a lag axis holds a count of steps; both are plain numbers to
    Matplotlib, which is why linked zoom has to tell them apart.
    """
    axis = axes.xaxis
    return isinstance(axis.get_major_locator(), DateLocator) or isinstance(
        axis.get_major_formatter(), (DateFormatter, ConciseDateFormatter, AutoDateFormatter)
    )


class ChartToolsMixin(_Host):
    """The chart panel's tools and view: interactive tools (crosshair, dragged annotations, box selection, A part of ChartPanel (panel.py)."""

    # ==================================================================
    # Tools: Interactive tools: crosshair, dragged annotations, box selection, live updates.
    # ==================================================================
    # ------------------------------------------------------------------
    # Crosshair
    # ------------------------------------------------------------------
    #: Colour for the crosshair lines - grey rather than the hover
    #: annotation's own colours, so it reads as a ruled guide under the
    #: data rather than as a second thing competing for attention.
    CROSSHAIR_COLOR: Final[str] = "#808080"

    def _init_crosshair(self) -> None:
        """Reset crosshair state to "off, nothing drawn"."""
        self._crosshair_enabled = False
        #: axes -> its vertical line, shared x across every axes.
        self._crosshair_vlines: dict[Any, Any] = {}
        #: axes -> its horizontal line, only ever visible on the one axes
        #: under the pointer - y scales are not shared, so a horizontal
        #: line on every axes would compare unrelated numbers.
        self._crosshair_hlines: dict[Any, Any] = {}
        #: The linked-zoom/pan toggle lives here too: both are "act across
        #: every axes of this figure" settings a person turns on together
        #: when comparing stacked panels.
        self._link_x_zoom_enabled = False
        self._syncing_x_limits = False

    def _discard_crosshair(self) -> None:
        """Forget the crosshair's artists after figure.clear() destroyed them.

        Mirrors _discard_hover_annotation: the enabled flags
        survive a reload (a person's choice to see a crosshair should not
        reset itself every time the chart redraws), only the per-axes
        artists and the pending link-zoom guard do not.
        """
        self._crosshair_vlines = {}
        self._crosshair_hlines = {}
        self._syncing_x_limits = False

    def _on_toggle_crosshair(self, checked: bool) -> None:
        self._crosshair_enabled = bool(checked)
        if not self._crosshair_enabled:
            self._hide_crosshair()

    def _on_toggle_link_x_zoom(self, checked: bool) -> None:
        self._link_x_zoom_enabled = bool(checked)

    def _update_crosshair(self, event: Any | None) -> None:
        """Move the crosshair to the pointer, across every chart axes.

        Always a full draw_idle() rather than blitting: the hover
        annotation's blit restores a *cached* background snapshot, and
        that snapshot is only ever valid with the crosshair at the
        position it was captured at. Keeping the crosshair on the blit
        path too would mean re-capturing the background on every single
        pointer move - the crosshair's whole reason to exist - which
        defeats blitting's purpose anyway. draw_idle() here also drops
        _hover_background through the existing draw_event connection
        (_invalidate_hover_background), so the *next* blit-only hover
        update - crosshair off, or pointer over a bare point - always
        recaptures a fresh background rather than reusing a stale one.
        """
        if event is None or event.xdata is None:
            self._hide_crosshair()
            return

        active_axes = event.inaxes
        for axes in self._figure.axes:
            if not hasattr(axes, "_chartlibre_axis_id"):
                continue  # a colorbar or other helper axes, not a chart one

            vline = self._crosshair_vlines.get(axes)
            if vline is None:
                vline = axes.axvline(
                    event.xdata,
                    color=self.CROSSHAIR_COLOR,
                    linewidth=0.8,
                    linestyle="--",
                    zorder=9_000,
                )
                self._crosshair_vlines[axes] = vline
            else:
                vline.set_xdata([event.xdata, event.xdata])
            vline.set_visible(True)

            hline = self._crosshair_hlines.get(axes)
            if axes is active_axes and event.ydata is not None:
                if hline is None:
                    hline = axes.axhline(
                        event.ydata,
                        color=self.CROSSHAIR_COLOR,
                        linewidth=0.8,
                        linestyle="--",
                        zorder=9_000,
                    )
                    self._crosshair_hlines[axes] = hline
                else:
                    hline.set_ydata([event.ydata, event.ydata])
                hline.set_visible(True)
            elif hline is not None:
                hline.set_visible(False)

        self._canvas.draw_idle()

    def _hide_crosshair(self) -> None:
        """Hide every crosshair line without discarding the artists."""
        changed = False
        for line in (*self._crosshair_vlines.values(), *self._crosshair_hlines.values()):
            if line.get_visible():
                line.set_visible(False)
                changed = True
        if changed:
            self._canvas.draw_idle()

    def _connect_x_sync_callbacks(self) -> None:
        """Wire every chart axes' xlim_changed to the link-zoom sync.

        xlim_changed fires however the limits changed - scroll zoom, the
        Matplotlib toolbar's pan/zoom tools, a rectangle zoom - so this one
        connection covers all of them rather than patching each entry
        point that can move an axes' x range.
        """
        for axes in self._figure.axes:
            if hasattr(axes, "_chartlibre_axis_id"):
                axes.callbacks.connect("xlim_changed", self._on_axes_xlim_changed)  # pyright: ignore[reportAttributeAccessIssue]

    def _on_axes_xlim_changed(self, changed_axes: Any) -> None:
        """Apply one axes' new x range to every other chart axes that reads x the same way.

        Guarded by _syncing_x_limits: setting another axes' xlim fires its
        own xlim_changed right back at this same callback, and without the
        guard two linked axes would bounce the change back and forth.

        A dated axis and a lag axis are both plain numbers to Matplotlib, so
        a range moves only between axes of the same kind: a lag of 40 is not
        the day 40 after 1970. Back, Forward and Home are left out as well
        (see ChartNavigation._update_view): each axes gets its stored view.
        """
        if not self._link_x_zoom_enabled or self._syncing_x_limits or self._toolbar.restoring_views:
            return

        xlim = changed_axes.get_xlim()
        dated = _is_date_axis(changed_axes)
        self._syncing_x_limits = True
        try:
            for axes in self._figure.axes:
                if axes is changed_axes or not hasattr(axes, "_chartlibre_axis_id"):
                    continue
                if _is_date_axis(axes) == dated and axes.get_xlim() != xlim:
                    axes.set_xlim(xlim)
        finally:
            self._syncing_x_limits = False
        self._canvas.draw_idle()

    # ------------------------------------------------------------------
    # Draggable annotations
    # ------------------------------------------------------------------
    def _init_annotation_drag(self) -> None:
        """Reset drag state to "nothing being dragged"."""
        #: (axis_id, annotation index, artist, axes) of the annotation
        #: currently being dragged, or None. The axes is kept alongside the
        #: axis id so a drop can be refused if the pointer left it - x/y
        #: from a different axes' coordinate system would be meaningless
        #: written onto this one.
        self._dragging_annotation: tuple[int, int, Any, Any] | None = None

    def _discard_annotation_drag(self) -> None:
        """Forget an in-progress drag after figure.clear() destroyed its artist."""
        self._dragging_annotation = None

    def _annotation_artist_at(self, axes: Any, event: Any) -> tuple[int, Any] | None:
        """Return (index, artist) for the axis annotation under *event*.

        Hit-tests only artists BaseAxisRenderer.apply_annotation tagged
        with ``_chartlibre_annotation_index`` - the hover readout, a
        measurement's label, and any other Text this axes happens to carry
        are left alone; none of them are ever tagged.
        """
        for artist in axes.texts:
            index = getattr(artist, "_chartlibre_annotation_index", None)
            if index is None:
                continue
            try:
                hit, _details = artist.contains(event)
            except Exception:
                continue
            if hit:
                return int(index), artist
        return None

    def _on_annotation_drag_press(self, event: Any) -> None:
        """Start dragging an axis annotation, if the click landed on one.

        Left button only, and only while no Matplotlib navigation tool
        (pan/zoom) is active - those clicks belong to the toolbar, not to
        this. Also skipped while box selection is the active tool, so a
        drag never has to guess whether it started a selection or moved
        an annotation.
        """
        if self._select_mode_enabled or getattr(self, "_draw_tool", None) is not None:
            return
        if event.button != 1 or event.inaxes is None:
            return
        if str(getattr(self._toolbar, "mode", "")) != "":
            return

        axis_id = getattr(event.inaxes, "_chartlibre_axis_id", None)
        if axis_id is None:
            return

        hit = self._annotation_artist_at(event.inaxes, event)
        if hit is None:
            return

        index, artist = hit
        self._dragging_annotation = (int(axis_id), index, artist, event.inaxes)

    def _on_annotation_drag_motion(self, event: Any) -> None:
        """Follow the pointer while an annotation is being dragged."""
        if self._dragging_annotation is None:
            return
        if event.inaxes is None or event.xdata is None or event.ydata is None:
            return

        _axis_id, _index, artist, axes = self._dragging_annotation
        if event.inaxes is not axes:
            return

        if hasattr(artist, "xy"):
            # An Annotation (the "arrow" type): xy is the anchor point the
            # arrow points to and the stored x/y - xyann (the text/arrow
            # tip) stays at its own offset from it, unaffected.
            artist.xy = (event.xdata, event.ydata)
        else:
            artist.set_position((event.xdata, event.ydata))
        self._canvas.draw_idle()

    def _on_annotation_drag_release(self, event: Any) -> None:
        """Finish an annotation drag: write the new position back, or snap
        back to the stored one if the drop is not usable."""
        if self._dragging_annotation is None:
            return
        axis_id, index, _artist, axes = self._dragging_annotation
        self._dragging_annotation = None

        if event.inaxes is not axes or event.xdata is None or event.ydata is None:
            self.reload()
            return

        try:
            self._repo.snapshot_for_undo(
                self._repo.DESCRIPTOR_TABLES, label=_("Move annotation")
            )
            options = dict(self._repo.get_axis_options(int(axis_id)) or {})
            annotations = list(options.get("annotations") or [])
            if index < 0 or index >= len(annotations):
                self.reload()
                return
            entry = dict(annotations[index])
            entry["x"] = float(event.xdata)
            entry["y"] = float(event.ydata)
            annotations[index] = entry
            options["annotations"] = annotations
            self._repo.set_axis_options(int(axis_id), options)
        except Exception:
            applogger.exception("Could not move the annotation.")
            self.reload()
            return

        self.reload()
        self.figure_edited.emit()

    # ------------------------------------------------------------------
    # Box selection
    # ------------------------------------------------------------------
    #: Colour for the selection rectangle - matches the crosshair rather
    #: than the ruler/hover colours, since like the crosshair this is a
    #: guide the user draws rather than a value read off the data.
    SELECT_COLOR: Final[str] = "#1f77b4"

    def _init_box_selection(self) -> None:
        """Reset box selection to "off, nothing selected"."""
        self._select_mode_enabled = False
        #: (axes, x0, y0) of the corner a drag started from, or None.
        self._selection_start: tuple[Any, float, float] | None = None
        #: The rubber-band rectangle artist while a drag is in progress.
        self._selection_rect_artist: Any | None = None
        #: The figure as drawn without the rectangle, for the drag to put the rectangle back on (blitting).
        self._selection_background: Any | None = None
        #: The last completed selection - axis id, its bounds, and per
        #: series (keyed by the series' own name, the same identity the
        #: pick/legend code already matches artists by) the descriptor
        #: fields a "Hide"/"New series" action needs. None once acted on,
        #: cleared, or the pointer draws a new one.
        self._last_selection: dict[str, Any] | None = None

    def _discard_box_selection(self) -> None:
        """Forget an in-progress drag after figure.clear() destroyed its artist.

        The completed selection survives a reload deliberately: the axes it
        refers to are gone, but its bounds and series metadata are not tied
        to any artist, so "Hide selected points" still works after e.g. a
        crosshair toggle triggers a redraw in between selecting and acting.
        """
        self._selection_start = None
        self._selection_rect_artist = None
        self._selection_background = None

    def _clamped_data_point(self, axes: Any, event: Any) -> tuple[float, float] | None:
        """The pointer in *axes*' data units, held to its edge when it has left it - another chart, the margin."""
        if event.inaxes is axes and event.xdata is not None and event.ydata is not None:
            return float(event.xdata), float(event.ydata)  # on it: exactly where matplotlib says, so a click stays one
        if event.x is None or event.y is None:
            return None
        left, bottom, right, top = axes.bbox.extents
        x, y = axes.transData.inverted().transform((min(max(float(event.x), left), right),
                                                    min(max(float(event.y), bottom), top)))
        return float(x), float(y)

    def _on_toggle_select_mode(self, checked: bool) -> None:
        if checked and getattr(self, "_draw_tool", None) is not None:
            self.set_draw_tool(None)  # one tool owns the mouse at a time
        self._select_mode_enabled = bool(checked)
        if not self._select_mode_enabled:
            self._discard_box_selection()
            self._canvas.draw_idle()

    def _on_box_select_press(self, event: Any) -> None:
        """Start a rubber-band selection, if the tool is on."""
        if not self._select_mode_enabled or event.button != 1:
            return
        if event.inaxes is None or event.xdata is None or event.ydata is None:
            return
        if not hasattr(event.inaxes, "_chartlibre_axis_id"):
            return

        self._selection_start = (event.inaxes, float(event.xdata), float(event.ydata))
        rect = Rectangle(
            (event.xdata, event.ydata),
            0,
            0,
            facecolor=self.SELECT_COLOR,
            edgecolor=self.SELECT_COLOR,
            alpha=0.15,
            linewidth=1.0,
            linestyle="--",
            zorder=9_500,
            animated=True,
        )
        event.inaxes.add_patch(rect)
        self._selection_rect_artist = rect
        # The figure is drawn once, without the rectangle; the drag then only puts the rectangle back on that
        # picture. Drawing the whole figure at every move made the drag crawl on a figure of several charts.
        self._canvas.draw()
        self._selection_background = self._canvas.copy_from_bbox(event.inaxes.bbox)
        event.inaxes.draw_artist(rect)
        self._canvas.blit(event.inaxes.bbox)

    def _on_box_select_motion(self, event: Any) -> None:
        """Grow the rubber-band rectangle to follow the pointer."""
        if self._selection_start is None or self._selection_rect_artist is None:
            return
        axes, x0, y0 = self._selection_start
        point = self._clamped_data_point(axes, event)
        if point is None:
            return

        x1, y1 = point
        self._selection_rect_artist.set_bounds(
            min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)
        )
        if self._selection_background is None:
            self._canvas.draw_idle()
            return
        self._canvas.restore_region(self._selection_background)
        axes.draw_artist(self._selection_rect_artist)
        self._canvas.blit(axes.bbox)

    def _on_box_select_release(self, event: Any) -> None:
        """Finish the drag: collect the points it covers, or drop it."""
        if self._selection_start is None:
            return
        axes, x0, y0 = self._selection_start
        self._selection_start = None
        rect_artist = self._selection_rect_artist
        self._selection_rect_artist = None
        self._selection_background = None
        if rect_artist is not None:
            rect_artist.remove()

        # Released over another chart or the margin: the box ends at the edge of the chart it started in.
        point = self._clamped_data_point(axes, event)
        if point is None:
            self._last_selection = None
            self._canvas.draw_idle()
            return

        x1, y1 = point
        x_min, x_max = sorted((x0, x1))
        y_min, y_max = sorted((y0, y1))
        if x_min == x_max or y_min == y_max:
            # A click, not a drag: the point under it selects its row - Shift adds it or takes it away - and
            # a click on nothing clears the selection.
            self._last_selection = None
            self._click_select(axes, event)
            self._canvas.draw_idle()
            return

        axis_id = int(axes._chartlibre_axis_id)
        self._last_selection = self._collect_selection(axis_id, axes, x_min, x_max, y_min, y_max)
        if self._last_selection is not None:
            # Shift-drag: the box added to what is selected.
            self._select_table_rows(self._last_selection, add="shift" in str(event.key or ""))
        self._canvas.draw_idle()

        if self._last_selection is None:
            self.selection_changed.emit(_("No points in the selection."))
            return
        point_count = sum(len(info["x"]) for info in self._last_selection["series"].values())
        self.selection_changed.emit(
            _("{count} point(s) selected across {series} series - right-click to act on them.").format(
                count=point_count, series=len(self._last_selection["series"])
            )
        )

    def _collect_selection(
        self, axis_id: int, axes: Any, x_min: float, x_max: float, y_min: float, y_max: float
    ) -> dict[str, Any] | None:
        """Return every plotted point inside the rectangle, grouped by series.

        Matched to a series descriptor by artist label, the same identity
        _on_pick and the legend toggle already use - a renderer draws a
        series' Line2D/PathCollection labelled with the series' own name.
        """
        series_rows = {str(row["name"]): row for row in self._repo.get_series(axis_id) or []}
        matches: dict[str, Any] = {}

        for artist in (*axes.lines, *axes.collections):
            label = str(artist.get_label() or "").strip()
            if not label or label.startswith("_") or label not in series_rows:
                continue

            if hasattr(artist, "get_offsets"):
                points = np.asarray(artist.get_offsets())
                if points.size == 0:
                    continue
                xs, ys = points[:, 0].astype(float), points[:, 1].astype(float)
            else:
                # The line's own data in the units its axis draws them in: a date is its day, not its count of
                # microseconds, and a category its place - the box is drawn in those units.
                x_data, y_data = artist.get_data()
                xs = self._in_axis_units(axes.xaxis, pd.Series(np.asarray(x_data)))
                ys = self._in_axis_units(axes.yaxis, pd.Series(np.asarray(y_data)))

            mask = (xs >= x_min) & (xs <= x_max) & (ys >= y_min) & (ys <= y_max)
            if not mask.any():
                continue

            row = series_rows[label]
            matches[label] = {
                "series_id": int(row["id"]),
                "sql_query": str(row["sql_query"] or ""),
                "roles": json.loads(row["roles"]) if row["roles"] else {},
                "style": json.loads(row["style_json"]) if row["style_json"] else {},
                "x": xs[mask],
                "y": ys[mask],
            }

        if not matches:
            return None
        return {
            "axis_id": axis_id,
            "x0": x_min,
            "x1": x_max,
            "y0": y_min,
            "y1": y_max,
            "series": matches,
        }

    def _axes_of(self, axis_id: int) -> Any:
        return next((a for a in self._canvas.figure.axes if getattr(a, "_chartlibre_axis_id", None) == int(axis_id)), None)

    @staticmethod
    def _in_axis_units(axis: Any, values: pd.Series) -> np.ndarray:
        """*values* as *axis* draws them: dates and categories through its own units, as the renderer's points
        were; NaN where it cannot place one."""
        coerced, temporal = coerce_axis(values)
        if temporal or coerced.notna().any():
            try:
                return np.asarray(axis.convert_units(np.asarray(coerced)), dtype=float)
            except (TypeError, ValueError, KeyError):
                return np.full(len(values), np.nan)
        # Categories: Matplotlib's own, else where the renderer put them - the tick labelled with each.
        text = values.astype(str)
        try:
            return np.asarray(axis.convert_units(np.asarray(text)), dtype=float)
        except (TypeError, ValueError, KeyError):
            ticks = {label.get_text(): float(loc) for loc, label in zip(axis.get_ticklocs(), axis.get_ticklabels())
                     if label.get_text()}
            return np.array([ticks.get(value, np.nan) for value in text], dtype=float)

    #: How near a click must be to a point to take it, in pixels (of a screen at 1x).
    CLICK_RADIUS_PX: Final[float] = 6.0

    def _click_select(self, axes: Any, event: Any) -> None:
        """A click with Select points on: its row only (Shift: in or out of the selection); nothing under it, none."""
        shift = "shift" in str(event.key or "")
        hit = self._row_under(axes, int(axes._chartlibre_axis_id), float(event.x), float(event.y))
        tables = self.row_tables()
        if hit is None:
            if shift:
                return
            self.deselect_all()
            return
        table, row_id = hit
        selected = set(self._repo.selected_row_ids(table))
        selected = selected ^ {row_id} if shift else {row_id}
        changed = {table}
        if not shift:
            for other in tables - {table}:
                if self._repo.selected_row_ids(other):
                    self._repo.select_rows(other, [])
                    changed.add(other)
        self._repo.select_rows(table, sorted(selected))
        self._draw_selected_rows()
        self.rows_selected.emit(sorted(changed))
        self.selection_changed.emit(_("{count} row(s) of '{table}' selected.").format(count=len(selected),
                                                                                        table=table))

    def has_selected_rows(self) -> bool:
        """True if any row of a table this chart reads is Selected - or a box selection is waiting for an action."""
        return bool(self._last_selection) or any(self._repo.selected_row_ids(table) for table in self.row_tables())

    def deselect_all(self) -> bool:
        """Unselect every selected row of the tables this chart reads, and forget a waiting box selection.

        The other charts and the table preview follow (rows_selected). True if there was something selected.
        """
        cleared = [table for table in self.row_tables() if self._repo.selected_row_ids(table)]
        had_box = self._last_selection is not None
        self._last_selection = None
        for table in cleared:
            self._repo.select_rows(table, [])
        self._draw_selected_rows()
        self._canvas.draw_idle()
        if cleared:
            self.rows_selected.emit(sorted(cleared))
            self.selection_changed.emit(_("Selection cleared."))
        return bool(cleared) or had_box

    def _row_under(self, axes: Any, axis_id: int, px: float, py: float) -> tuple[str, int] | None:
        """The table and row of the point nearest (*px*, *py*) - display pixels - within CLICK_RADIUS_PX."""
        radius = self.CLICK_RADIUS_PX * float(getattr(self._canvas, "device_pixel_ratio", 1) or 1)
        best: tuple[float, str, int] | None = None
        for row in self._repo.get_series(axis_id) or []:
            sql = str(row["sql_query"] or "")
            table = self._repo.row_table(sql)
            if not table:
                continue
            rows = self._repo.series_rows(sql, json.loads(row["roles"]) if row["roles"] else {})
            if rows.empty:
                continue
            points = np.column_stack([self._in_axis_units(axes.xaxis, rows["x"]),
                                      self._in_axis_units(axes.yaxis, rows["y"])])
            shown = axes.transData.transform(points)
            distance = np.hypot(shown[:, 0] - px, shown[:, 1] - py)
            if not np.isfinite(distance).any():
                continue
            index = int(np.nanargmin(distance))
            if distance[index] <= radius and (best is None or distance[index] < best[0]):
                best = (float(distance[index]), table, int(rows[ROW_ID].iloc[index]))
        return None if best is None else (best[1], best[2])

    def _select_table_rows(self, selection: dict[str, Any], *, add: bool = False) -> None:
        """Mark the rows behind the selected points Selected in their tables, and show them.

        Only for a series whose query names its rows (the row id, ROW_ID);
        every chart of those tables then rings the same rows
        (rows_selected), and so does the table preview.
        """
        by_table: dict[str, set[int]] = {}
        for info in selection["series"].values():
            table = self._repo.row_table(info["sql_query"])
            if not table:
                continue
            rows = self._repo.series_rows(info["sql_query"], info["roles"])
            axes = self._axes_of(int(selection["axis_id"]))
            if axes is None or rows.empty:
                continue
            xs, ys = self._in_axis_units(axes.xaxis, rows["x"]), self._in_axis_units(axes.yaxis, rows["y"])
            inside = (xs >= selection["x0"]) & (xs <= selection["x1"]) & (ys >= selection["y0"]) & (ys <= selection["y1"])
            by_table.setdefault(table, set()).update(int(i) for i in rows[ROW_ID][inside])
        for table, ids in by_table.items():
            self._repo.select_rows(table, sorted(ids), add=add)
        if by_table:
            self._draw_selected_rows()
            self.rows_selected.emit(sorted(by_table))

    def selected_only_tables(self) -> list[str]:
        """This chart's tables that show only their Selected rows (R-07's data filter)."""
        return sorted(table for table in self.row_tables() if self._repo.selected_only(table))

    def _set_selected_only(self, table: str, on: bool) -> None:
        self._repo.set_selected_only(table, bool(on))
        self.selected_only_changed.emit([table])

    def _on_filter_note_link(self, url: str) -> None:
        if url.startswith("show-all:"):
            self._set_selected_only(url[len("show-all:"):], False)
        elif url == "trust-functions:":
            from app.dialogs.function_trust_dialog import ask_to_trust

            if ask_to_trust(self, self._repo):
                self.functions_trusted.emit()

    def drawn_functions(self) -> set[str]:
        """The stored functions this chart draws (function data sources)."""
        queries = []
        for axes in self._canvas.figure.axes:
            axis_id = getattr(axes, "_chartlibre_axis_id", None)
            if axis_id is not None:
                queries.extend(str(row["sql_query"] or "") for row in self._repo.get_series(int(axis_id)) or [])
        return function_names(queries)

    def untrusted_functions(self) -> list[str]:
        """The stored functions this chart draws that this computer does not run: drawn empty."""
        used = self.drawn_functions()
        if not used:
            return []
        from app.data_operations import (
            sympy_store,  # SymPy: loaded only for a chart of a function
        )

        return sorted(used & {row["function_name"] for row in sympy_store.untrusted(self._repo)})

    def _update_filter_note(self) -> None:
        """Over the chart, while one of its tables shows only its Selected rows: how many of how many, and the
        way back."""
        notes = []
        for table in self.selected_only_tables():
            notes.append(_("Only the Selected rows of '{table}': {count} of {total}.").format(
                table=html.escape(table), count=len(self._repo.selected_row_ids(table)),
                total=self._repo.row_count(table))
                + f" <a href='show-all:{html.escape(table, quote=True)}'>{html.escape(_('Show all'))}</a>")
        untrusted = self.untrusted_functions()
        if untrusted:
            notes.append(_("Not drawn: {names} - the project's functions are not trusted on this computer.").format(
                names=", ".join(f"'{html.escape(name)}'" for name in untrusted))
                + f" <a href='trust-functions:'>{html.escape(_('Trust...'))}</a>")
        self._filter_note.setText("<br>".join(notes))
        self._filter_note.setVisible(bool(notes))

    #: Label of the rings round the points whose rows are Selected.
    SELECTED_ROWS_LABEL: Final[str] = "_selected_rows"

    def show_selected_rows(self, tables: list[str] | None = None) -> None:
        """Ring again the points whose rows are Selected - after *tables* (None: any) changed elsewhere."""
        if tables is not None and not set(tables) & self.row_tables():
            return
        self._draw_selected_rows()
        self._canvas.draw_idle()

    def row_tables(self) -> set[str]:
        tables: set[str] = set()
        for axes in self._canvas.figure.axes:
            axis_id = getattr(axes, "_chartlibre_axis_id", None)
            for row in (self._repo.get_series(int(axis_id)) or []) if axis_id is not None else []:
                table = self._repo.row_table(str(row["sql_query"] or ""))
                if table:
                    tables.add(table)
        return tables

    def _draw_selected_rows(self) -> None:
        """A ring round every point of this chart whose table row is Selected.

        Drawn over the chart, not part of it: on flat axes, for a series
        whose query names its rows and whose x and y are numbers. Never
        the reason a chart is not drawn.
        """
        try:
            self._draw_selected_row_rings()
        except Exception:
            applogger.exception("Could not ring the selected rows.")

    def _draw_selected_row_rings(self) -> None:
        for axes in self._canvas.figure.axes:
            for artist in [a for a in (*axes.collections, *axes.lines) if a.get_label() == self.SELECTED_ROWS_LABEL]:
                artist.remove()
        selected: dict[str, set[int]] = {}
        for axes in self._canvas.figure.axes:
            axis_id = getattr(axes, "_chartlibre_axis_id", None)
            if axis_id is None or axes.name != "rectilinear":
                continue
            for row in self._repo.get_series(int(axis_id)) or []:
                sql = str(row["sql_query"] or "")
                table = self._repo.row_table(sql)
                if not table or self._repo.selected_only(table):
                    continue  # showing only its Selected rows: every point is one, no ring needed
                if table not in selected:
                    selected[table] = set(self._repo.selected_row_ids(table))
                if not selected[table]:
                    continue
                roles = json.loads(row["roles"]) if row["roles"] else {}
                rows = self._repo.series_rows(sql, roles)
                picked = rows[rows[ROW_ID].isin(selected[table])]
                if picked.empty:
                    continue
                self._add_selected_markers(
                    axes, str(row["name"] or ""), rows, picked,
                    self._in_axis_units(axes.xaxis, picked["x"]), self._in_axis_units(axes.yaxis, picked["y"]),
                )

    @staticmethod
    def _series_marker(axes: Any, name: str, label: str) -> dict[str, Any]:
        """The marker the series *name* is drawn with on *axes*: its shape (paths or a marker code), sizes (area,
        points squared), face colours and how many points it holds. A plain circle when nothing matches."""
        from matplotlib.collections import PathCollection
        from matplotlib.colors import to_rgba

        collections = [a for a in axes.collections if isinstance(a, PathCollection) and a.get_label() != label]
        artist = next((a for a in collections if a.get_label() == name), None) or (collections[0] if collections else None)
        if artist is not None:
            artist.update_scalarmappable()
            sizes = np.asarray(artist.get_sizes(), dtype=float)
            colours = np.asarray(artist.get_facecolor(), dtype=float)
            return {"paths": artist.get_paths(), "sizes": sizes if sizes.size else np.array([36.0]),
                    "colours": colours if colours.size else np.array([to_rgba("C0")]), "count": len(artist.get_offsets())}
        lines = [ln for ln in axes.lines if str(ln.get_marker()) not in ("", "None", "none") and ln.get_label() != label]
        line = next((ln for ln in lines if ln.get_label() == name), None) or (lines[0] if lines else None)
        if line is not None:
            face = line.get_markerfacecolor()
            colour = line.get_color() if face in (None, "auto", "none") else face
            return {"marker": line.get_marker(), "sizes": np.array([float(line.get_markersize()) ** 2]),
                    "colours": np.array([to_rgba(colour)]), "count": len(line.get_xdata())}
        # A line with no marker: its selected stretch is drawn again, not dotted - on a dense line dots run together.
        bare = [ln for ln in axes.lines if ln.get_label() != label]
        line = next((ln for ln in bare if ln.get_label() == name), None) or (bare[0] if bare else None)
        if line is not None:
            return {"marker": "o", "sizes": np.array([float(line.get_linewidth()) ** 2]),
                    "colours": np.array([to_rgba(line.get_color())]), "count": len(line.get_xdata()),
                    "linewidth": float(line.get_linewidth()), "line": line}
        return {"marker": "o", "sizes": np.array([float(rcParams.get("lines.markersize", 6.0)) ** 2]),
                "colours": np.array([to_rgba("C0")]), "count": 0}

    def _add_selected_markers(self, axes: Any, name: str, rows: pd.DataFrame, picked: pd.DataFrame,
                              xs: Any, ys: Any) -> None:
        """Draw the selected points of one series as Settings > Charts says: the series' own marker, same size
        (scaled by the setting), made bold - darker, solid, heavy edged - or ringed or filled with the selection colour."""
        from matplotlib.collections import PathCollection
        from matplotlib.colors import to_rgb, to_rgba
        from matplotlib.transforms import IdentityTransform

        from app.utils.config import selected_points_size, selected_points_style

        style, scale = selected_points_style(), selected_points_size() / 100.0
        template = self._series_marker(axes, name, self.SELECTED_ROWS_LABEL)
        count = len(picked)
        positions = np.flatnonzero(rows[ROW_ID].isin(picked[ROW_ID]).to_numpy())
        sizes, colours = template["sizes"], template["colours"]
        # Per point when the series' arrays are one entry per row, otherwise the first (or the middle one).
        sizes = sizes[positions] if len(sizes) == len(rows) and len(positions) == count else np.full(count, float(np.median(sizes)))
        colours = (colours[positions] if len(colours) == len(rows) and len(positions) == count
                   else np.tile(colours[0], (count, 1)))

        def darker(colour: Any, factor: float) -> tuple[float, float, float, float]:
            red, green, blue = to_rgb(colour[:3])
            return red * factor, green * factor, blue * factor, 1.0

        if style == "ring":
            # A circle round the marker: a few points wider than it, however big it is.
            sizes = (np.sqrt(sizes) * scale + 5.0) ** 2
            face, edge, width = "none", np.array([to_rgba(self.SELECT_COLOR)] * count), 1.5
        elif style == "fill":
            sizes = sizes * scale ** 2
            face = np.array([to_rgba(self.SELECT_COLOR)] * count)
            edge, width = np.array([darker(to_rgba(self.SELECT_COLOR), 0.55)] * count), 1.2
        else:  # bold: the same marker, solid, darker and with a heavy edge
            sizes = sizes * scale ** 2
            face = np.array([darker(c, 0.8) for c in colours])
            edge, width = np.array([darker(c, 0.55) for c in colours]), 1.1
        offsets = np.column_stack([np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)])
        if "line" in template:
            # A line without markers: the selected stretch of the line as it is drawn - smoothed or thinned,
            # its own vertices at the selected x - darker and twice as thick, broken where the selection is;
            # a lone selected point is a dot as thick as that line.
            drawn = np.column_stack([np.asarray(template["line"].get_xdata(orig=False), dtype=float),
                                     np.asarray(template["line"].get_ydata(orig=False), dtype=float)])
            wanted = np.unique(offsets[:, 0][np.isfinite(offsets[:, 0])])
            nearest = np.clip(np.searchsorted(wanted, drawn[:, 0]), 1, max(len(wanted) - 1, 1)) if len(wanted) else None
            if nearest is None:
                return
            close = np.minimum(np.abs(drawn[:, 0] - wanted[nearest - 1]), np.abs(drawn[:, 0] - wanted[np.minimum(nearest, len(wanted) - 1)]))
            kept = np.flatnonzero(close <= 1e-9 * max(1.0, float(np.nanmax(np.abs(wanted)))))
            if not len(kept):
                return
            breaks = np.flatnonzero(np.diff(kept) > 1) + 1
            path = np.insert(drawn[kept], breaks, np.nan, axis=0)
            width = 2.0 * template["linewidth"] * scale
            colour = darker(colours[0], 0.7)
            axes.plot(path[:, 0], path[:, 1], color=colour, linewidth=width, linestyle="-", marker="o",
                      markersize=width, markeredgewidth=0, solid_capstyle="round", zorder=9_000,
                      label=self.SELECTED_ROWS_LABEL)
            return
        if "paths" in template:
            collection = PathCollection(template["paths"], sizes=sizes, offsets=offsets, offset_transform=axes.transData,
                                        facecolors=face, edgecolors=edge, linewidths=width, zorder=9_000,
                                        label=self.SELECTED_ROWS_LABEL)
            collection.set_transform(IdentityTransform())  # sizes are points, as Axes.scatter sets it
            axes.add_collection(collection, autolim=False)
        else:
            axes.scatter(offsets[:, 0], offsets[:, 1], s=sizes, marker=template["marker"], facecolors=face,
                         edgecolors=edge, linewidths=width, zorder=9_000, label=self.SELECTED_ROWS_LABEL)

    def _hide_selection(self) -> None:
        """Hide every selected point by rewriting its series' own query.

        Not a rowid-based Hide flag (that only ever worked for a series
        reading a plain table, and even then turned out unreliable in
        practice). Wrapping the series' existing SQL in
        a WHERE clause that keeps only the points OUTSIDE the rectangle
        works for any series, table-backed or not - the same
        "read the series' own query as a subquery" idea
        _create_series_from_selection already uses, just with the
        condition negated (De Morgan: NOT(xmin<=x<=xmax AND ymin<=y<=ymax)
        is x<xmin OR x>xmax OR y<ymin OR y>ymax) and updating the existing
        series in place instead of adding a new one.
        """
        selection = self._last_selection
        if not selection:
            return
        self._last_selection = None

        try:
            self._repo.snapshot_for_undo(
                self._repo.DESCRIPTOR_TABLES, label=_("Hide selected points")
            )
            hid_any = False
            for info in selection["series"].values():
                roles = info["roles"]
                if "x" not in roles or "y" not in roles:
                    continue
                new_sql = (
                    f"SELECT * FROM ({info['sql_query']}) "
                    f"WHERE (x < {selection['x0']!r} OR x > {selection['x1']!r} "
                    f"OR y < {selection['y0']!r} OR y > {selection['y1']!r})"
                )
                self._repo.update_series_sql_query(int(info["series_id"]), new_sql)
                hid_any = True
        except Exception:
            applogger.exception("Could not hide the selected points.")
            return

        if not hid_any:
            return
        self.reload()
        self.figure_edited.emit()

    def _create_series_from_selection(self) -> None:
        """Add one new series per selected series, holding only its selected rows.

        Works for any series query, not only a plain table: the rectangle is
        just a WHERE clause wrapped around whatever the source series already
        selects, the same "read the series' own query as a subquery" idea
        the rest of the app already leans on for a series-over-a-series.
        """
        selection = self._last_selection
        if not selection:
            return
        self._last_selection = None

        axis_id = selection["axis_id"]
        try:
            self._repo.snapshot_for_undo(
                self._repo.DESCRIPTOR_TABLES, label=_("New series from selection")
            )
            next_index = len(self._repo.get_series(axis_id) or [])
            created_any = False
            for label, info in selection["series"].items():
                sql = (
                    f"SELECT * FROM ({info['sql_query']}) "
                    f"WHERE x BETWEEN ? AND ? AND y BETWEEN ? AND ?"
                )
                frame = self._repo.query_df(
                    sql, (selection["x0"], selection["x1"], selection["y0"], selection["y1"])
                )
                if frame.empty:
                    continue
                table_name = generated_table_name(f"{label}_selection")
                self._repo.import_dataframe(frame, table_name=table_name, normalize_columns=False)
                style = dict(info["style"])
                style.pop("generated_selection", None)
                style["generated_selection"] = True
                self._repo.create_series_descriptor(
                    axis_id=axis_id,
                    series_index=next_index,
                    name=_("{name} (selection)").format(name=label),
                    sql_query=f"SELECT * FROM {quote_identifier(table_name)}",
                    roles=info["roles"],
                    style=style,
                )
                next_index += 1
                created_any = True
        except Exception:
            applogger.exception("Could not create a series from the selection.")
            return

        if not created_any:
            return
        self.reload()
        self.figure_edited.emit()

    # ------------------------------------------------------------------
    # Live updates
    # ------------------------------------------------------------------
    def _init_live_updates(self) -> None:
        """Turn live updates off and create its timer.

        Called once from __init__, not on every reload: like the crosshair
        and box-selection toggles, a person's choice to watch this chart
        live is a viewer setting that should survive the chart's own
        redraws, not something reload() resets every time it runs.
        """
        self._live_updates_enabled = False
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(LIVE_REFRESH_INTERVAL_MS)
        self._live_timer.timeout.connect(self._on_live_timer_tick)

    def _on_toggle_live_updates(self, checked: bool) -> None:
        self._live_updates_enabled = bool(checked)
        if self._live_updates_enabled:
            self._live_timer.start()
        else:
            self._live_timer.stop()

    def _on_live_timer_tick(self) -> None:
        """Redraw on the timer, unless a gesture on this chart is mid-flight.

        reload() clears the figure and rebuilds it from the descriptor, so
        a redraw arriving mid-drag would pull the artist a drag refers
        to out from under it. A completed box
        selection is not guarded here: it already survives reload() by
        design (see _discard_box_selection), so a timer tick between
        selecting and right-clicking "Hide selected" does not lose it.
        """
        if self._dragging_annotation is not None or self._selection_start is not None:
            return
        self.reload()

    # ==================================================================
    # Geometry: Resize modes, zoom, background, and the figure's geometry and metrics.
    # ==================================================================
    # ------------------------------------------------------------------
    # Resize / zoom / background helpers
    # ------------------------------------------------------------------
    def minimumSizeHint(self) -> QSize:
        """Keep parent layouts from using the chart content as minimum size."""
        return QSize(80, 60)

    def sizeHint(self) -> QSize:
        """Return a moderate preferred size, independent from canvas content."""
        return QSize(800, 450)

    def showEvent(self, event: PySide6.QtGui.QShowEvent) -> None:
        """Refresh geometry when a hidden chart tab becomes visible.

        Also a backstop for the deferred first render (see __init__'s
        ``defer_render``): MainWindow always calls ensure_rendered() itself
        before connecting the properties panel to a newly-current tab, but
        this covers becoming visible any other way too.
        """
        super().showEvent(event)
        self.ensure_rendered()
        self._schedule_canvas_geometry_sync(redraw=True, late=True)

    def event(self, event: QEvent) -> bool:
        """Catch tab/page layout events that are not resize events."""
        handled = super().event(event)
        try:
            event_type = event.type()
        except Exception:
            return handled
        if event_type == QEvent.Type.Show:
            self._schedule_canvas_geometry_sync(redraw=True, late=True)
        elif event_type in (QEvent.Type.LayoutRequest, QEvent.Type.PolishRequest):
            # A check, not a redraw: Qt posts LayoutRequest whenever a child's
            # size hint changes - the toolbar's "x=…, y=…" readout does on
            # every mouse move - and redrawing the whole figure for each one
            # made hovering cost a full draw per move. A real size change
            # still redraws, in _sync_canvas_geometry.
            self._schedule_canvas_geometry_sync(redraw=False, late=True)
        return handled

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Re-sync the canvas geometry after resize events.

        Paint events are deliberately *not* handled here.

        They used to be: the viewport's Paint was intercepted, the background
        filled by hand, and True returned.  Two things were wrong with that.
        It painted a widget from outside its own paintEvent, and returning True
        cancelled the paint Qt was about to perform - so the viewport was never
        marked clean, and the compositor was free to leave stale content
        anywhere in the window.  Tiles of unrelated widgets repeating down the
        window are what that looks like on macOS.

        Nothing had to replace it.  ``_apply_background_color_to_widgets``
        already gives the viewport ``autoFillBackground`` and the chart
        background colour, so Qt erases it on every paint through the normal
        path and the canvas draws on top.  The filter was suppressing the very
        paint that would have cleared the area it was trying to clear.
        """
        try:
            event_type = event.type()
        except Exception:
            return False

        if event_type != QEvent.Type.Resize:
            return super().eventFilter(watched, event)

        if watched is self._canvas:
            self._schedule_canvas_geometry_sync(redraw=True)
            return super().eventFilter(watched, event)

        if watched is self._fixed_scroll_area.viewport() or watched is self._chart_area:
            self._schedule_canvas_geometry_sync(redraw=True)

        return super().eventFilter(watched, event)

    def _resolved_background_color(self) -> PySide6.QtGui.QColor:
        """The colour around the figure: the theme's desk for "auto", else the configured one."""
        if str(self._background_color).strip().lower() == BACKGROUND_AUTO:
            window = QApplication.palette().color(PySide6.QtGui.QPalette.ColorRole.Window)
            return PySide6.QtGui.QColor(DESK_COLOURS[1] if window.lightness() < 128 else DESK_COLOURS[0])
        color = PySide6.QtGui.QColor(self._background_color)
        if not color.isValid():
            applogger.warning("Invalid background color %r: the theme's is used.", self._background_color)
            self._background_color = BACKGROUND_AUTO
            return self._resolved_background_color()
        return color

    def _fill_background(self, widget: QWidget) -> None:
        """Fill a widget's whole rect with the configured background colour."""
        color = self._resolved_background_color()

        painter = PySide6.QtGui.QPainter(widget)
        try:
            painter.fillRect(widget.rect(), color)
        finally:
            painter.end()

    def paintEvent(self, event: PySide6.QtGui.QPaintEvent) -> None:
        """Paint the panel background before the frame and children.

        Why this is not left to the stylesheet: in FIT_PROPORTIONAL the canvas
        is centred and smaller than the panel, so a strip of the panel is left
        uncovered.  With an opaque-painting child on top, macOS does not erase
        that strip and it keeps the previous frame's pixels.  Filling it
        explicitly costs one rect fill and removes the dependency on
        platform-specific erase behaviour.
        """
        self._fill_background(self)
        super().paintEvent(event)

    def resizeEvent(self, event: PySide6.QtGui.QResizeEvent) -> None:
        """Update canvas geometry when ChartPanel is resized."""
        super().resizeEvent(event)
        # The strip the canvas vacates belongs to the panel; ask for a repaint
        # explicitly rather than trusting the platform to invalidate the newly
        # exposed area (see paintEvent).
        self.update()
        self._schedule_canvas_geometry_sync(redraw=True)

    def set_resize_mode(
        self,
        resize_mode: str,
        *,
        persist: bool = True,
        redraw: bool = True,
    ) -> None:
        """Set resize behaviour and persist it for this figure by default."""
        self._resize_mode = self._normalized_resize_mode(resize_mode)
        is_fixed = self._resize_mode == "FIXED"

        self._zoom_fit_button.setVisible(is_fixed)
        self._zoom_slider.setVisible(is_fixed)
        self._zoom_label.setVisible(is_fixed)

        if is_fixed:
            self._move_canvas_to_fixed_page()
            self._apply_fixed_mode_pixel_size()
        else:
            self._move_canvas_to_direct_layout(
                centered=self._resize_mode == "FIT_PROPORTIONAL"
            )
            self._restore_unzoomed_figure_metrics()

        if persist:
            self._persist_chart_panel_config()
            self._persist_view_state()
        if redraw:
            self._schedule_canvas_geometry_sync(redraw=True)

    def _remove_active_chart_widget_from_layout(self) -> None:
        """Detach chart display widgets from the main layout.

        Qt layouts tolerate removeWidget() for widgets that are not currently
        managed by the layout.  Removing both possible chart widgets makes mode
        switching deterministic and prevents a hidden scroll area from remaining
        as a layout item.
        """
        self._main_layout.removeWidget(self._canvas)
        self._main_layout.removeWidget(self._fixed_scroll_area)

    def _move_canvas_to_direct_layout(self, *, centered: bool) -> None:
        """Put the canvas directly in the ChartPanel layout for FIT modes.

        FIT and FIT_PROPORTIONAL intentionally share the same parent/layout
        path.  FIT lets the layout expand the canvas.  FIT_PROPORTIONAL keeps
        the same layout path, but gives the canvas a fixed proportional size
        and lets the layout center it in the chart client area.
        """
        self._remove_active_chart_widget_from_layout()

        if self._canvas.parent() is self._fixed_scroll_area.viewport():
            self._fixed_scroll_area.takeWidget()

        self._fixed_scroll_area.setVisible(False)
        self._fixed_scroll_area.lower()
        self._canvas.setParent(self._chart_area)
        self._canvas.show()
        self._canvas.raise_()

        if centered:
            self._canvas.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed,
            )
            self._main_layout.addWidget(
                self._canvas,
                1,
                Qt.AlignmentFlag.AlignCenter,
            )
        else:
            # Clear any fixed-size constraint left by FIT_PROPORTIONAL/FIXED.
            self._canvas.setMinimumSize(0, 0)
            self._canvas.setMaximumSize(QSize(16777215, 16777215))
            self._canvas.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding,
            )
            self._main_layout.addWidget(self._canvas, 1)

    def _move_canvas_to_fixed_page(self) -> None:
        """Put the canvas into the scroll area for FIXED mode."""
        self._remove_active_chart_widget_from_layout()

        if self._canvas.parent() is not self._fixed_scroll_area.viewport():
            self._fixed_scroll_area.takeWidget()
            self._fixed_scroll_area.setWidget(self._canvas)

        self._main_layout.addWidget(self._fixed_scroll_area, 1)
        self._fixed_scroll_area.setVisible(True)
        self._fixed_scroll_area.raise_()

    def set_zoom_percent(self, percent: int) -> None:
        """Set FIXED-mode zoom and persist it to user.json."""
        new_value = self._clamp_zoom(percent)
        if new_value == self._zoom_percent:
            return

        self._zoom_percent = new_value
        self._zoom_label.setText(f"{self._zoom_percent}%")

        if self._zoom_slider.value() != self._zoom_percent:
            self._zoom_slider.blockSignals(True)
            self._zoom_slider.setValue(self._zoom_percent)
            self._zoom_slider.blockSignals(False)

        if self._resize_mode == "FIXED":
            self._apply_fixed_mode_pixel_size()
            self._schedule_canvas_geometry_sync(redraw=True)

        self._persist_chart_panel_config()
        self._persist_view_state()

    def _apply_background_color_to_widgets(self) -> None:
        """Apply the panel background without changing the Matplotlib figure.

        The background belongs to the Qt client area around the canvas.  It must
        be visible in FIT_PROPORTIONAL margins and in the FIXED scroll viewport,
        but it must not alter Matplotlib figure or axes face colors.

        ``autoFillBackground`` here is what erases the scroll viewport before
        each paint, which matters because the canvas sets WA_OpaquePaintEvent
        and so paints only its own rect.  Do not add a Paint handler for the
        viewport on top of this: one existed, returned True, and cancelled this
        erase - see eventFilter.
        """
        qcolor = self._resolved_background_color()
        color_name = qcolor.name()

        for widget in self._background_painted_widgets():
            widget.setAutoFillBackground(True)
            widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            palette = widget.palette()
            palette.setColor(PySide6.QtGui.QPalette.ColorRole.Window, qcolor)
            palette.setColor(PySide6.QtGui.QPalette.ColorRole.Base, qcolor)
            widget.setPalette(palette)

        # Style sheets make the background deterministic even when the app-wide
        # QSS disables palette painting for QFrame/QScrollArea descendants.
        # The chart area by name too: the panel's own sheet re-polishes its
        # children, which put the window's palette back on it and left the
        # toolbar row a lighter grey strip above the desk.
        self.setStyleSheet(
            f"QFrame#ChartPanel {{ background-color: {color_name}; }} "
            f"QWidget#chartArea {{ background-color: {color_name}; }}"
        )
        self._fixed_scroll_area.setStyleSheet("QScrollArea#chartScrollArea { "
            f"background-color: {color_name}; border: none; "
            "}"
        )
        self._fixed_scroll_area.viewport().setStyleSheet(f"background-color: {color_name};")

    def _background_painted_widgets(self) -> tuple[QWidget, ...]:
        """Return widgets that should show the chosen background colour."""
        # Not the notes pane under the chart: it is a page of text, on the
        # base colour like every other, not part of the desk.
        return (
            self,
            self._chart_area,
            self._fixed_scroll_area,
            self._fixed_scroll_area.viewport(),
        )

    def _schedule_canvas_geometry_sync(self, *, redraw: bool, late: bool = False) -> None:
        """Coalesce resize-driven canvas updates using owned timers.

        The old gwXG sizing path is kept intact.  The only change here is that
        the callback is owned by the widget, so it cannot fire after close, and
        a late pass is available for tab activation/final layout geometry.
        """
        self._pending_canvas_redraw = self._pending_canvas_redraw or bool(redraw)

        if not self._pending_canvas_sync:
            self._pending_canvas_sync = True
            self._canvas_sync_timer.start(0)

        if late:
            self._canvas_late_sync_timer.start(80)

    def _run_pending_canvas_geometry_sync(self) -> None:
        """Run the pending geometry sync with the merged redraw flag."""
        if self._deleted:
            return
        redraw = self._pending_canvas_redraw
        self._pending_canvas_redraw = False
        self._sync_canvas_geometry(redraw=redraw)

    def _sync_canvas_geometry(self, *, redraw: bool) -> None:
        """Synchronize canvas and Matplotlib figure geometry.

        FIT is pure Qt layout management.  The canvas receives its size from
        the ChartPanel layout and this method only redraws when that size
        changes.

        FIT_PROPORTIONAL stays as close as possible to FIT: the canvas is still
        a direct widget in the ChartPanel layout.  The only difference from FIT
        is that the canvas width and height are fixed to the largest size that
        preserves the natural figure aspect ratio inside the same chart client
        area used by FIT.

        FIXED moves the canvas into _fixed_scroll_area and gives it the zoomed,
        fixed figure pixel size.
        """
        self._pending_canvas_sync = False
        figure_before = (tuple(self._figure.get_size_inches()), self._figure.dpi)

        if self._resize_mode == "FIXED":
            target_size = self._current_figure_pixel_size(apply_zoom=True)
            self._canvas.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed,
            )
            if self._canvas.size() != target_size:
                self._canvas.setFixedSize(target_size)
                self._fixed_scroll_area.viewport().update()
            self._apply_figure_size_from_canvas(target_size)

        elif self._resize_mode == "FIT_PROPORTIONAL":
            area_size = self._direct_chart_client_size()
            if area_size.width() <= 0 or area_size.height() <= 0:
                return

            target_size = self._proportional_size_for_viewport(area_size)
            self._canvas.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed,
            )
            if self._canvas.size() != target_size:
                self._canvas.setFixedSize(target_size)
                self._main_layout.invalidate()

            self._apply_figure_size_from_canvas(target_size)

        else:
            # FIT: the layout owns the widget geometry.  Do not call
            # setFixedSize(), resize(), or updateGeometry() here, otherwise Qt
            # and the manual synchronizer can enter a resize feedback loop.
            # Still update Matplotlib's logical figure size from the canvas that
            # Qt has assigned.  Without this, tab switches and dialog closes can
            # leave the drawing using the previous panel's inches/DPI even
            # though the QWidget has a new pixel size.
            target_size = QSize(self._canvas.size())
            if target_size.width() <= 0 or target_size.height() <= 0:
                return
            self._apply_figure_size_from_canvas(target_size)

        if getattr(self._canvas, "resize_deferred", False):
            return  # mid-resize: the canvas draws once the size settles (W-04)
        figure_changed = (tuple(self._figure.get_size_inches()), self._figure.dpi) != figure_before
        if redraw or figure_changed or target_size != self._last_canvas_size:
            self._last_canvas_size = QSize(target_size)
            # Not when the canvas already shows exactly this figure at this
            # size - a resize Matplotlib redrew for itself, a tab shown again:
            # each such second draw cost a whole render of the figure.
            # Nor for a tab nobody can see: showEvent asks again when it is.
            if self._drawn_state != self._draw_state() and self.isVisible():
                self._canvas.draw_idle()

    def _direct_chart_client_size(self) -> QSize:
        """Return the chart area available below the toolbar row."""
        contents = self._chart_area.contentsRect()
        top_row_height = self._top_row.height() if self._top_row.isVisible() else 0
        layout_spacing = self._main_layout.spacing() if top_row_height > 0 else 0
        width = max(0, contents.width())
        height = max(0, contents.height() - top_row_height - layout_spacing)
        return QSize(width, height)

    def _apply_figure_size_from_canvas(self, canvas_size: QSize) -> None:
        """Make Matplotlib's figure size match the canvas.

        ``canvas_size`` is in logical pixels; ``figure.dpi`` counts device
        pixels, because ``FigureCanvasQT._update_pixel_ratio`` multiplied it by
        the display's ratio.  The two have to be reconciled, and this is the
        conversion Matplotlib itself performs in ``FigureCanvasQT.resizeEvent``:

            w = event.size().width() * self.device_pixel_ratio
            winch = w / self.figure.dpi

        Dropping the ratio - which this method used to do - makes the figure
        half the size of the widget on a 2x screen.  Agg then paints a quarter
        of the widget's area and the remainder keeps whatever the backing store
        held, which is the field of artefacts reported on macOS and never on
        Windows, where the ratio is 1 and the mistake cancels out.
        """
        if getattr(self._canvas, "resize_deferred", False):
            return  # the figure keeps its size until the resize settles (W-04)
        if canvas_size.width() <= 0 or canvas_size.height() <= 0:
            return

        # FIXED too: the canvas is a whole number of pixels, and the figure
        # takes exactly those. Putting the configured inches back (6.4 where
        # 781 pixels at 122% make 6.4016) left the figure a pixel off its own
        # canvas - redrawn twice on every show, or, once that was suppressed,
        # left with a fresh blank buffer of the new size. The configured
        # inches stay in _fixed_figure_size_inches, for export.
        width_in = logical_to_inches(canvas_size.width(), self._figure, self._canvas)
        height_in = logical_to_inches(canvas_size.height(), self._figure, self._canvas)
        self._figure.set_size_inches(width_in, height_in, forward=False)

    def _proportional_size_for_viewport(self, viewport_size: QSize) -> QSize:
        """Return largest size inside viewport preserving current aspect ratio."""
        viewport_width = max(1, viewport_size.width())
        viewport_height = max(1, viewport_size.height())
        ratio = self._current_figure_aspect_ratio()

        width_from_height = int(round(float(viewport_height) * ratio))
        if width_from_height <= viewport_width:
            return QSize(max(1, width_from_height), viewport_height)

        height_from_width = int(round(float(viewport_width) / ratio))
        return QSize(viewport_width, max(1, height_from_width))

    def _clamp_zoom(self, percent: int) -> int:
        return max(self._min_zoom_percent, min(self._max_zoom_percent, int(percent)))

    def _current_figure_aspect_ratio(self) -> float:
        """Return the unzoomed rendered figure aspect ratio.

        FIT_PROPORTIONAL must preserve the chart's natural rendered aspect, not
        the current canvas aspect.  In FIT mode the Matplotlib figure is resized
        to the available client rectangle, so using figure.get_size_inches()
        here would make proportional mode inherit the last FIT rectangle and
        look identical to FIT.  The captured fixed metrics are the stable source
        of truth for proportional sizing.
        """
        try:
            width_in, height_in = self._fixed_figure_size_inches
            width_value = float(width_in)
            height_value = float(height_in)
        except (TypeError, ValueError):
            return DEFAULT_ASPECT_RATIO

        if width_value <= 0.0 or height_value <= 0.0:
            return DEFAULT_ASPECT_RATIO

        return width_value / height_value

    # ------------------------------------------------------------------
    # Descriptor and pre-render geometry normalization
    # ------------------------------------------------------------------
    def _descriptor_prepared_for_render(
        self,
        descriptor: Any,
        *,
        axis_count_override: int | None = None,
    ) -> Any:
        """Return a render descriptor with oversized/inconsistent grids fixed.

        The grid-normalization logic itself lives in ``app.charts.
        descriptor_grid`` - it is pure descriptor-tree manipulation with
        nothing Qt about it, and is tested there directly.
        """
        prepared, changed = descriptor_prepared_for_render(
            descriptor, axis_count_override=axis_count_override
        )
        if changed:
            applogger.debug(
                "Normalized chart grid before render (figure_id=%s, axes=%s)",
                self._figure_id,
                axis_count_override
                if axis_count_override is not None
                else descriptor_axis_count(descriptor),
            )
        return prepared

    def _prepare_canvas_geometry_before_render(self) -> None:
        """Synchronize Qt and Matplotlib sizes before rendering.

        ``reload()`` may be called immediately after a modal dialog closes, while
        Qt still has stale splitter/tab geometry cached.  For FIT modes the
        Matplotlib figure size is derived from the *current* chart client area,
        so force the owning window layouts to settle, read the visible size, and
        apply that size before the descriptor is rendered.
        """
        self._activate_current_layouts()

        if self._resize_mode == "FIXED":
            self._apply_fixed_mode_pixel_size()
            self._apply_figure_size_from_canvas(self._current_figure_pixel_size(apply_zoom=True))
            return

        area_size = self._current_fit_client_size()
        if area_size.width() <= 0 or area_size.height() <= 0:
            return

        if self._resize_mode == "FIT_PROPORTIONAL":
            target_size = self._proportional_size_for_viewport(area_size)
            self._canvas.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed,
            )
            self._canvas.setFixedSize(target_size)
            self._main_layout.invalidate()
        else:
            target_size = area_size
            self._canvas.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding,
            )
            self._canvas.setMinimumSize(0, 0)
            self._canvas.setMaximumSize(16777215, 16777215)
            self._canvas.resize(target_size.width(), target_size.height())

        self._apply_figure_size_from_canvas(target_size)
        self._last_canvas_size = QSize(target_size)

    def _current_fit_client_size(self) -> QSize:
        """Return the best current canvas area for FIT-style reloads.

        The direct chart client rectangle is authoritative once layouts are
        settled.  If Qt still reports an empty size, fall back to the visible
        window dimensions so reload can still render a sensible fitted figure.
        """
        area_size = self._direct_chart_client_size()
        if area_size.width() > 0 and area_size.height() > 0:
            return area_size
        return self._fallback_chart_client_size_from_window()

    def _activate_current_layouts(self) -> None:
        """Ask Qt layouts to resolve the current window/widget geometry now."""
        app = QApplication.instance()
        if app is not None:
            # Only the pending layout requests, never a full processEvents():
            # this runs from showEvent, e.g. in the middle of QTabWidget.clear()
            # after an Undo, and a full pass would run other queued actions
            # (re-entrantly adding/removing tabs and views) and crash Qt.
            app.sendPostedEvents(None, int(QEvent.Type.LayoutRequest))

        for widget in (self.window(), self, self._content_split, self._chart_area):
            if isinstance(widget, QWidget):
                widget.updateGeometry()
            layout = widget.layout() if isinstance(widget, QWidget) else None
            if layout is not None:
                layout.activate()

        self._fixed_scroll_area.updateGeometry()
        self._fixed_scroll_area.viewport().updateGeometry()

    def _fallback_chart_client_size_from_window(self) -> QSize:
        """Estimate chart client size from the visible window when layout is stale."""
        window = self.window()
        width = max(self._chart_area.width(), self.width())
        height = max(self._chart_area.height(), self.height())

        if isinstance(window, QWidget):
            window_size = window.size()
            width = max(width, window_size.width())
            height = max(height, window_size.height())

        top_row_height = self._top_row.sizeHint().height() if self._top_row.isVisible() else 0
        notes_height = self._notes_view.height() if self._notes_view.isVisible() else 0
        height = max(0, height - top_row_height - notes_height)
        return QSize(max(0, width), max(0, height))

    # ------------------------------------------------------------------
    # Config and figure metrics
    # ------------------------------------------------------------------
    def _chart_config(self) -> dict[str, Any]:
        """Return this panel's own section as a real dict."""
        return get_section(CONFIG_SECTION)

    def _refresh_config_from_source(self) -> None:
        """Reload this panel's section through the app.utils.config API."""
        self._config = self._chart_config()

    def _apply_persisted_figure_metrics_to_rcparams(self) -> None:
        """Apply this figure's own width, height and DPI to rcParams.

        Read from the figure descriptor rather than from config.json: the
        metrics belong to the figure, so every panel has to set them before it
        renders instead of inheriting whatever the previously-opened figure
        left in this process-wide rcParams.

        A figure with no metrics of its own falls back to Matplotlib's own
        defaults, *not* to whatever the last figure left in rcParams. Leaving
        rcParams untouched meant a plain figure inherited the width, height
        and dpi of the last figure that did carry metrics - so it rendered
        oversized, and FIXED-mode "fit to width" then fitted that wrong size.
        """
        try:
            descriptor = self._repo.load_figure_descriptor(self._figure_id)
            options = getattr(descriptor, "options", None) if descriptor else None
            metrics = figure_metrics_from_options(
                options if isinstance(options, dict) else None
            )
            if metrics is None:
                width_in, height_in = DEFAULT_FIGURE_SIZE_IN
                dpi = DEFAULT_FIGURE_DPI
            else:
                width_cm, height_cm, dpi = metrics
                width_in = width_cm / CM_PER_INCH
                height_in = height_cm / CM_PER_INCH

            rcParams["figure.figsize"] = [width_in, height_in]
            rcParams["figure.dpi"] = dpi

            # And the FIXED baseline, which is the same statement: this is the
            # size the figure is configured to be.
            #
            # Without this the baseline was only ever *captured from the last
            # render* - and in FIXED mode what gets rendered is the baseline
            # itself, so it fed on its own output. Whatever the first render
            # produced became permanent, and the width and height typed into
            # the figure properties were applied to rcParams, applied to the
            # figure, and then overwritten by the stale baseline before the
            # descriptor was drawn. Which is exactly how they "were ignored".
            self._fixed_figure_size_inches = (width_in, height_in)
            self._fixed_figure_dpi = float(dpi)
        except Exception:
            applogger.exception(
                "Failed to apply figure metrics (figure_id=%s)", self._figure_id
            )

    def _reset_figure_metrics_from_rcparams_for_reload(self) -> None:
        """Reset logical figure size and base DPI from current rcParams."""
        try:
            figsize = rcParams.get("figure.figsize", None)
            dpi = rcParams.get("figure.dpi", None)

            if figsize is not None and len(figsize) >= 2:
                width_in = float(figsize[0])
                height_in = float(figsize[1])
                if width_in > 0.0 and height_in > 0.0:
                    self._figure.set_size_inches(width_in, height_in, forward=False)

            if dpi is not None and float(dpi) > 0.0:
                # On screen a figure is drawn at the screen's density in every
                # mode, as FIXED already did: its own dpi is an export
                # resolution (Save figure, reports, the project preview), and
                # drawing at it scaled the text with it - a 200 dpi figure in
                # a FIT panel came out with letters twice the size.
                self._set_configured_dpi(FIXED_MODE_SCREEN_DPI)
        except Exception:
            applogger.exception(
                "Failed to reset figure metrics from rcParams (figure_id=%s)",
                self._figure_id,
            )

    def _set_configured_dpi(self, dpi: float) -> None:
        """Set the figure's dpi from a value the user configured.

        ``figure.dpi`` is expected to be in device pixels everywhere else in
        this class, because that is the invariant the Qt backend maintains:
        ``_set_device_pixel_ratio`` multiplies the dpi by the display's ratio
        and only revisits it when the ratio itself changes.

        rcParams and the figure's options hold the dpi the user asked for, with no
        ratio in it.  Writing that straight onto the figure - which this used
        to do on every reload - silently breaks the invariant for the rest of
        the session, and the figure comes out at the wrong size against the
        canvas again.  Reloading a chart was enough to bring the artefacts back
        on a Retina screen even after the resize path was fixed.

        ``_canvas`` may not exist yet: the constructor prepares the figure from
        rcParams before building the canvas around it.  That is not a problem
        to work around, because ``FigureCanvasQT.__init__`` applies the ratio to
        whatever dpi it finds - so the figure ends up correctly scaled either
        way, and the only thing needed here is not to raise.
        """
        apply_configured_dpi(self._figure, getattr(self, "_canvas", None), dpi)

    def _capture_fixed_metrics_from_rendered_figure(self) -> None:
        """Capture rendered figure metrics for FIXED mode."""
        try:
            width_in, height_in = self._figure.get_size_inches()

            if float(width_in) > 0.0 and float(height_in) > 0.0:
                self._fixed_figure_size_inches = (float(width_in), float(height_in))

            # The dpi is *not* read back from the figure.
            #
            # Two things have been done to it by the time this runs: the Qt
            # backend multiplied it by the display's pixel ratio, and FIXED
            # mode multiplied it again by the zoom.  Capturing that as the base
            # dpi folds the zoom into the baseline, so the next zoom multiplies
            # an already-zoomed value and the chart grows without bound - which
            # is exactly how FIXED zoom stopped being correct.
            #
            # rcParams holds the dpi the user configured, with neither factor
            # in it.  That is the only stable baseline.
            self._fixed_figure_dpi = float(rcParams.get("figure.dpi", 100.0) or 100.0)
        except Exception:
            applogger.exception(
                "Failed to capture rendered figure metrics (figure_id=%s)",
                self._figure_id,
            )

    def _current_figure_pixel_size(self, *, apply_zoom: bool) -> QSize:
        """Return the FIXED-mode canvas size in *logical* pixels.

        The result goes to ``QWidget.setFixedSize``, which speaks logical
        pixels.  Sized from ``FIXED_MODE_SCREEN_DPI``, a fixed on-screen
        reference, rather than from the figure's own configured dpi - dpi is
        a print/export resolution and must not also change how big the
        figure looks on screen.  A 16 inch figure occupies 1600 logical
        pixels at 100% zoom on every display and at every configured dpi;
        only the number of device pixels behind them differs, and that is
        the backend's business rather than this method's.
        """
        try:
            width_in, height_in = self._fixed_figure_size_inches
        except (TypeError, ValueError):
            width_in, height_in = 16.0, 9.0

        zoom = self._zoom_percent / 100.0 if apply_zoom else 1.0
        return QSize(
            int(round(inches_to_logical(width_in, FIXED_MODE_SCREEN_DPI, zoom))),
            int(round(inches_to_logical(height_in, FIXED_MODE_SCREEN_DPI, zoom))),
        )

    def _restore_unzoomed_figure_metrics(self) -> None:
        """Restore captured logical size and base DPI after leaving FIXED mode."""
        try:
            width_in, height_in = self._fixed_figure_size_inches
            # The screen's density in, device dpi onto the figure; the
            # figure's own dpi stays in _fixed_figure_dpi, for saving.
            self._set_configured_dpi(FIXED_MODE_SCREEN_DPI)
            self._figure.set_size_inches(width_in, height_in, forward=False)
        except Exception:
            applogger.exception(
                "Failed to restore unzoomed figure metrics (figure_id=%s)",
                self._figure_id,
            )

    def _apply_fixed_mode_pixel_size(self) -> None:
        """Size the canvas for FIXED mode at the current zoom.

        Zoom is applied to ``FIXED_MODE_SCREEN_DPI``, the same on-screen
        reference ``_current_figure_pixel_size`` sizes the widget from - not
        to the figure's own configured dpi, which must stay a pure
        print/export setting.  The figure is rendered at exactly the dpi the
        widget's logical size needs (times the display's own pixel ratio, via
        ``_set_configured_dpi``); using the configured dpi here instead was
        what made the on-screen figure grow or shrink with it.  Width, height
        and the physical print/export size stay in inches throughout - only
        the number of on-screen pixels changes with zoom.

        Neither factor is stored: ``zoom`` from the slider, the display's
        ratio by ``_set_configured_dpi``.  Storing either one is what made
        zoom compound.
        """
        if self._resize_mode != "FIXED":
            return

        try:
            zoom = self._zoom_percent / 100.0
            width_in, height_in = self._fixed_figure_size_inches
            self._set_configured_dpi(FIXED_MODE_SCREEN_DPI * zoom)
            self._figure.set_size_inches(width_in, height_in, forward=False)
            pixels = self._current_figure_pixel_size(apply_zoom=True)
            self._canvas.setFixedSize(pixels)
            # The whole pixels the canvas got, not the inches asked for: see
            # _apply_figure_size_from_canvas.
            self._figure.set_size_inches(
                logical_to_inches(pixels.width(), self._figure, self._canvas),
                logical_to_inches(pixels.height(), self._figure, self._canvas),
                forward=False,
            )
        except Exception:
            applogger.exception(
                "Failed to apply fixed-mode pixel size (figure_id=%s)",
                self._figure_id,
            )

    # ==================================================================
    # Actions: What the panel does to its chart: copy, save, export, delete.
    # ==================================================================
    # ------------------------------------------------------------------
    # Local actions
    # ------------------------------------------------------------------
    def _canvas_to_qimage(self) -> PySide6.QtGui.QImage | None:
        """Render the current Matplotlib figure into a detached QImage."""
        self._canvas.draw()
        buffer = BytesIO()
        copy_dpi:float = self._config.get(CONFIG_COPY_DPI,600.0)

        try:
            self._figure.savefig(
                buffer,
                format="png",
                dpi=copy_dpi,
                bbox_inches=None,
                facecolor=self._figure.get_facecolor(),
                edgecolor=self._figure.get_edgecolor(),
            )
            data = buffer.getvalue()
        finally:
            buffer.close()

        image = PySide6.QtGui.QImage.fromData(data)
        if image.isNull():
            applogger.error("Failed to build QImage from in-memory PNG data.")
            return None
        return image

    def copy_chart_to_clipboard(self) -> None:
        """Copy the current chart image to the system clipboard."""
        try:
            image = self._canvas_to_qimage()
            if image is None:
                return
            PySide6.QtGui.QGuiApplication.clipboard().setImage(image)
            applogger.info("Chart copied to clipboard (figure_id=%s)", self._figure_id)
        except Exception:
            applogger.exception(
                "Failed to copy chart to clipboard (figure_id=%s)",
                self._figure_id,
            )

    def save_chart_as(self) -> None:
        """Save the chart to an image or vector format via a file dialog."""
        # The configured default decides the suggested extension and which
        # filter the dialog opens on.  Both were hard-coded to PNG while
        # config.json carried a ``save_format`` that nothing read, so the
        # preference existed and did nothing.
        from app.dialogs.settings_dialog import (
            CONFIG_SAVE_FORMAT,
            SAVE_FORMAT_FILTERS,
            normalized_save_format,
        )

        preferred = normalized_save_format(get_value(CONFIG_SAVE_FORMAT))
        extension, preferred_filter = SAVE_FORMAT_FILTERS[preferred]
        default_name = f"chart_{self._figure_id}.{extension}"

        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            _("Save chart as"),
            default_name,
            ";;".join(label for _unused, label in SAVE_FORMAT_FILTERS.values()),
            preferred_filter,
        )
        if not file_path:
            return

        try:
            # Not self._figure.dpi: in FIXED mode that now holds the on-screen
            # rendering dpi (FIXED_MODE_SCREEN_DPI times zoom), which has
            # nothing to do with export quality.  _fixed_figure_dpi is always
            # the dpi actually configured for this figure, screen state aside.
            self._figure.savefig(
                file_path, dpi=self._fixed_figure_dpi, bbox_inches="tight"
            )
            applogger.info(
                "Chart saved (figure_id=%s, path=%s, filter=%s)",
                self._figure_id,
                file_path,
                selected_filter,
            )
        except Exception:
            applogger.exception("Failed to save chart (figure_id=%s)", self._figure_id)
            show_message(self, "chart.save_failed")

    def export_report(self) -> None:
        """The project report of this chart alone: its picture and notes."""
        from app.dialogs.project_report_dialog import ProjectReportDialog

        ProjectReportDialog(self._repo, self, figure_id=self._figure_id).exec()

    def delete_chart(self) -> None:
        """Ask for confirmation and close/delete the current chart panel."""
        if ask(self, "chart.confirm_delete"):
            self.close()

    def export_view_as_csv(self) -> None:
        """Save the rows actually on screen - after zoom and downsampling -
        as one CSV. A sibling of copy/save-chart, for the data rather than
        the picture: what a peak-fit or a "why does this look off" question
        wants is the numbers behind what is visible, not the whole series.
        """
        file_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            _("Export view as CSV"),
            f"chart_{self._figure_id}_view.csv",
            _("CSV files (*.csv)"),
        )
        if not file_path:
            return

        rows = self._current_view_rows()
        if not rows:
            show_message(self, "chart.export_view_empty")
            return

        try:
            with open(file_path, "w", newline="", encoding="utf-8") as handle:
                fieldnames: list[str] = ["axis", "series", "x", "y"]
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            applogger.info(
                "Chart view exported (figure_id=%s, path=%s, rows=%d)",
                self._figure_id,
                file_path,
                len(rows),
            )
        except OSError:
            applogger.exception("Failed to export chart view (figure_id=%s)", self._figure_id)
            show_message(self, "chart.save_failed")

    def _current_view_rows(self) -> list[dict[str, Any]]:
        """Return every plotted point currently inside its own axes' zoom.

        Each chart axes keeps its own xlim/ylim, so "the current view" is
        computed per axes rather than once for the whole figure - a
        zoomed-in panel next to an untouched one only exports the zoomed
        rows from the first.
        """
        rows: list[dict[str, Any]] = []
        for axes in self._figure.axes:
            axis_id = getattr(axes, "_chartlibre_axis_id", None)
            if axis_id is None:
                continue
            x_min, x_max = axes.get_xlim()
            y_min, y_max = axes.get_ylim()

            for artist in (*axes.lines, *axes.collections):
                label = str(artist.get_label() or "").strip()
                if not label or label.startswith("_"):
                    continue

                if hasattr(artist, "get_offsets"):
                    points = np.asarray(artist.get_offsets())
                    if points.size == 0:
                        continue
                    xs, ys = points[:, 0].astype(float), points[:, 1].astype(float)
                else:
                    x_data, y_data = artist.get_data()
                    try:
                        xs = np.asarray(x_data, dtype=float)
                        ys = np.asarray(y_data, dtype=float)
                    except (TypeError, ValueError):
                        continue

                mask = (xs >= x_min) & (xs <= x_max) & (ys >= y_min) & (ys <= y_max)
                for x_value, y_value in zip(xs[mask], ys[mask]):
                    rows.append(
                        {"axis": int(axis_id), "series": label, "x": float(x_value), "y": float(y_value)}
                    )
        return rows
