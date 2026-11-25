"""Linked zoom keeps dated axes and lag axes apart, and Back puts every axis back on its own range.

A date axis holds days since 1970 and a lag axis holds a count of steps; to Matplotlib both are plain
numbers. Copying the dates' range onto an ACF left its lags off the plot, and Back then crowded them at 0.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter
from matplotlib.figure import Figure

from app.widgets.chart_panel.panel import ChartNavigation, ChartPanel


class _Panel:
    """The chart panel's link-zoom methods, on a bare figure with its own navigation."""

    _connect_x_sync_callbacks = ChartPanel._connect_x_sync_callbacks
    _on_axes_xlim_changed = ChartPanel._on_axes_xlim_changed

    def __init__(self, figure: Figure, toolbar: ChartNavigation) -> None:
        self._figure = figure
        self._toolbar = toolbar
        self._link_x_zoom_enabled = True
        self._syncing_x_limits = False
        self._canvas = SimpleNamespace(draw_idle=lambda: None)


def _linked_figure() -> tuple[Any, ...]:
    """Two dated axes on different stretches of days, then two lag axes of different lengths."""
    figure = Figure(figsize=(12, 3))
    dated_a, dated_b, lags_a, lags_b = figure.subplots(1, 4)
    days = np.arange(10_000.0, 12_000.0)  # days since 1970: 1997 to 2002
    dated_a.plot(days, np.sin(days / 50.0))
    dated_b.plot(days + 500.0, np.cos(days / 50.0))
    for axes in (dated_a, dated_b):
        locator = AutoDateLocator()
        axes.xaxis.set_major_locator(locator)
        axes.xaxis.set_major_formatter(ConciseDateFormatter(locator))
    lags_a.plot(np.arange(41.0), np.linspace(1.0, 0.0, 41))
    lags_b.plot(np.arange(21.0), np.linspace(1.0, 0.0, 21))
    for index, axes in enumerate(figure.axes):
        axes._chartlibre_axis_id = index  # the mark the chart panel puts on its own axes
    toolbar = ChartNavigation(FigureCanvasQTAgg(figure), None, coordinates=False)
    for axes in figure.axes:
        axes.get_xlim()  # settle each autoscale before the link is on, as a drawn figure has
    panel = _Panel(figure, toolbar)
    panel._connect_x_sync_callbacks()
    # Matplotlib holds the callbacks weakly: the panel must come back too, or it is collected at once.
    return figure, dated_a, dated_b, lags_a, lags_b, toolbar, panel


def _xlims(axes_list: tuple[Any, ...]) -> list[tuple[float, float]]:
    return [axes.get_xlim() for axes in axes_list]


def test_a_zoom_on_a_dated_axis_moves_the_dated_axes_and_not_the_lags(qapp: Any) -> None:
    _, dated_a, dated_b, lags_a, lags_b, _, _ = _linked_figure()
    lag_ranges = _xlims((lags_a, lags_b))
    dated_a.set_xlim(10_500.0, 11_000.0)
    assert dated_b.get_xlim() == dated_a.get_xlim()
    assert _xlims((lags_a, lags_b)) == lag_ranges


def test_a_zoom_on_a_lag_axis_leaves_the_dated_axes_alone(qapp: Any) -> None:
    _, dated_a, dated_b, lags_a, _, _, _ = _linked_figure()
    dated_ranges = _xlims((dated_a, dated_b))
    lags_a.set_xlim(0.0, 20.0)
    assert _xlims((dated_a, dated_b)) == dated_ranges


def test_lag_axes_still_follow_each_other(qapp: Any) -> None:
    _, _, _, lags_a, lags_b, _, _ = _linked_figure()
    lags_a.set_xlim(0.0, 20.0)
    assert lags_b.get_xlim() == (0.0, 20.0)


def test_back_puts_every_axis_back_on_its_own_range(qapp: Any) -> None:
    _, dated_a, dated_b, lags_a, lags_b, toolbar, _ = _linked_figure()
    axes = (dated_a, dated_b, lags_a, lags_b)
    home = _xlims(axes)
    toolbar.push_current()
    dated_a.set_xlim(10_500.0, 11_000.0)
    toolbar.push_current()
    toolbar.back()
    assert np.allclose(_xlims(axes), home)
