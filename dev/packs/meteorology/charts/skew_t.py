"""Skew-T log-P: an atmospheric sounding, temperature and dew point against pressure.

The meteorologist's chart of a radiosonde's climb. Pressure falls upwards on a logarithmic scale and the
temperature axis is skewed, so that the isotherms run from the lower left to the upper right and the two curves,
which are nearly vertical in the air, spread out where they differ. Behind them: the isotherms, the dry adiabats
(the way a parcel of dry air cools as it rises) and, optionally, the lines of constant saturation mixing ratio.

Roles: pressure (hPa) and temperature (degrees C) required; dewpoint (degrees C) optional.

  https://matplotlib.org/stable/gallery/specialty_plots/skewt.html
"""
from __future__ import annotations

from typing import Any, ClassVar

import numpy as np

from app.plugin_api.charts.base import BaseAxisRenderer, SeriesData
from app.utils.coercion import column_of, to_numbers

#: The reference pressure (hPa) of the potential temperature and of the temperature axis.
_P0: float = 1000.0
#: Poisson's constant for dry air.
_KAPPA: float = 0.2854


class SkewTAxisRenderer(BaseAxisRenderer):
    """A sounding on a Skew-T log-P diagram."""

    Name: str = "Skew-T Log-P"
    WhenToUse: str = "Use it to read an atmospheric sounding: temperature and dew point against pressure."
    Category: str = "Specialized charts"
    Description: str = (
        "Temperature and dew point of a sounding against pressure, on a skewed temperature axis, over the "
        "isotherms, dry adiabats and mixing-ratio lines."
    )
    Keywords: str = "skew-t skewt log-p sounding radiosonde sondaggio atmosfera meteorologia meteo pressure pressione"
    Goals: ClassVar[list[str]] = ["describe"]
    Link: str = "https://matplotlib.org/stable/gallery/specialty_plots/skewt.html"

    RequiredRoles: ClassVar[list[str]] = ["pressure", "temperature"]
    OptionalRoles: ClassVar[list[str]] = ["dewpoint"]
    MaxSeries: int | None = 1

    Kwargs: ClassVar[dict[str, Any]] = {}

    Options: ClassVar[dict[str, Any]] = {
        "temperature_color": {"default": "#d62728", "type": str, "kind": "color", "group": "Colours",
                              "description": "The temperature curve."},
        "dewpoint_color": {"default": "#2ca02c", "type": str, "kind": "color", "group": "Colours",
                           "description": "The dew point curve."},
        "skew": {"default": 35.0, "type": float, "min": 0.0, "max": 100.0, "step": 1.0, "group": "Scale",
                 "description": "How far the isotherms lean: degrees C of shift for each unit of ln(1000 / p)."},
        "top_pressure": {"default": 100.0, "type": float, "min": 1.0, "max": 900.0, "step": 10.0, "group": "Scale",
                         "description": "The pressure at the top of the chart, in hPa."},
        "min_temperature": {"default": -40.0, "type": float, "group": "Scale",
                            "description": "The coldest temperature at the bottom edge, in degrees C."},
        "max_temperature": {"default": 40.0, "type": float, "group": "Scale",
                            "description": "The warmest temperature at the bottom edge, in degrees C."},
        "isotherms": {"default": True, "type": bool, "group": "Background", "description": "Draw the isotherms."},
        "adiabats": {"default": True, "type": bool, "group": "Background", "description": "Draw the dry adiabats."},
        "mixing_ratios": {"default": True, "type": bool, "group": "Background",
                          "description": "Draw the lines of constant saturation mixing ratio."},
    }

    def render_axis(self, ax: Any, series: list[SeriesData], options: dict | None = None) -> None:
        options = options or {}
        sd = self.single_series(series, reason="the soundings would cover each other")
        if sd is None:
            return
        style = self.merge_style(options, sd.style or {})
        pressure = to_numbers(column_of(sd.df, "pressure")).to_numpy(dtype=float)
        temperature = to_numbers(column_of(sd.df, "temperature")).to_numpy(dtype=float)
        dewpoint = (to_numbers(column_of(sd.df, "dewpoint")).to_numpy(dtype=float)
                    if "dewpoint" in sd.df.columns else np.full(pressure.size, np.nan))
        skew = float(self.opt("skew", style) or 35.0)
        top = float(self.opt("top_pressure", style) or 100.0)
        low_t = float(self.opt("min_temperature", style) if self.opt("min_temperature", style) is not None else -40.0)
        high_t = float(self.opt("max_temperature", style) if self.opt("max_temperature", style) is not None else 40.0)
        bottom = 1050.0

        def height(p: Any) -> Any:
            """The vertical position of a pressure: ln(1000 / p), so higher is lower pressure."""
            return np.log(_P0 / np.asarray(p, dtype=float))

        def across(t: Any, p: Any) -> Any:
            """The horizontal position of a temperature at a pressure: the temperature, leaned."""
            return np.asarray(t, dtype=float) + skew * height(p)

        levels = np.linspace(bottom, top, 80)
        if bool(self.opt("isotherms", style)):
            for t in np.arange(-150, 60, 10):
                ax.plot(across(t, levels), height(levels), color="0.75", linewidth=0.7, zorder=1,
                        linestyle="-" if t != 0 else "-", alpha=0.9 if t == 0 else 0.6)
        if bool(self.opt("adiabats", style)):
            for theta in np.arange(-30, 250, 10):
                t = (theta + 273.15) * (levels / _P0) ** _KAPPA - 273.15
                ax.plot(across(t, levels), height(levels), color="#c9a36b", linewidth=0.7, zorder=1, alpha=0.7)
        if bool(self.opt("mixing_ratios", style)):
            for ratio in (1, 2, 4, 8, 12, 16, 20):  # g/kg
                vapour = levels * ratio / (622.0 + ratio)  # hPa
                t = 243.5 * np.log(vapour / 6.112) / (17.67 - np.log(vapour / 6.112))
                keep = levels >= 600
                ax.plot(across(t[keep], levels[keep]), height(levels[keep]), color="#6bb26b", linewidth=0.7,
                        linestyle="--", zorder=1, alpha=0.8)

        keep = np.isfinite(pressure) & np.isfinite(temperature)
        order = np.argsort(-pressure[keep])
        p, t, td = pressure[keep][order], temperature[keep][order], dewpoint[keep][order]
        ax.plot(across(t, p), height(p), color=str(self.opt("temperature_color", style)), linewidth=2.0, zorder=3,
                label="Temperature")
        if np.isfinite(td).any():
            ax.plot(across(td, p), height(p), color=str(self.opt("dewpoint_color", style)), linewidth=2.0,
                    zorder=3, label="Dew point")

        ticks = [p_ for p_ in (1000, 850, 700, 500, 400, 300, 200, 150, 100, 70, 50) if top <= p_ <= bottom]
        ax.set_yticks(height(ticks), [f"{value:g}" for value in ticks])
        ax.set_xticks(np.arange(np.ceil(low_t / 10) * 10, high_t + 1, 10))
        ax.set_xlim(low_t, high_t)
        ax.set_ylim(float(height(bottom)), float(height(top)))
        ax.set_xlabel("Temperature (°C)")
        ax.set_ylabel("Pressure (hPa)")
        ax.grid(False)
        self.apply_annotations(ax, options)
