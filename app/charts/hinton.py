"""Hinton diagram: a matrix drawn as squares, the area of each one its value's size, its colour its sign.

White for the positive, black for the negative, on a grey ground: a weight matrix, a correlation or a transition
table read at a glance, which cell weighs most and which way. The squares fill the biggest value's cell.

  https://matplotlib.org/stable/gallery/specialty_plots/hinton_demo.html
"""
from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
from matplotlib.patches import Rectangle

from app.logs.logger import applogger
from app.plugin_api.charts.base import BaseAxisRenderer, SeriesData
from app.plugin_api.charts.grids import pivot_to_grid

#: Ticks label each cell's x or y only up to this many: past it they overlap.
MAX_TICKS: int = 40


class HintonAxisRenderer(BaseAxisRenderer):
    """Squares of area proportional to the value over a regular x/y grid."""

    Name: str = "Hinton Diagram"
    WhenToUse: str = "Use it to read the size and the sign of every value of a matrix at a glance."
    Category: str = "Gridded data"
    Description: str = (
        "A matrix as squares: the area is the size of the value, white is positive and black negative."
    )
    Keywords: str = "hinton matrix matrice weights pesi correlation correlazione squares quadrati"
    Goals: ClassVar[list[str]] = ["relate"]
    Link: str = "https://matplotlib.org/stable/gallery/specialty_plots/hinton_demo.html"

    RequiredRoles: ClassVar[list[str]] = ["x", "y", "z"]
    OptionalRoles: ClassVar[list[str]] = []
    MaxSeries: int | None = 1

    Kwargs: ClassVar[dict[str, Any]] = {}

    Options: ClassVar[dict[str, Any]] = {
        "positive_color": {"default": "#ffffff", "type": str, "kind": "color", "group": "Colours",
                           "description": "The squares of the positive values."},
        "negative_color": {"default": "#000000", "type": str, "kind": "color", "group": "Colours",
                           "description": "The squares of the negative values."},
        "background_color": {"default": "#808080", "type": str, "kind": "color", "group": "Colours",
                             "description": "The ground the squares lie on."},
        "max_value": {"default": None, "type": float, "group": "Scale",
                      "description": "The value that fills a whole cell. Empty takes the biggest size, "
                                     "rounded up to a power of two as the matplotlib example does."},
        "top_row_first": {"default": True, "type": bool, "group": "Scale",
                          "description": "Write the matrix as it is read: the lowest y at the top."},
    }

    def render_axis(self, ax: Any, series: list[SeriesData], options: dict | None = None) -> None:
        options = options or {}
        sd = self.single_series(series, reason="the squares of a second matrix would cover the first")
        if sd is None:
            return
        grid = pivot_to_grid(sd.df)
        if grid is None:
            applogger.error("A Hinton diagram needs a complete grid: every x paired with every y exactly once.")
            return
        x_grid, y_grid, z_grid = grid
        style = self.merge_style(options, sd.style or {})
        rows, columns = z_grid.shape
        values = np.where(np.isfinite(z_grid), z_grid, 0.0)
        limit = self.opt("max_value", style)
        try:
            limit = float(limit) if limit not in (None, "") else None
        except (TypeError, ValueError):
            limit = None
        if not limit or limit <= 0:
            biggest = float(np.abs(values).max()) if values.size else 0.0
            limit = 2.0 ** np.ceil(np.log2(biggest)) if biggest > 0 else 1.0

        ax.set_facecolor(str(self.opt("background_color", style)))
        positive, negative = str(self.opt("positive_color", style)), str(self.opt("negative_color", style))
        # The axis' own inversion is the axis options' (they set it afterwards): the rows are placed top first.
        top_first = bool(self.opt("top_row_first", style))
        for row in range(rows):
            place = rows - 1 - row if top_first else row
            for column in range(columns):
                value = z_grid[row, column]
                if not np.isfinite(value) or value == 0:
                    continue
                side = float(np.sqrt(min(abs(value) / limit, 1.0)))
                ax.add_patch(
                    Rectangle((column - side / 2.0, place - side / 2.0), side, side,
                              facecolor=positive if value > 0 else negative, edgecolor="none", linewidth=0))
        ax.set_xlim(-0.5, columns - 0.5)
        ax.set_ylim(-0.5, rows - 0.5)
        ax.set_aspect("equal", adjustable="box")
        x_values, y_values = x_grid[0, :], y_grid[:, 0]
        if columns <= MAX_TICKS:
            ax.set_xticks(np.arange(columns), [f"{value:.3g}" for value in x_values])
        if rows <= MAX_TICKS:
            labels = [f"{value:.3g}" for value in y_values]
            ax.set_yticks(np.arange(rows), labels[::-1] if top_first else labels)
        ax.grid(False)
        self.apply_annotations(ax, options)
