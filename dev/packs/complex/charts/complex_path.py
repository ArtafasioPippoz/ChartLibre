"""A path z(t) in the complex plane, or its image f(z(t)), coloured by t.

The rows are the points of the path: x = Re z, y = Im z, and optionally t, the parameter that
orders them and colours them (row order otherwise). Arrows along the way show the direction.

With a *Function* set, the path is first mapped through f, so the same series drawn on two axes -
one with no function, one with f - shows a curve and its image side by side, coloured alike: the
point that is yellow on the left goes where the yellow is on the right. A circle around a zero of
order n winds n times around 0 in the image; that is the argument principle, seen.
"""
from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
from matplotlib.collections import LineCollection

from app.analysis import complex_plane as cp
from app.logs.logger import applogger
from app.plugin_api.charts.base import BaseAxisRenderer, SeriesData
from app.utils.coercion import column_of, to_numbers


def path_points(sd: SeriesData) -> tuple[np.ndarray, np.ndarray]:
    """Return z and t of the series' finite rows, ordered by t (by row when t is not mapped)."""
    x = to_numbers(column_of(sd.df, "x")).to_numpy(dtype=float)
    y = to_numbers(column_of(sd.df, "y")).to_numpy(dtype=float)
    t = (to_numbers(column_of(sd.df, "t")).to_numpy(dtype=float) if "t" in sd.df.columns
         else np.arange(x.size, dtype=float))
    keep = np.isfinite(x) & np.isfinite(y) & np.isfinite(t)
    order = np.argsort(t[keep], kind="stable")
    return (x[keep] + 1j * y[keep])[order], t[keep][order]


class ComplexPathAxisRenderer(BaseAxisRenderer):
    """A curve in the complex plane, coloured by its parameter, optionally mapped through f.

    Role columns:
        x, y   required. Re z and Im z of each point of the path.
        t      optional. The parameter: orders the points and colours them. Row order without it.
    """

    Name: str = "Complex Path"
    WhenToUse: str = "Use it to follow a path z(t) in the complex plane, or to see where a function f sends it."
    Category: str = "Pairwise data"
    Description: str = (
        "A path in the complex plane coloured by its parameter, with arrows for its direction. "
        "With a function f, the image f(z(t)) is drawn instead."
    )
    Keywords: str = "numeri complessi complex path percorso curva contour argument principle mappa conforme"
    Link: str = "https://en.wikipedia.org/wiki/Conformal_map"

    RequiredRoles: ClassVar[list[str]] = ["x", "y"]
    OptionalRoles: ClassVar[list[str]] = ["t"]

    Options: ClassVar[dict[str, Any]] = {
        "function": {"default": "", "type": str, "group": "Function",
                     "description": "f(z) to map the path through, written as in Domain Colouring. "
                                    "Empty draws the path itself."},
        "cmap": {"default": "viridis", "type": str, "group": "Appearance",
                 "description": "The colormap of the parameter t."},
        "arrows": {"default": 6, "type": int, "min": 0, "max": 50, "group": "Appearance",
                   "description": "How many arrows show the direction along each path."},
        "mark_ends": {"default": True, "type": bool, "group": "Appearance",
                      "description": "A dot at the start and a square at the end."},
        "equal_scale": {"default": True, "type": bool, "group": "Appearance",
                        "description": "The same scale on Re and Im, so angles and circles look true."},
        "colorbar": {"default": False, "type": bool, "group": "Appearance",
                     "description": "A colorbar of t beside the axes."},
    }

    Kwargs: ClassVar[dict[str, Any]] = {
        "linewidth": {"default": 2.0, "type": float, "min": 0.1, "max": 20.0, "step": 0.5,
                      "group": "Appearance", "description": "Width of the path."},
        "alpha": {"default": None, "type": float, "min": 0.0, "max": 1.0, "step": 0.05,
                  "group": "Appearance", "description": "Opacity of the path."},
        "zorder": {"default": None, "type": float, "group": "Appearance",
                   "description": "Drawing order: higher draws on top."},
    }

    def render_axis(self, ax: Any, series: list[SeriesData], options: dict[str, Any] | None = None) -> None:
        options = options or {}
        kwargs = self.get_kwargs(options)
        text = str(self.opt("function", options) or "").strip()
        try:
            f = cp.compile_function(text) if text else None
        except ValueError as error:
            applogger.warning("Complex Path: %s", error)
            return
        cmap = str(self.opt("cmap", options) or "viridis")
        arrows = int(self.opt_typed("arrows", options) or 0)
        mark_ends = bool(self.opt_typed("mark_ends", options))

        paths = []
        for sd in series:
            if not dict(sd.style or {}).get("visible", True) or not self.ensure_required_roles(sd.df):
                continue
            z, t = path_points(sd)
            if z.size < 2:
                applogger.info("Series '%s' skipped: a path needs two points.", sd.name)
                continue
            paths.append((sd, f(z) if f is not None else z, t))
        if not paths:
            return
        # One colour scale for every path on the axes: the same t is the same colour everywhere.
        t_min = min(float(t.min()) for _, _, t in paths)
        t_max = max(float(t.max()) for _, _, t in paths)
        norm = (t_min, t_max if t_max > t_min else t_min + 1.0)

        collection = None
        for sd, w, t in paths:
            collection = self._draw_path(ax, sd, w, t, norm, cmap, kwargs, arrows, mark_ends)
        ax.autoscale_view()
        if bool(self.opt_typed("equal_scale", options)):
            ax.set_aspect("equal", adjustable="datalim")
        if collection is not None and bool(self.opt_typed("colorbar", options)):
            self.add_colorbar(ax, collection, options)
        self.apply_annotations(ax, options)

    @staticmethod
    def _draw_path(ax: Any, sd: SeriesData, w: np.ndarray, t: np.ndarray, norm: tuple[float, float],
                   cmap: str, kwargs: dict, arrows: int, mark_ends: bool) -> LineCollection | None:
        finite = np.isfinite(w)
        points = np.column_stack([w.real, w.imag])
        # A segment per pair of neighbours, both ends finite: a pole on the way breaks the path.
        both = finite[:-1] & finite[1:]
        segments = np.stack([points[:-1], points[1:]], axis=1)[both]
        if not len(segments):
            applogger.info("Series '%s' skipped: f is not finite along the path.", sd.name)
            return None
        middle = ((t[:-1] + t[1:]) / 2)[both]
        collection = LineCollection(segments, cmap=cmap, label=sd.name, **kwargs)
        collection.set_array(middle)
        collection.set_clim(*norm)
        ax.add_collection(collection)
        colours = collection.cmap(collection.norm(middle))

        if arrows > 0:
            # Evenly spaced along the length drawn, not along the rows: dense rows would bunch them.
            lengths = np.hypot(*np.diff(segments, axis=1)[:, 0].T)
            cumulative = np.cumsum(lengths)
            for k in range(arrows):
                index = int(np.searchsorted(cumulative, cumulative[-1] * (k + 0.5) / arrows))
                start, end = segments[min(index, len(segments) - 1)]
                if np.allclose(start, end):
                    continue
                ax.annotate("", xy=end, xytext=start,
                            arrowprops={"arrowstyle": "-|>", "color": colours[min(index, len(colours) - 1)],
                                        "lw": 0, "mutation_scale": 14})
        if mark_ends:
            first, last = points[finite][0], points[finite][-1]
            ax.plot(*first, "o", color=colours[0], markeredgecolor="black", markersize=6)
            ax.plot(*last, "s", color=colours[-1], markeredgecolor="black", markersize=6)
        return collection
