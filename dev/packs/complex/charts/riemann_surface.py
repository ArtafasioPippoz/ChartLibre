"""The Riemann surface of a many-valued function: every value of w(z) at once, as one continuous sheet.

z^(p/q) has q values at each z != 0, log z infinitely many. Drawn over the plane with the height
one part of w and the colour the other, the values join into a single surface: going once around
0 climbs from one sheet to the next, and after q turns z^(p/q) is back where it started, while
log z climbs for ever - a helicoid.

The surface is drawn over polar coordinates z = r e^(i theta), with theta running over all the
turns at once rather than over [-pi, pi): that is what glues the sheets along the branch cut, so
nothing is cut and nothing is joined by a guess.
"""
from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
from matplotlib import colormaps
from matplotlib.colors import Normalize

from app.utils.logger import applogger
from app.plugin_api.charts.base import BaseAxisRenderer, SeriesData
from app.utils.coercion import column_of, to_numbers

POWER = "power"   # w = z^(p/q): q sheets
LOG = "log"       # w = log z: as many sheets as asked for


def riemann_grid(kind: str, numerator: int, denominator: int, sheets: int, radius: float,
                 radial: int, angular: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return X, Y and the complex w over the surface's polar grid.

    *angular* points per turn; theta covers every sheet: q turns for a power, *sheets* for log
    (centred on the principal one). for log, r is geometric from radius/100, since log has no value at 0.
    """
    if kind == POWER:
        q = max(int(denominator), 1)
        turns, start = q, 0.0
    elif kind == LOG:
        turns = max(int(sheets), 1)
        start = -np.pi * turns
    else:
        raise ValueError(f"Unknown function '{kind}'.")
    # log's height is ln r: geometric radii spread it, and its colours, evenly from near 0 to the edge.
    r = (np.geomspace(radius * 1e-2, radius, max(radial, 2)) if kind == LOG
         else np.linspace(0.0, radius, max(radial, 2)))
    theta = np.linspace(start, start + 2 * np.pi * turns, max(angular, 8) * turns + 1)
    R, T = np.meshgrid(r, theta)
    if kind == POWER:
        exponent = numerator / max(int(denominator), 1)
        with np.errstate(all="ignore"):
            w = R ** exponent * np.exp(1j * exponent * T)
    else:
        w = np.log(R) + 1j * T
    return R * np.cos(T), R * np.sin(T), w


class RiemannSurfaceAxisRenderer(BaseAxisRenderer):
    """z^(p/q) or log z over the plane, all of its values at once.

    Role columns:
        x, y   required. Re z and Im z: the surface is drawn out to the largest |z| of the rows.
    """

    Name: str = "Riemann Surface"
    WhenToUse: str = "Use it to see how the values of a many-valued function such as sqrt z or log z join up."
    Category: str = "3D and volumetric data"
    Description: str = (
        "All the values of z^(p/q) or log z drawn as one surface over the complex plane: one part "
        "of w as height, the other as colour. Going around 0 climbs from sheet to sheet."
    )
    Keywords: str = "superficie di riemann riemann surface numeri complessi complex radice sqrt logaritmo branch cut"
    Link: str = "https://en.wikipedia.org/wiki/Riemann_surface"
    Projection: str = "3d"

    RequiredRoles: ClassVar[list[str]] = ["x", "y"]
    OptionalRoles: ClassVar[list[str]] = []
    MaxSeries: int | None = 1

    Options: ClassVar[dict[str, Any]] = {
        "function": {"default": POWER, "type": [POWER, LOG], "group": "Function",
                     "description": "'power' is z^(p/q), with q sheets; 'log' is log z."},
        "numerator": {"default": 1, "type": int, "min": -12, "max": 12, "group": "Function",
                      "description": "p in z^(p/q)."},
        "denominator": {"default": 2, "type": int, "min": 1, "max": 12, "group": "Function",
                        "description": "q in z^(p/q): the number of sheets. 2 is the square root."},
        "sheets": {"default": 3, "type": int, "min": 1, "max": 12, "group": "Function",
                   "description": "How many turns of log z to draw."},
        "height": {"default": "imag", "type": ["imag", "real"], "group": "Appearance",
                   "description": "Which part of w is the height; the other one is the colour."},
        "cmap": {"default": "twilight", "type": str, "kind": "colormap", "group": "Appearance",
                 "description": "Colormap of the part of w that is not the height."},
        "radial": {"default": 30, "type": int, "min": 4, "max": 200, "group": "Resolution",
                   "description": "Points from 0 out to the edge."},
        "angular": {"default": 72, "type": int, "min": 8, "max": 720, "group": "Resolution",
                    "description": "Points per turn around 0."},
    }

    Kwargs: ClassVar[dict[str, Any]] = {
        "alpha": {"default": 0.9, "type": float, "min": 0.0, "max": 1.0, "step": 0.05,
                  "group": "Appearance", "description": "Opacity of the surface."},
        "linewidth": {"default": 0.0, "type": float, "min": 0.0, "max": 5.0, "step": 0.1,
                      "group": "Appearance", "description": "Width of the mesh lines; 0 hides them."},
        "edgecolor": {"default": None, "type": str, "kind": "color", "group": "Appearance",
                      "description": "Colour of the mesh lines."},
    }

    def render_axis(self, ax: Any, series: list[SeriesData], options: dict[str, Any] | None = None) -> None:
        options = options or {}
        if not hasattr(ax, "plot_surface"):
            applogger.warning("Riemann Surface needs a 3D axes.")
            return
        sd = next((s for s in series if dict(s.style or {}).get("visible", True)
                   and self.ensure_required_roles(s.df)), None)
        if sd is None:
            return
        x = to_numbers(column_of(sd.df, "x")).to_numpy(dtype=float)
        y = to_numbers(column_of(sd.df, "y")).to_numpy(dtype=float)
        modulus = np.hypot(x, y)
        modulus = modulus[np.isfinite(modulus)]
        radius = float(modulus.max()) if modulus.size else 0.0
        if radius <= 0:
            applogger.info("Riemann Surface: x and y give no radius to draw out to.")
            return
        try:
            X, Y, w = riemann_grid(str(self.opt("function", options) or POWER),
                                   int(self.opt_typed("numerator", options) or 1),
                                   int(self.opt_typed("denominator", options) or 1),
                                   int(self.opt_typed("sheets", options) or 1), radius,
                                   int(self.opt_typed("radial", options) or 30),
                                   int(self.opt_typed("angular", options) or 72))
        except ValueError as error:
            applogger.warning("Riemann Surface: %s", error)
            return
        imag_height = (self.opt("height", options) or "imag") == "imag"
        Z, C = (w.imag, w.real) if imag_height else (w.real, w.imag)
        finite = C[np.isfinite(C)]
        # The 2nd to 98th percentile: log's -infinity near 0 would otherwise take the whole colormap.
        low, high = np.percentile(finite, [2, 98]) if finite.size else (0.0, 1.0)
        norm = Normalize(float(low), float(high) if high > low else float(low) + 1.0)
        cmap = colormaps.get(str(self.opt("cmap", options) or "twilight"), colormaps["twilight"])
        kwargs = self.get_kwargs(options)
        ax.plot_surface(X, Y, Z, facecolors=cmap(norm(np.nan_to_num(C))), shade=False,
                        rstride=1, cstride=1, antialiased=False, label=sd.name, **kwargs)
        ax.set_zlabel("Im w" if imag_height else "Re w")
        self.apply_annotations(ax, options)
