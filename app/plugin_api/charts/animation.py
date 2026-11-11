"""Animated charts: a figure played through the values of a column, or of a function's parameter (todo I-03).

Two sources of frames, one setting each, kept in the figure's options under ``"animation"``:

* **column** - each frame draws only the rows with one value of a column (a year, a time, a step), or every
  value up to it (cumulative), or the last few (trailing). The frames are queries on the same data, filtered
  by the row id the series' query names - the path Show only Selected takes - so nothing new is stored.
* **parameter** - each frame draws the figure's function series with one of the function's parameters set
  to a value between *from* and *to*: a family of curves, played. Only the series of a stored function
  change; the rest stay as they are.

A frame is drawn by rendering the figure inside ``render_figure.animation_frame``, which hands every series'
query to the frame's filter. Nothing here touches Qt: the play bar (app/widgets/chart_panel) and the GIF
export below both go through these functions.
"""
from __future__ import annotations

import io
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, fields
from typing import Any

import numpy as np

from app.data.repo.function_sql import function_sql, parse_function_sql, replace_function_sql

#: The figure option holding the settings.
OPTION_KEY = "animation"

COLUMN, PARAMETER = "column", "parameter"
EACH, CUMULATIVE, TRAILING = "each", "cumulative", "trailing"
MODES: tuple[str, ...] = (EACH, CUMULATIVE, TRAILING)


@dataclass(slots=True)
class AnimationSettings:
    """What plays and how: the figure's "animation" option."""

    source: str = COLUMN
    #: COLUMN: the column whose values are the frames.
    column: str = ""
    mode: str = EACH
    #: TRAILING: how many frames stay on, the current one included.
    trail: int = 3
    #: PARAMETER: the function parameter that varies, from, to, in how many frames.
    parameter: str = ""
    start: float = 0.0
    stop: float = 1.0
    steps: int = 20
    fps: float = 4.0
    loop: bool = True
    #: The axes keep the limits of the whole data, so nothing jumps from frame to frame.
    hold: bool = True
    #: The frame's value written at the top right of the figure.
    caption: bool = True

    @property
    def active(self) -> bool:
        return bool(self.column) if self.source == COLUMN else bool(self.parameter)

    @classmethod
    def from_options(cls, options: Any) -> AnimationSettings | None:
        """The settings stored in a figure's options, or None when it has none."""
        raw = options.get(OPTION_KEY) if isinstance(options, dict) else None
        if not isinstance(raw, dict):
            return None
        known = {item.name for item in fields(cls)}
        settings = cls(**{key: value for key, value in raw.items() if key in known})
        settings.mode = settings.mode if settings.mode in MODES else EACH
        settings.trail = max(1, int(settings.trail))
        settings.steps = max(2, int(settings.steps))
        settings.fps = min(30.0, max(0.5, float(settings.fps)))
        return settings if settings.active else None

    def to_options(self) -> dict[str, Any]:
        return asdict(self)


# ----------------------------------------------------------------------
# What the figure has to play
# ----------------------------------------------------------------------
def _series(descriptor: Any) -> list[Any]:
    return [series for axis in (descriptor.axes or []) for series in (axis.series or [])]


def series_tables(repo: Any, descriptor: Any) -> list[str]:
    """The tables the figure's series read rows of (by their row id), each once."""
    found: dict[str, None] = {}
    for series in _series(descriptor):
        table = repo.row_table(str(series.sql_query or ""))
        if table:
            found[table] = None
    return list(found)


def frame_columns(repo: Any, descriptor: Any) -> list[str]:
    """The columns a column animation can run along: those of the tables the series read."""
    names: dict[str, None] = {}
    for table in series_tables(repo, descriptor):
        names.update((str(name), None) for name in repo.get_columns(table))
    return [name for name in names if name not in ("_id", "Selected", "Hide")]


def function_parameters(descriptor: Any) -> dict[str, float]:
    """The parameters of the figure's function series, with the value each has now (the first one met)."""
    found: dict[str, float] = {}
    for series in _series(descriptor):
        query = parse_function_sql(str(series.sql_query or ""))
        if query is not None:
            for name, value in query.parameters.items():
                found.setdefault(name, float(value))
    return found


def not_animatable(descriptor: Any) -> list[str]:
    """The chart types of the figure that cannot be played (Animatable = False), by name."""
    from app.scanners.axis_renderer_scanner import get_renderer, import_class_from_file

    refused: list[str] = []
    for axis in descriptor.axes or []:
        entry = get_renderer(axis.name)
        try:
            renderer = import_class_from_file(entry) if entry is not None else None
        except (ImportError, OSError, SyntaxError, AttributeError):
            renderer = None
        if renderer is not None and not getattr(renderer, "Animatable", True):
            refused.append(str(getattr(renderer, "Name", axis.name)))
    return list(dict.fromkeys(refused))


def frames(repo: Any, descriptor: Any, settings: AnimationSettings) -> list[Any]:
    """The frames' values, in order: the column's values, or the parameter's from *start* to *stop*."""
    if settings.source == PARAMETER:
        return [float(value) for value in np.linspace(settings.start, settings.stop, settings.steps)]
    return repo.animation_frames(series_tables(repo, descriptor), settings.column)


def frame_values(settings: AnimationSettings, values: Sequence[Any], index: int) -> list[Any]:
    """The values frame *index* draws: its own, every one up to it, or the last *trail* of them."""
    index = max(0, min(int(index), len(values) - 1))
    if settings.source == PARAMETER or settings.mode == EACH:
        return [values[index]]
    if settings.mode == CUMULATIVE:
        return list(values[: index + 1])
    return list(values[max(0, index - settings.trail + 1): index + 1])


def frame_filter(repo: Any, settings: AnimationSettings, values: Sequence[Any], index: int) -> Callable[[str], str]:
    """What each series' query becomes in frame *index* (for render_figure.animation_frame)."""
    shown = frame_values(settings, values, index)
    if settings.source == PARAMETER:
        value = float(shown[0])
        return lambda sql: with_parameter(sql, settings.parameter, value)
    return lambda sql: repo.sql_animation_frame(sql, settings.column, shown)


def with_parameter(sql: str, parameter: str, value: float) -> str:
    """*sql* with its function drawn at *parameter* = *value*; as it is when it draws no function with one."""
    query = parse_function_sql(sql)
    if query is None or parameter not in query.parameters:
        return sql
    parameters = {**query.parameters, parameter: float(value)}
    return replace_function_sql(sql, function_sql(query.name, parameters, query.x, query.y))


def caption(settings: AnimationSettings, values: Sequence[Any], index: int) -> str:
    """The frame's value as written on the figure: "a = 0.5", or the column's value."""
    if not values:
        return ""
    value = values[max(0, min(int(index), len(values) - 1))]
    if settings.source == PARAMETER:
        return f"{settings.parameter} = {float(value):.4g}"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


# ----------------------------------------------------------------------
# Drawing a frame on a figure
# ----------------------------------------------------------------------
CAPTION_GID = "chartlibre-animation-caption"


def axes_limits(figure: Any) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Each axes' x and y limits, in order: what Hold the axes keeps from the whole data."""
    return [(tuple(ax.get_xlim()), tuple(ax.get_ylim())) for ax in figure.axes]


def finish_frame(figure: Any, settings: AnimationSettings, text: str,
                 limits: Sequence[tuple[tuple[float, float], tuple[float, float]]] | None) -> None:
    """After a frame is drawn: the whole data's limits back on its axes (Hold), and its caption."""
    if settings.hold and limits and len(limits) == len(figure.axes):
        for ax, (xlim, ylim) in zip(figure.axes, limits):
            ax.set_xlim(xlim)
            ax.set_ylim(ylim)
    if settings.caption and text:
        figure.text(0.98, 0.98, text, ha="right", va="top", fontsize="large", fontweight="bold",
                    gid=CAPTION_GID, transform=figure.transFigure)


def render_frame(figure: Any, descriptor: Any, repo: Any, settings: AnimationSettings, values: Sequence[Any],
                 index: int, limits: Any = None) -> None:
    """Draw frame *index* of *descriptor* on *figure*, finished (limits held, caption written)."""
    from app.plugin_api.charts.render_figure import animation_frame, render_figure_from_descriptor

    with animation_frame(frame_filter(repo, settings, values, index)):
        render_figure_from_descriptor(figure=figure, descriptor=descriptor, repo=repo)
    finish_frame(figure, settings, caption(settings, values, index), limits)


# ----------------------------------------------------------------------
# Export
# ----------------------------------------------------------------------
def export_gif(path: Any, descriptor: Any, repo: Any, settings: AnimationSettings, *,
               size_in: tuple[float, float], dpi: float,
               progress: Callable[[int, int], bool] | None = None) -> bool:
    """Write every frame of the animation to an animated GIF at *path*; False when *progress* said Stop.

    Drawn off screen at the figure's size and dpi. *progress(done, total)* is told after each frame and
    returns False to stop: nothing is written then.
    """
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from PIL import Image

    values = frames(repo, descriptor, settings)
    if not values:
        raise ValueError("The animation has no frames: the column has no values.")
    figure = Figure(figsize=size_in, dpi=dpi)
    FigureCanvasAgg(figure)
    limits = None
    if settings.hold:
        from app.plugin_api.charts.render_figure import render_figure_from_descriptor

        if settings.source == PARAMETER:
            # The whole family's extent: every frame drawn once, the widest limits kept.
            limits = _family_limits(figure, descriptor, repo, settings, values)
        else:
            render_figure_from_descriptor(figure=figure, descriptor=descriptor, repo=repo)
            figure.canvas.draw()
            limits = axes_limits(figure)
    images = []
    for index in range(len(values)):
        render_frame(figure, descriptor, repo, settings, values, index, limits)
        buffer = io.BytesIO()
        figure.savefig(buffer, format="png", dpi=dpi, facecolor="white")
        buffer.seek(0)
        images.append(Image.open(buffer).convert("RGB"))
        if progress is not None and not progress(index + 1, len(values)):
            return False
    duration = int(round(1000.0 / settings.fps))
    images[0].save(path, save_all=True, append_images=images[1:], duration=duration,
                   loop=0 if settings.loop else 1, optimize=False)
    return True


def _family_limits(figure: Any, descriptor: Any, repo: Any, settings: AnimationSettings,
                   values: Sequence[Any]) -> list[tuple[tuple[float, float], tuple[float, float]]] | None:
    """The limits that hold every frame of a parameter animation: the union of each frame's own."""
    union: list[list[float]] | None = None
    for index in range(len(values)):
        quiet = AnimationSettings(**{**settings.to_options(), "hold": False, "caption": False})
        render_frame(figure, descriptor, repo, quiet, values, index)
        figure.canvas.draw()
        current = axes_limits(figure)
        if union is None:
            union = [[*xlim, *ylim] for xlim, ylim in current]
            continue
        if len(current) != len(union):
            return None
        for box, ((x0, x1), (y0, y1)) in zip(union, current):
            box[0], box[1] = min(box[0], x0), max(box[1], x1)
            box[2], box[3] = min(box[2], y0), max(box[3], y1)
    return [((box[0], box[1]), (box[2], box[3])) for box in union] if union else None
