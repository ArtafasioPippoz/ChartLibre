"""Domain colouring: a complex function drawn as colour over the complex plane.

Every point z = x + iy is painted with f(z): hue for the argument, lightness for the modulus (see
app/analysis/complex_plane.py). Zeros and poles show as points where every hue meets, and the
order of one is how many times the colours go round it.

Two sources for f, chosen by what the series maps:

* **re and im mapped** - the values of f were computed elsewhere (a simulation, a measurement,
  a table), at the x/y rows of a complete grid, and are drawn as they are;
* **only x and y mapped** - f is the *Function* option, evaluated by the renderer over the range
  of the series' x and y, and evaluated again at each zoom or pan, so detail never runs out.
  The rows only say where to look.
"""
from __future__ import annotations

from typing import Any, ClassVar

import numpy as np

from app.analysis import complex_plane as cp
from app.logs.logger import applogger
from app.plugin_api.charts.base import BaseAxisRenderer, SeriesData
from app.plugin_api.charts.grids import pivot_to_grid
from app.utils.coercion import column_of, to_numbers


class DomainColouringAxisRenderer(BaseAxisRenderer):
    """A complex function as an image of the plane: hue = arg f(z), lightness = |f(z)|.

    Role columns:
        x, y     required. The real and imaginary part of z. Alone, they set the region
                 the Function option is evaluated over.
        re, im   optional, together. The real and imaginary part of f at each (x, y), on a
                 complete grid; the Function option is then not used.
    """

    Name: str = "Domain Colouring"
    WhenToUse: str = "Use it to see the zeros, poles and branch cuts of a complex function f(z)."
    Category: str = "Gridded data"
    Description: str = (
        "A complex function drawn over the complex plane: the colour is the argument of f(z), "
        "the lightness its modulus. Zeros and poles are where all the colours meet."
    )
    Keywords: str = "numeri complessi complex domain coloring colorazione dominio fase phase zeri poli"
    Link: str = "https://en.wikipedia.org/wiki/Domain_coloring"

    RequiredRoles: ClassVar[list[str]] = ["x", "y"]
    OptionalRoles: ClassVar[list[str]] = ["re", "im"]
    MaxSeries: int | None = 1

    Options: ClassVar[dict[str, Any]] = {
        "function": {"default": "(z - 1) * (z + 1j)**2 / (z**3 + 2)", "type": str,
                     "group": "Function",
                     "description": "f(z), when re and im are not mapped: z, i, pi, e, + - * / ** "
                                    "and exp, log, sqrt, sin, cos, tan, sinh, cosh, tanh, arcsin, "
                                    "arccos, arctan, abs, conj, real, imag, angle."},
        "resolution": {"default": 600, "type": int, "min": 50, "max": 3000, "step": 50,
                       "group": "Function",
                       "description": "Points across the width at which f is evaluated."},
        "modulus": {"default": cp.MODULUS_SMOOTH, "type": list(cp.MODULUS_MODES), "group": "Appearance",
                    "description": "How the modulus shows: 'smooth' darkens towards 0 and lightens "
                                   "towards infinity, 'rings' adds a ring at every doubling, 'none' "
                                   "shows the phase alone."},
        "phase_lines": {"default": 0, "type": int, "min": 0, "max": 72, "group": "Appearance",
                        "description": "Rays of constant argument drawn darker: 12 marks every 30 degrees."},
    }

    Kwargs: ClassVar[dict[str, Any]] = {
        "alpha": {"default": None, "type": float, "min": 0.0, "max": 1.0, "step": 0.05,
                  "group": "Appearance", "description": "Opacity of the image."},
        "interpolation": {"default": "antialiased", "type": ["antialiased", "nearest", "bilinear", "bicubic"],
                          "group": "Appearance", "description": "How the image is resampled on screen."},
        "zorder": {"default": None, "type": float, "group": "Appearance",
                   "description": "Drawing order: higher draws on top."},
    }

    def render_axis(self, ax: Any, series: list[SeriesData], options: dict[str, Any] | None = None) -> None:
        options = options or {}
        kwargs = self.get_kwargs(options)
        modulus = self.opt("modulus", options) or cp.MODULUS_SMOOTH
        phase_lines = int(self.opt_typed("phase_lines", options) or 0)
        for sd in series:
            if not dict(sd.style or {}).get("visible", True) or not self.ensure_required_roles(sd.df):
                continue
            try:
                if "re" in sd.df.columns and "im" in sd.df.columns:
                    self._draw_data(ax, sd, kwargs, modulus, phase_lines)
                else:
                    self._draw_function(ax, sd, options, kwargs, modulus, phase_lines)
            except ValueError as error:
                applogger.warning("Domain Colouring, series '%s': %s", sd.name, error)
            break  # one function per axes
        self.apply_annotations(ax, options)

    @staticmethod
    def _draw_data(ax: Any, sd: SeriesData, kwargs: dict, modulus: str, phase_lines: int) -> None:
        re_grid = pivot_to_grid(sd.df, z_role="re")
        im_grid = pivot_to_grid(sd.df, z_role="im")
        if re_grid is None or im_grid is None:
            raise ValueError("re and im must be given at every point of a complete x/y grid.")
        X, Y, re = re_grid
        w = re + 1j * im_grid[2]
        rgb = cp.domain_colours(w, modulus, phase_lines)
        # pivot_to_grid's arrays are indexed [y, x], which is an image's [row, column].
        ax.imshow(rgb, origin="lower", aspect="auto",
                  extent=(X.min(), X.max(), Y.min(), Y.max()), **kwargs)

    def _draw_function(self, ax: Any, sd: SeriesData, options: dict, kwargs: dict,
                       modulus: str, phase_lines: int) -> None:
        f = cp.compile_function(str(self.opt("function", options) or ""))
        resolution = int(self.opt_typed("resolution", options) or 600)
        xs = to_numbers(column_of(sd.df, "x")).to_numpy(dtype=float)
        ys = to_numbers(column_of(sd.df, "y")).to_numpy(dtype=float)
        xs, ys = xs[np.isfinite(xs)], ys[np.isfinite(ys)]
        if xs.size == 0 or ys.size == 0:
            raise ValueError("x and y have no numbers to set the region from.")
        x_range = (float(xs.min()), float(xs.max()))
        y_range = (float(ys.min()), float(ys.max()))
        if x_range[0] == x_range[1] or y_range[0] == y_range[1]:
            raise ValueError("x and y must each span a range.")

        def image_of(xr: tuple[float, float], yr: tuple[float, float]) -> np.ndarray:
            _, _, w = cp.evaluate_on_grid(f, xr, yr, resolution)
            return cp.domain_colours(w, modulus, phase_lines)

        image = ax.imshow(image_of(x_range, y_range), origin="lower", aspect="auto",
                          extent=(*x_range, *y_range), **kwargs)
        ax.set_xlim(*x_range)
        ax.set_ylim(*y_range)

        def refresh(_ax: Any = None) -> None:
            xr, yr = tuple(sorted(ax.get_xlim())), tuple(sorted(ax.get_ylim()))
            if (*xr, *yr) == tuple(image.get_extent()):
                return
            image.set_data(image_of(xr, yr))
            image.set_extent((*xr, *yr))

        # Evaluated again over whatever the view becomes: zooming never runs out of detail.
        ax.callbacks.connect("xlim_changed", refresh)
        ax.callbacks.connect("ylim_changed", refresh)
