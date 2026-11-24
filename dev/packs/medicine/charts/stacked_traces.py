"""Stacked traces: several channels one above the other on a shared time axis, as an EEG or an ECG is read.

Each series is one channel, drawn around its own baseline, the baselines evenly spaced; the channel's name stands
at its baseline in place of a number. One scale for all, so their sizes compare.

  https://matplotlib.org/stable/gallery/specialty_plots/mri_with_eeg.html
"""
from __future__ import annotations

from typing import Any, ClassVar

import numpy as np

from app.plugin_api.charts.base import BaseAxisRenderer, SeriesData
from app.utils.coercion import column_of, to_numbers


class StackedTracesAxisRenderer(BaseAxisRenderer):
    """One trace per series, stacked on a shared x axis."""

    Name: str = "Stacked Traces"
    WhenToUse: str = "Use it to read several recorded channels, such as an EEG or an ECG, against one time axis."
    Category: str = "Specialized charts"
    Description: str = "Each series is a channel drawn around its own baseline, one above the other."
    Keywords: str = "eeg ecg ekg traces tracce canali channels elettroencefalogramma segnali stacked impilate"
    Goals: ClassVar[list[str]] = ["signal"]
    Link: str = "https://matplotlib.org/stable/gallery/specialty_plots/mri_with_eeg.html"

    RequiredRoles: ClassVar[list[str]] = ["x", "y"]
    OptionalRoles: ClassVar[list[str]] = []
    MaxSeries: int | None = None

    Kwargs: ClassVar[dict[str, Any]] = {}

    Options: ClassVar[dict[str, Any]] = {
        "spacing": {"default": None, "type": float, "group": "Scale",
                    "description": "The distance between two baselines, in the data's unit. Empty takes "
                                   "a little more than the biggest channel's range."},
        "first_on_top": {"default": True, "type": bool, "group": "Scale",
                         "description": "The first series at the top, as a recording is read."},
        "centre": {"default": True, "type": bool, "group": "Scale",
                   "description": "Take each channel's mean as its baseline."},
        "linewidth": {"default": 0.8, "type": float, "min": 0.1, "max": 5.0, "step": 0.1, "group": "Appearance",
                      "description": "The traces' width."},
    }

    def render_axis(self, ax: Any, series: list[SeriesData], options: dict | None = None) -> None:
        options = options or {}
        channels: list[tuple[str, np.ndarray, np.ndarray, dict]] = []
        for sd in series:
            x = to_numbers(column_of(sd.df, "x")).to_numpy(dtype=float)
            y = to_numbers(column_of(sd.df, "y")).to_numpy(dtype=float)
            keep = np.isfinite(x) & np.isfinite(y)
            if keep.any():
                channels.append((str(sd.name), x[keep], y[keep], self.merge_style(options, sd.style or {})))
        if not channels:
            return
        first = channels[0][3]
        centre = bool(self.opt("centre", first))
        ranges = [float(np.ptp(y)) for _n, _x, y, _s in channels]
        spacing = self.opt("spacing", first)
        try:
            spacing = float(spacing) if spacing not in (None, "") else None
        except (TypeError, ValueError):
            spacing = None
        if not spacing or spacing <= 0:
            spacing = 1.1 * (max(ranges) or 1.0)
        count = len(channels)
        baselines = []
        for index, (name, x, y, style) in enumerate(channels):
            rank = index if not bool(self.opt("first_on_top", first)) else count - 1 - index
            baseline = rank * spacing
            baselines.append(baseline)
            shifted = y - (float(y.mean()) if centre else 0.0) + baseline
            line_style = {"linewidth": float(self.opt("linewidth", style) or 0.8)}
            if style.get("color"):
                line_style["color"] = style["color"]
            ax.plot(x, shifted, label=name, **line_style)
        ax.set_yticks(baselines, [name for name, *_rest in channels])
        ax.set_ylim(-spacing, (count) * spacing)
        ax.margins(x=0.0)
        ax.grid(False, axis="y")
        self.apply_annotations(ax, options)
