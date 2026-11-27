"""Hillshade: a grid of heights lit from a direction, as a relief map.

The sun is a point of the sky (its azimuth and its height); each cell is shaded by how it faces it and tinted by
its own height - the topographic shading of matplotlib's LightSource. A surface plot shows a relief in
perspective; this one shows it from above, where the eye reads the ridges and the hollows at once.

  https://matplotlib.org/stable/gallery/specialty_plots/topographic_hillshading.html
"""
from __future__ import annotations

from typing import Any, ClassVar

import numpy as np

from app.utils.logger import applogger
from app.plugin_api.charts.base import BaseAxisRenderer, SeriesData
from app.plugin_api.charts.grids import pivot_to_grid


class HillshadeAxisRenderer(BaseAxisRenderer):
    """A relief map: the heights of a regular x/y grid, shaded by a light."""

    Name: str = "Hillshade"
    WhenToUse: str = "Use it to see the relief of a surface from above, lit from one side."
    Category: str = "Gridded data"
    Description: str = "A grid of heights shaded by a light from a chosen direction: ridges and hollows stand out."
    Keywords: str = "hillshade hillshading relief rilievo topographic topografico ombreggiatura light source"
    Goals: ClassVar[list[str]] = ["relate"]
    Link: str = "https://matplotlib.org/stable/gallery/specialty_plots/topographic_hillshading.html"

    RequiredRoles: ClassVar[list[str]] = ["x", "y", "z"]
    OptionalRoles: ClassVar[list[str]] = []
    MaxSeries: int | None = 1

    Kwargs: ClassVar[dict[str, Any]] = {}

    Options: ClassVar[dict[str, Any]] = {
        "cmap": {"default": "terrain", "type": str, "group": "Appearance",
                 "description": "The colormap of the heights, e.g. 'terrain' or 'gist_earth'."},
        "azimuth": {"default": 315.0, "type": float, "min": 0.0, "max": 360.0, "step": 5.0, "group": "Light",
                    "description": "Where the light comes from, in degrees clockwise from north (315 is the "
                                   "north-west, the way maps are lit)."},
        "altitude": {"default": 45.0, "type": float, "min": 0.0, "max": 90.0, "step": 5.0, "group": "Light",
                     "description": "How high the light is, in degrees over the horizon."},
        "vert_exag": {"default": 1.0, "type": float, "min": 0.0, "max": 100.0, "step": 0.5, "group": "Light",
                      "description": "The heights, stretched by this factor before they are lit: more makes "
                                     "the relief steeper. The cells are taken one unit apart, so it also "
                                     "sets the heights against the cell size."},
        "blend_mode": {"default": "overlay", "type": ["overlay", "soft", "hsv"], "group": "Light",
                       "description": "How the shade is blended with the colours."},
        "colorbar": {"default": False, "type": bool, "group": "Colorbar",
                     "description": "Add a colorbar for the heights."},
        "colorbar_label": {"default": None, "type": str, "group": "Colorbar",
                           "description": "Label written alongside the colorbar."},
    }

    def render_axis(self, ax: Any, series: list[SeriesData], options: dict | None = None) -> None:
        import matplotlib
        from matplotlib.colors import LightSource

        options = options or {}
        sd = self.single_series(series, reason="the second relief would cover the first")
        if sd is None:
            return
        grid = pivot_to_grid(sd.df)
        if grid is None:
            applogger.error("A hillshade needs a complete grid: every x paired with every y exactly once.")
            return
        x_grid, y_grid, z_grid = grid
        style = self.merge_style(options, sd.style or {})
        z = np.where(np.isfinite(z_grid), z_grid, np.nan)
        if not np.isfinite(z).any():
            return
        xs, ys = x_grid[0, :], y_grid[:, 0]
        dx = float(np.abs(np.diff(xs)).mean()) if xs.size > 1 else 1.0
        dy = float(np.abs(np.diff(ys)).mean()) if ys.size > 1 else 1.0
        cmap = matplotlib.colormaps[str(self.opt("cmap", style) or "terrain")]
        source = LightSource(azdeg=float(self.opt("azimuth", style) or 315.0),
                             altdeg=float(self.opt("altitude", style) or 45.0))
        shaded = source.shade(np.nan_to_num(z, nan=float(np.nanmin(z))), cmap=cmap,
                              blend_mode=str(self.opt("blend_mode", style) or "overlay"),
                              vert_exag=float(self.opt("vert_exag", style) or 1.0))
        shaded[np.isnan(z)] = 0.0  # a hole is transparent
        ascending_y = ys[0] <= ys[-1]
        extent = (float(xs.min() - dx / 2), float(xs.max() + dx / 2),
                  float(ys.min() - dy / 2), float(ys.max() + dy / 2))
        ax.imshow(shaded if ascending_y else shaded[::-1], origin="lower", extent=extent,
                             aspect="auto", interpolation="nearest")
        if bool(self.opt("colorbar", style)):
            from matplotlib.cm import ScalarMappable
            from matplotlib.colors import Normalize

            self.add_colorbar(ax, ScalarMappable(Normalize(float(np.nanmin(z)), float(np.nanmax(z))), cmap), style)
        self.apply_annotations(ax, options)
