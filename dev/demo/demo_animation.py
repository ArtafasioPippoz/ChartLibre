"""The animated charts demo: figures played along a column, and functions played along a parameter (I-03).

Each figure carries its animation in its options, so opening it and pressing Play on Chart properties >
Animation is all there is to do:

* CO2 at Mauna Loa, one year at a time - the seasonal cycle climbing (each frame alone, the axes held);
* the global temperature record as it grew, decade by decade (cumulative);
* made-up countries, income against life expectancy over thirty years - Gapminder's bubbles (trailing: the
  last three years stay on);
* a damped oscillation with its decay varied, and a Gaussian with its width varied (a function's parameter).

    python -m dev.demo.demo_animation
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
from dev.demo.build_demos import demo_style

SAMPLE_DATA = Path(__file__).resolve().parent / "sample data"

#: Declared with the others in app.data.demos (the application lists them); found here by its builder.
ANIMATION_DEMO: DemoProject = next(demo for demo in DEMO_PROJECTS if demo.builder.endswith(":build_animation_demo"))

_LINE = {"linewidth": 1.6, "linestyle": "-", "marker": ""}


def _co2() -> pd.DataFrame:
    """The Keeling curve with its year and month apart: the month is the x, the year the frame."""
    frame = pd.read_csv(SAMPLE_DATA / "co2_mauna_loa.csv")
    dates = pd.to_datetime(frame["date"])
    frame["year"] = dates.dt.year
    frame["month"] = dates.dt.month
    counts = frame.groupby("year")["month"].transform("count")
    return frame[counts == 12].reset_index(drop=True)  # whole years only: every frame a full cycle


def _temperature() -> pd.DataFrame:
    frame = pd.read_csv(SAMPLE_DATA / "global_temperature.csv")
    frame["decade"] = (frame["year"] // 10) * 10
    return frame


def _countries() -> pd.DataFrame:
    """Twelve made-up countries over thirty years: income growing at its own rate, life expectancy following."""
    rng = np.random.default_rng(11)
    rows = []
    for index in range(12):
        income = rng.uniform(800.0, 12000.0)
        growth = rng.uniform(0.01, 0.07)
        for year in range(1990, 2020):
            life = 38.0 + 9.5 * np.log10(income) + rng.normal(0.0, 0.5)
            rows.append({"country": f"Country {chr(65 + index)}", "year": year, "income": round(income, 1),
                         "life_expectancy": round(float(life), 2)})
            income *= 1.0 + growth + rng.normal(0.0, 0.015)
    return pd.DataFrame(rows)


def _figure(repo: SqliteRepo, name: str, title: str, x_label: str, y_label: str, settings: anim.AnimationSettings,
            *, chart_type: str = "Scatter Plot", axis_options: dict | None = None) -> int:
    figure_id = int(repo.create_figure_descriptor(
        name=name, nrows=1, ncols=1,
        options={"mpl_style": demo_style(), "layout_mode": "constrained", anim.OPTION_KEY: settings.to_options()}))
    return int(repo.create_axis_descriptor(
        figure_id=figure_id, axis_index=0, chart_type=chart_type, title=title, x_label=x_label, y_label=y_label,
        options={"title": title, **(axis_options or {})}))


def _table_series(repo: SqliteRepo, axis_id: int, name: str, table: str, x: str, y: str, style: dict) -> None:
    sql = repo.sql_with_row_id(f'SELECT "{x}" AS "x", "{y}" AS "y" FROM "{table}"')
    repo.create_series_descriptor(axis_id=axis_id, series_index=0, name=name, sql_query=sql,
                                  roles={"x": "x", "y": "y"}, style=style)


def _function_series(repo: SqliteRepo, axis_id: int, name: str, values: dict[str, float],
                     grid: GridRange) -> None:
    repo.create_series_descriptor(axis_id=axis_id, series_index=0, name=name, roles={"x": "x", "y": "y"},
                                  sql_query=function_sql(name, values, grid), style=dict(_LINE))


def build_animation_demo(directory: Path = DEMO_DIR) -> Path:
    """Write the animated charts demo into *directory* and return its path."""
    path = Path(directory) / ANIMATION_DEMO.path_name
    path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm", ".undo.db"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)
    repo = SqliteRepo(db_path=path)
    repo.import_dataframe(_co2(), table_name="co2_mauna_loa", normalize_columns=False)
    repo.import_dataframe(_temperature(), table_name="global_temperature", normalize_columns=False)
    repo.import_dataframe(_countries(), table_name="countries", normalize_columns=False)

    axis_id = _figure(repo, "CO2 at Mauna Loa - the seasonal cycle, year by year", "CO2, one year at a time",
                      "month", "CO2 (ppm)", anim.AnimationSettings(column="year", mode=anim.EACH, fps=8.0))
    _table_series(repo, axis_id, "CO2", "co2_mauna_loa", "month", "co2_ppm",
                  {"linewidth": 1.6, "linestyle": "-", "marker": "o", "markersize": 4})

    axis_id = _figure(repo, "Global temperature - the record as it grew", "Temperature anomaly, decade by decade",
                      "year", "anomaly (°C)", anim.AnimationSettings(column="decade", mode=anim.CUMULATIVE, fps=3.0))
    _table_series(repo, axis_id, "Anomaly", "global_temperature", "year", "anomaly_c", dict(_LINE))

    axis_id = _figure(repo, "Countries - income and life expectancy over thirty years",
                      "Made-up countries, 1990-2019", "income per person", "life expectancy (years)",
                      anim.AnimationSettings(column="year", mode=anim.TRAILING, trail=3, fps=6.0),
                      axis_options={"x_scale": "log"})
    _table_series(repo, axis_id, "Countries", "countries", "income", "life_expectancy",
                  {"linestyle": "", "marker": "o", "markersize": 7, "alpha": 0.7})

    for name, code, values, description in (
        ("Damped", "a*exp(-b*x)*cos(w*x)", {"a": 1.0, "b": 0.3, "w": 4.0},
         "A damped oscillation: amplitude a, decay b, angular frequency w."),
        ("Gaussian", "A*exp(-(x - mu)**2/(2*s**2))", {"A": 1.0, "mu": 0.0, "s": 1.0},
         "A bell curve: height A, centre mu, width s."),
    ):
        sympy_store.save(repo, {
            "function_name": name, "source_type": "expression", "symbols": ", ".join(values), "code_string": code,
            "from": "-5" if name == "Gaussian" else "0", "to": "5" if name == "Gaussian" else "10",
            "points": "201", "description": description, "values": values,
        })
    axis_id = _figure(repo, "Damped oscillation - the decay b varied", "a exp(-bx) cos(wx)",
                      "x", "y", anim.AnimationSettings(source=anim.PARAMETER, parameter="b", start=0.05, stop=1.2,
                                                       steps=30, fps=10.0))
    _function_series(repo, axis_id, "Damped", {"a": 1.0, "b": 0.3, "w": 4.0}, GridRange(0.0, 10.0, 201))
    axis_id = _figure(repo, "Gaussian - the width s varied", "A exp(-(x - mu)² / 2s²)",
                      "x", "y", anim.AnimationSettings(source=anim.PARAMETER, parameter="s", start=0.3, stop=2.5,
                                                       steps=30, fps=10.0))
    _function_series(repo, axis_id, "Gaussian", {"A": 1.0, "mu": 0.0, "s": 1.0}, GridRange(-5.0, 5.0, 201))

    repo.close()
    Path(f"{path}.undo.db").unlink(missing_ok=True)
    return path


if __name__ == "__main__":
    print(build_animation_demo())
