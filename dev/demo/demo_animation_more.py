"""The second animated charts demo: more figures that move, in two dimensions and in three (I-03).

Everything is made up on the spot (no data file), and each figure carries its animation in its options:

2D
* a travelling wave fading as it goes (each frame alone);
* heat spreading along a rod, a square pulse smoothing out (each frame alone);
* a Lissajous curve drawn as it goes (cumulative);
* two tones beating, the second one's frequency varied (a function's parameter).

3D
* a helix growing along its axis (cumulative, a 3D line);
* thirty particles drifting in a box, the last four steps staying on (trailing, a 3D scatter);
* a ripple spreading over a surface (each frame alone, the height held).

    python -m dev.demo.demo_animation_more
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from app.data.demos import DEMO_DIR, DEMO_PROJECTS, DemoProject
from app.data.repo.function_sql import GridRange, function_sql
from app.data.sqlite_repo import SqliteRepo
from app.data_operations import sympy_store
from app.plugin_api.charts import animation as anim
from app.plugin_api.charts import axis_options
from dev.demo.build_demos import demo_style
from dev.demo.demo_animation import _figure, _function_series, _table_series

#: Declared with the others in app.data.demos (the application lists them); found here by its builder.
MORE_DEMO: DemoProject = next(demo for demo in DEMO_PROJECTS if demo.builder.endswith(":build_more_animation_demo"))

_LINE = {"linewidth": 1.6, "linestyle": "-", "marker": ""}


def _wave() -> pd.DataFrame:
    """A wave moving to the right along x, fading with the distance: 40 frames of 101 points."""
    x = np.linspace(0.0, 10.0, 101)
    rows = []
    for step in range(40):
        y = np.sin(2 * np.pi * (x / 5.0 - step / 20.0)) * np.exp(-0.12 * x)
        rows.append(pd.DataFrame({"step": step, "x": x, "y": np.round(y, 5)}))
    return pd.concat(rows, ignore_index=True)


def _heat() -> pd.DataFrame:
    """A rod held at 0 at its ends, warm in the middle at first: the first odd Fourier modes of the pulse."""
    x = np.linspace(0.0, 1.0, 81)
    rows = []
    for step in range(40):
        time = step * 0.0015
        u = np.zeros_like(x)
        for n in range(1, 60, 2):
            u += 4.0 / (n * np.pi) * np.sin(n * np.pi * x) * np.exp(-((n * np.pi) ** 2) * time)
        rows.append(pd.DataFrame({"step": step, "x": x, "temperature": np.round(u, 5)}))
    return pd.concat(rows, ignore_index=True)


def _lissajous() -> pd.DataFrame:
    angle = np.linspace(0.0, 2 * np.pi, 121)
    return pd.DataFrame({"step": np.arange(121), "x": np.round(np.sin(3 * angle + np.pi / 2), 5),
                         "y": np.round(np.sin(2 * angle), 5)})


def _helix() -> pd.DataFrame:
    t = np.linspace(0.0, 6 * np.pi, 181)
    return pd.DataFrame({"step": np.arange(181), "x": np.round(np.cos(t), 5), "y": np.round(np.sin(t), 5),
                         "z": np.round(t / (2 * np.pi), 5)})


def _particles() -> pd.DataFrame:
    """Thirty particles drifting upward with a random jitter, kept inside the box by reflecting at its walls."""
    rng = np.random.default_rng(5)
    position = rng.uniform(-0.6, 0.6, size=(30, 3))
    velocity = rng.normal(0.0, 0.04, size=(30, 3)) + np.array([0.0, 0.0, 0.03])
    rows = []
    for step in range(40):
        for index in range(30):
            rows.append({"step": step, "particle": index, "x": round(float(position[index, 0]), 4),
                         "y": round(float(position[index, 1]), 4), "z": round(float(position[index, 2]), 4)})
        position += velocity + rng.normal(0.0, 0.015, size=position.shape)
        wall = np.abs(position) > 1.0
        velocity[wall] *= -1.0
        position = np.clip(position, -1.0, 1.0)
    return pd.DataFrame(rows)


def _ripple() -> pd.DataFrame:
    """A circular ripple travelling outwards over a 31 x 31 grid, 24 frames."""
    axis = np.linspace(-6.0, 6.0, 31)
    grid_x, grid_y = np.meshgrid(axis, axis)
    radius = np.hypot(grid_x, grid_y)
    rows = []
    for step in range(24):
        height = np.cos(radius * 1.4 - step * np.pi / 6.0) * np.exp(-radius / 5.0)
        rows.append(pd.DataFrame({"step": step, "x": grid_x.ravel(), "y": grid_y.ravel(),
                                  "z": np.round(height.ravel(), 5)}))
    return pd.concat(rows, ignore_index=True)


def _series_3d(repo: SqliteRepo, axis_id: int, name: str, table: str, style: dict, *, order: str = "") -> None:
    sql = repo.sql_with_row_id(f'SELECT "x" AS "x", "y" AS "y", "z" AS "z" FROM "{table}"{order}')
    repo.create_series_descriptor(axis_id=axis_id, series_index=0, name=name, sql_query=sql,
                                  roles={"x": "x", "y": "y", "z": "z"}, style=style)


def _limits(x: tuple[float, float], y: tuple[float, float], z: tuple[float, float]) -> dict:
    """A 3D axis' whole view range fixed: Hold keeps x and y only, the height would otherwise jump."""
    options: dict = {"projection": "3d", "limits_mode": axis_options.LIMITS_MANUAL}
    for axis, (low, high) in zip(("x", "y", "z"), (x, y, z)):
        options[axis_options.limit_key(axis, "min")] = low
        options[axis_options.limit_key(axis, "max")] = high
    return options


def build_more_animation_demo(directory: Path = DEMO_DIR) -> Path:
    """Write the second animated charts demo into *directory* and return its path."""
    path = Path(directory) / MORE_DEMO.path_name
    path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm", ".undo.db"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)
    repo = SqliteRepo(db_path=path)
    for table, frame in (("wave", _wave()), ("heat", _heat()), ("lissajous", _lissajous()), ("helix", _helix()),
                         ("particles", _particles()), ("ripple", _ripple())):
        repo.import_dataframe(frame, table_name=table, normalize_columns=False)

    # ---- 2D
    axis_id = _figure(repo, "Wave - travelling and fading", "A wave moving to the right", "x", "y",
                      anim.AnimationSettings(column="step", mode=anim.EACH, fps=12.0),
                      axis_options={"y_min": -1.1, "y_max": 1.1})
    _table_series(repo, axis_id, "Wave", "wave", "x", "y", dict(_LINE))

    axis_id = _figure(repo, "Heat - a pulse smoothing out along a rod", "Temperature along the rod",
                      "position", "temperature", anim.AnimationSettings(column="step", mode=anim.EACH, fps=10.0))
    _table_series(repo, axis_id, "Temperature", "heat", "x", "temperature", dict(_LINE))

    axis_id = _figure(repo, "Lissajous - drawn as it goes", "x = sin(3t + pi/2), y = sin 2t", "x", "y",
                      anim.AnimationSettings(column="step", mode=anim.CUMULATIVE, fps=20.0))
    _table_series(repo, axis_id, "Curve", "lissajous", "x", "y", dict(_LINE))

    sympy_store.save(repo, {
        "function_name": "Beats", "source_type": "expression", "symbols": "f", "code_string": "sin(x) + sin(f*x)",
        "from": "0", "to": "40", "points": "801", "values": {"f": 1.0},
        "description": "Two tones: one at 1, the other at f; close together they beat.",
    })
    axis_id = _figure(repo, "Beats - the second tone's frequency varied", "sin x + sin f x", "x", "y",
                      anim.AnimationSettings(source=anim.PARAMETER, parameter="f", start=1.0, stop=1.3, steps=31,
                                             fps=10.0))
    _function_series(repo, axis_id, "Beats", {"f": 1.0}, GridRange(0.0, 40.0, 801))

    # ---- 3D
    axis_id = _figure(repo, "Helix - growing along its axis", "A helix, drawn as it goes", "x", "y",
                      anim.AnimationSettings(column="step", mode=anim.CUMULATIVE, fps=20.0),
                      chart_type="3D Line Plot", axis_options=_limits((-1.2, 1.2), (-1.2, 1.2), (0.0, 3.0)))
    _series_3d(repo, axis_id, "Helix", "helix", dict(_LINE), order=' ORDER BY "step"')

    axis_id = _figure(repo, "Particles - drifting in a box", "Thirty particles, the last four steps kept", "x", "y",
                      anim.AnimationSettings(column="step", mode=anim.TRAILING, trail=4, fps=8.0),
                      chart_type="Scatter Plot (3D)", axis_options=_limits((-1.0, 1.0), (-1.0, 1.0), (-1.0, 1.0)))
    _series_3d(repo, axis_id, "Particles", "particles", {"marker": "o", "alpha": 0.8})

    axis_id = _figure(repo, "Ripple - spreading over a surface", "A ripple travelling outwards", "x", "y",
                      anim.AnimationSettings(column="step", mode=anim.EACH, fps=8.0),
                      chart_type="Surface Plot",
                      axis_options={**_limits((-6.0, 6.0), (-6.0, 6.0), (-1.0, 1.0)), "cmap": "viridis"})
    _series_3d(repo, axis_id, "Surface", "ripple", {})

    repo.close()
    Path(f"{path}.undo.db").unlink(missing_ok=True)
    return path


if __name__ == "__main__":
    print(build_more_animation_demo())
