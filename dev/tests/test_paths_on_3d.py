"""Paths and shapes are 2D patches: a 3D axes neither draws them nor breaks its own draw."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from app.charts.scatter import ScatterAxisRenderer
from app.plugin_api.charts.path_geometry import format_nodes
from app.widgets.chart_panel.draw_tools import DrawToolsMixin


def _three_d_axes() -> tuple[Figure, object]:
    fig = Figure(figsize=(5, 4))
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(projection="3d")
    ax.scatter(np.arange(5.0), np.arange(5.0), np.arange(5.0))
    return fig, ax


def test_a_stored_path_on_a_3d_axes_is_skipped_and_the_chart_still_draws() -> None:
    fig, ax = _three_d_axes()
    nodes = [(0.0, 0.0, None, None), (1.0, 0.0, None, None), (1.0, 1.0, None, None)]
    ScatterAxisRenderer().apply_path(ax, {"points": format_nodes(nodes), "closed": "yes", "kwargs": {}})
    assert len(ax.patches) == 0  # no 2D patch in a 3D axes
    fig.canvas.draw()  # before the fix: AttributeError, 'PathPatch' has no do_3d_projection


def test_a_pen_or_drag_press_on_a_3d_axes_starts_nothing() -> None:
    _, ax = _three_d_axes()
    ax._chartlibre_axis_id = 1  # type: ignore[attr-defined]
    emitted: list[str] = []
    panel = SimpleNamespace(
        _draw_tool="path",
        _draw_axes=None,
        selection_changed=SimpleNamespace(emit=emitted.append),
    )
    event = SimpleNamespace(button=1, inaxes=ax, xdata=0.5, ydata=0.5, x=10.0, y=10.0)
    DrawToolsMixin._on_draw_press(panel, event)  # type: ignore[arg-type]
    assert panel._draw_axes is None
    assert len(emitted) == 1  # the readout says why nothing was drawn (the text is translated)
