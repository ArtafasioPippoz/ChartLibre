"""Thinning a large series out: the curve's order is kept, a rare colour never goes."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.data.sqlite_repo import SqliteRepo, colour_group_plan


def _table(repo: SqliteRepo, n: int = 5000) -> None:
    x = np.arange(n, dtype=float)
    colour = np.where(x % 997 == 0, "#d62728", None)  # a handful of outliers, scattered
    repo.import_dataframe(pd.DataFrame({"x": x, "y": np.sin(x / 50), "c": colour}),
                          table_name="big", normalize_columns=False)


def _coloured(repo: SqliteRepo, name: str, colour: np.ndarray, n: int) -> None:
    x = np.arange(n, dtype=float)
    repo.import_dataframe(pd.DataFrame({"x": x, "y": np.sin(x / 50), "c": colour}),
                          table_name=name, normalize_columns=False)


def test_a_curve_is_thinned_in_its_own_order(repo: SqliteRepo) -> None:
    _table(repo)
    frame = repo.downsampled_series_frame("SELECT x, y FROM big ORDER BY x", threshold=500)
    x = np.asarray(frame["x"], dtype=float)
    assert 400 <= len(x) <= 600
    assert np.all(np.diff(x) > 0) and x[0] == 0  # every tenth row, in x order


def test_coloured_rows_survive_the_thinning(repo: SqliteRepo) -> None:
    _table(repo)
    frame = repo.downsampled_series_frame('SELECT x, y, c AS "color" FROM big ORDER BY x', threshold=500)
    colours = [value for value in frame["color"] if isinstance(value, str) and value]
    assert len(colours) == 6  # every one of the coloured rows: x = 0, 997, ..., 4985


def test_a_rare_colour_is_kept_whole_among_a_common_one(repo: SqliteRepo) -> None:
    n = 20_000
    colour = np.where(np.arange(n) % 1000 == 7, "red", "blue")  # 20 red, the rest blue
    _coloured(repo, "rare", colour, n)
    frame = repo.downsampled_series_frame('SELECT x, y, c AS "color" FROM rare ORDER BY x', threshold=1000)
    assert list(frame["color"]).count("red") == 20  # every outlier, not one in twenty-one
    assert 800 <= len(frame) <= 1100  # the blue rows thinned to the budget the outliers leave


def test_groups_of_similar_size_are_thinned_in_proportion(repo: SqliteRepo) -> None:
    n = 20_000
    colour = np.where(np.arange(n) < n // 2, "first", "second")  # two blocks, neither rare
    _coloured(repo, "halves", colour, n)
    frame = repo.downsampled_series_frame('SELECT x, y, c AS "color" FROM halves ORDER BY x', threshold=1000)
    colours = list(frame["color"])
    assert 900 <= len(frame) <= 1100
    assert 400 <= colours.count("first") <= 600
    assert 400 <= colours.count("second") <= 600


def test_a_few_uncoloured_rows_among_coloured_ones_are_kept(repo: SqliteRepo) -> None:
    n = 20_000
    colour = np.where(np.isin(np.arange(n), [3, 4000, 8000, 12000, 16000]), None, "blue")
    _coloured(repo, "uncoloured", colour, n)
    frame = repo.downsampled_series_frame('SELECT x, y, c AS "color" FROM uncoloured ORDER BY x', threshold=1000)
    assert sum(1 for value in frame["color"] if not isinstance(value, str)) == 5  # all five, uncoloured


def test_a_colour_map_is_thinned_like_any_column(repo: SqliteRepo) -> None:
    n = 20_000
    x = np.arange(n, dtype=float)
    repo.import_dataframe(pd.DataFrame({"x": x, "y": x / 7, "c": x}),
                          table_name="colour_map", normalize_columns=False)
    frame = repo.downsampled_series_frame('SELECT x, y, c AS "color" FROM colour_map ORDER BY x', threshold=1000)
    assert 900 <= len(frame) <= 1100  # 20 000 distinct colours: a map, so the plain stride


def test_a_rare_integer_flag_is_kept(repo: SqliteRepo) -> None:
    n = 20_000
    flag = (np.arange(n) % 997 == 0).astype(int)  # 0 and 1; the 1s are rare
    _coloured(repo, "flags", flag, n)
    frame = repo.downsampled_series_frame('SELECT x, y, c AS "color" FROM flags ORDER BY x', threshold=1000)
    assert list(frame["color"]).count(1) == len(range(0, n, 997))  # all 21 flagged rows


def test_a_rare_colour_with_a_quote_in_its_name_is_kept(repo: SqliteRepo) -> None:
    n = 20_000
    colour = np.where(np.arange(n) == 5, "O'Brien", "blue")
    _coloured(repo, "quoted", colour, n)
    frame = repo.downsampled_series_frame('SELECT x, y, c AS "color" FROM quoted ORDER BY x', threshold=1000)
    assert list(frame["color"]).count("O'Brien") == 1


def test_the_plan_keeps_a_rare_group_and_sizes_the_stride_to_the_rest() -> None:
    stride, rare = colour_group_plan(20_000, 1_000, [("red", 20)])
    assert rare == [("red", 20)]
    assert stride == 21  # the 19 980 other rows over the 980 that the 20 red ones leave
