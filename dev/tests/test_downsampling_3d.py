"""A big 3D surface is drawn thinned to the cells the threshold allows: it stays a complete grid, and a grid with holes is still refused."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from app.data.sqlite_repo import SqliteRepo
from app.plugin_api.charts.grids import grid_thinning_mask, pivot_to_grid
from app.plugin_api.charts.render_figure import render_figure_from_descriptor
from dev.tests._figure_factory import create_renderer_showcase_db

#: The default threshold (1 000) times the 3D factor (100): the cell budget of a surface.
BUDGET = 100_000


def _grid(side: int) -> pd.DataFrame:
    axis = np.linspace(-3.0, 3.0, side)
    gx, gy = np.meshgrid(axis, axis)
    return pd.DataFrame({"x": gx.ravel(), "y": gy.ravel(), "z": np.sin(np.hypot(gx, gy)).ravel()})


def _thinned(frame: pd.DataFrame, max_cells: int) -> pd.DataFrame:
    mask = grid_thinning_mask(frame, max_cells=max_cells)
    assert mask is not None
    return frame.loc[mask]


def test_a_big_grid_is_thinned_under_the_cell_budget_and_stays_a_grid() -> None:
    grid = pivot_to_grid(_thinned(_grid(600), max_cells=BUDGET))
    assert grid is not None
    assert grid[0].shape == (300, 300)  # every second line of 600: 90 000 cells, step 3 would be 40 000 cells too few


def test_a_grid_already_under_the_budget_is_left_alone() -> None:
    assert grid_thinning_mask(_grid(150), max_cells=BUDGET) is None


def test_a_grid_with_a_hole_is_not_thinned_so_it_is_still_refused() -> None:
    frame = _grid(600).drop(index=5)  # one (x, y) pair missing
    assert grid_thinning_mask(frame, max_cells=BUDGET) is None
    assert pivot_to_grid(frame) is None


def test_the_step_is_the_smallest_that_meets_the_budget() -> None:
    # 1000 x 1000: step 3 gives 334 x 334 = 111 556 cells, over the budget; step 4 gives 250 x 250.
    grid = pivot_to_grid(_thinned(_grid(1000), max_cells=BUDGET))
    assert grid is not None
    assert grid[0].shape == (250, 250)


def test_a_surface_of_a_big_grid_is_drawn_thinned(tmp_path: Path) -> None:
    db_path = tmp_path / "surface_big.dhub"
    figure_ids = create_renderer_showcase_db(db_path, n_points=10)
    side = 600
    axis = np.linspace(-3.0, 3.0, side)
    gx, gy = np.meshgrid(axis, axis)
    gz = np.sin(np.hypot(gx, gy))
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("DELETE FROM src_grid")
        conn.executemany(
            "INSERT INTO src_grid (x, y, z) VALUES (?, ?, ?)",
            zip(gx.ravel().tolist(), gy.ravel().tolist(), gz.ravel().tolist()),
        )

    repo = SqliteRepo(db_path=db_path)
    descriptor = repo.load_figure_descriptor(figure_id=figure_ids["Surface Plot"])
    assert descriptor is not None
    fig = Figure(figsize=(7.0, 4.5))
    render_figure_from_descriptor(figure=fig, descriptor=descriptor, repo=repo)

    surface = fig.axes[0].collections[0]
    # 600 x 600 is 360 000 cells: over the budget, so every second line is drawn, 300 x 300.
    assert len(surface.get_facecolor()) == (300 - 1) ** 2
