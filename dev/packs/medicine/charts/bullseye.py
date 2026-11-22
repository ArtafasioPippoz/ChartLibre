"""Left ventricle bullseye: the 17-segment polar map of the American Heart Association.

The heart muscle seen from its apex as four rings - six basal segments, six mid, four apical and the apex itself
- each coloured by a value: perfusion, wall motion, strain, a score. Segments are numbered as the AHA numbers them
(1 to 6 basal from the anterior wall going anticlockwise, 7 to 12 mid, 13 to 16 apical, 17 the apex).

Roles: value required; segment optional (1 to 17; without it the rows are the segments in order).

  https://matplotlib.org/stable/gallery/specialty_plots/leftventricle_bulleye.html
"""
from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
from matplotlib.patches import Wedge

from app.plugin_api.charts.base import BaseAxisRenderer, SeriesData
from app.utils.coercion import column_of, to_numbers

#: Each ring: (inner radius, outer radius, the segments it holds), from the base to the apex.
_RINGS: tuple[tuple[float, float, int], ...] = ((0.70, 1.00, 6), (0.40, 0.70, 6), (0.18, 0.40, 4), (0.0, 0.18, 1))


class LeftVentricleBullseyeAxisRenderer(BaseAxisRenderer):
    """The 17 segments of the left ventricle, each coloured by its value."""

    Name: str = "Left Ventricle Bullseye"
    WhenToUse: str = "Use it to show one value for each of the 17 segments of the left ventricle."
    Category: str = "Specialized charts"
    Description: str = "The AHA 17-segment polar map of the heart muscle, each segment coloured by its value."
    Keywords: str = "bullseye bulleye left ventricle ventricolo sinistro cuore heart cardiology cardiologia aha polar map"
    Goals: ClassVar[list[str]] = ["compare", "describe"]
    Link: str = "https://matplotlib.org/stable/gallery/specialty_plots/leftventricle_bulleye.html"

    RequiredRoles: ClassVar[list[str]] = ["value"]
    OptionalRoles: ClassVar[list[str]] = ["segment"]
    MaxSeries: int | None = 1

    Kwargs: ClassVar[dict[str, Any]] = {}

    Options: ClassVar[dict[str, Any]] = {
        "cmap": {"default": "viridis", "type": str, "group": "Appearance",
                 "description": "The colormap the values are mapped through."},
        "vmin": {"default": None, "type": float, "group": "Appearance",
                 "description": "Value at the colormap's low end. Empty takes the smallest value."},
        "vmax": {"default": None, "type": float, "group": "Appearance",
                 "description": "Value at the colormap's high end. Empty takes the biggest value."},
        "value_labels": {"default": True, "type": bool, "group": "Labels",
                         "description": "Write each value in its segment."},
        "segment_numbers": {"default": False, "type": bool, "group": "Labels",
                            "description": "Write the AHA number of each segment instead of its value."},
        "colorbar": {"default": True, "type": bool, "group": "Colorbar", "description": "Add a colorbar."},
        "colorbar_label": {"default": None, "type": str, "group": "Colorbar",
                           "description": "Label written alongside the colorbar."},
    }

    def render_axis(self, ax: Any, series: list[SeriesData], options: dict | None = None) -> None:
        import matplotlib
        from matplotlib.cm import ScalarMappable
        from matplotlib.colors import Normalize

        options = options or {}
        sd = self.single_series(series, reason="the segments of a second heart would cover the first")
        if sd is None:
            return
        style = self.merge_style(options, sd.style or {})
        values = to_numbers(column_of(sd.df, "value")).to_numpy(dtype=float)
        if "segment" in sd.df.columns:
            numbers = to_numbers(column_of(sd.df, "segment")).to_numpy(dtype=float)
        else:
            numbers = np.arange(1, values.size + 1, dtype=float)
        by_segment = {int(n): v for n, v in zip(numbers, values) if np.isfinite(n) and 1 <= n <= 17}
        finite = [v for v in by_segment.values() if np.isfinite(v)]
        if not finite:
            return
        low = self.opt("vmin", style)
        high = self.opt("vmax", style)
        norm = Normalize(float(low) if low not in (None, "") else min(finite),
                         float(high) if high not in (None, "") else max(finite))
        cmap = matplotlib.colormaps[str(self.opt("cmap", style) or "viridis")]
        show_numbers = bool(self.opt("segment_numbers", style))
        show_values = bool(self.opt("value_labels", style)) or show_numbers

        number = 1
        for inner, outer, count in _RINGS:
            width = 360.0 / count
            for index in range(count):
                value = by_segment.get(number)
                middle = 90.0 + index * width  # the first of each ring at the top, then anticlockwise
                low_angle, high_angle = middle - width / 2.0, middle + width / 2.0
                colour = cmap(norm(value)) if value is not None and np.isfinite(value) else "#dddddd"
                if count == 1:
                    ax.add_patch(Wedge((0, 0), outer, 0, 360, facecolor=colour, edgecolor="white", linewidth=1.2))
                else:
                    ax.add_patch(Wedge((0, 0), outer, low_angle, high_angle, width=outer - inner,
                                       facecolor=colour, edgecolor="white", linewidth=1.2))
                if show_values and (value is not None or show_numbers):
                    radius = 0.0 if count == 1 else (inner + outer) / 2.0
                    angle = np.deg2rad(middle)
                    text = str(number) if show_numbers else f"{value:.3g}"
                    ax.text(radius * np.cos(angle), radius * np.sin(angle), text, ha="center", va="center",
                            fontsize="small", color="white" if _dark(colour) else "black")
                number += 1
        ax.set_xlim(-1.05, 1.05)
        ax.set_ylim(-1.05, 1.05)
        ax.set_aspect("equal", adjustable="box")
        # Not set_axis_off(): the axis options turn the axis back on after a render.
        ax.set_xticks([])
        ax.set_yticks([])
        for side in ax.spines.values():
            side.set_visible(False)
        ax.grid(False)
        if bool(self.opt("colorbar", style)):
            self.add_colorbar(ax, ScalarMappable(norm, cmap), style)
        self.apply_annotations(ax, options)


def _dark(colour: Any) -> bool:
    """True when white text reads on *colour*."""
    from matplotlib.colors import to_rgb

    red, green, blue = to_rgb(colour)
    return 0.299 * red + 0.587 * green + 0.114 * blue < 0.5
