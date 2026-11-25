"""Clicking a surface, a heatmap or a filled band reads nothing out instead of raising IndexError."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from matplotlib.figure import Figure

from app.widgets.chart_panel.panel import ChartPanel, pickable_data_artists


def _surface() -> tuple[Figure, object]:
    fig = Figure(figsize=(6, 4))
    ax = fig.add_subplot(projection="3d")
    x, y = np.meshgrid(np.linspace(-3.0, 3.0, 100), np.linspace(-3.0, 3.0, 100))
    ax.plot_surface(x, y, np.sin(np.hypot(x, y)))
    return fig, ax.collections[0]


def test_points_and_lines_are_armed_and_surfaces_and_meshes_are_not() -> None:
    fig = Figure(figsize=(6, 4))
    ax = fig.add_subplot(111)
    scatter = ax.scatter([1.0, 2.0, 3.0], [4.0, 5.0, 6.0])
    (line,) = ax.plot([1.0, 2.0], [3.0, 4.0])
    mesh = ax.pcolormesh(np.arange(25, dtype=float).reshape(5, 5))
    armed = pickable_data_artists(ax)
    assert scatter in armed and line in armed
    assert mesh not in armed

    _, surface = _surface()
    assert surface not in pickable_data_artists(surface.axes)


def test_a_pick_past_the_one_offset_of_a_surface_reads_nothing() -> None:
    _, surface = _surface()
    emitted: list[str] = []
    panel = SimpleNamespace(selection_changed=SimpleNamespace(emit=emitted.append))
    event = SimpleNamespace(artist=surface, ind=np.array([5286]))  # a face index, as matplotlib reports it
    ChartPanel._on_pick(panel, event)  # type: ignore[arg-type]
    assert emitted == []
