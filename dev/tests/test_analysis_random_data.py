"""Random data: the registry and the five layouts (app/analysis/random_data.py)."""
from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from app.analysis import random_data as rd
from app.analysis.random_data import Axis, ColumnSpec


def _one(key: str, n: int = 100_000, **parameters: float) -> np.ndarray:
    result = rd.generate(rd.LAYOUT_X, [ColumnSpec(key, parameters)], n=n, seed=1)
    return result.table["X"].to_numpy()


def test_the_same_seed_gives_the_same_table_and_another_seed_another() -> None:
    spec = [ColumnSpec("normal"), ColumnSpec("exponential")]
    a = rd.generate(rd.LAYOUT_XY, spec, n=50, seed=7).table
    b = rd.generate(rd.LAYOUT_XY, spec, n=50, seed=7).table
    c = rd.generate(rd.LAYOUT_XY, spec, n=50, seed=8).table
    assert a.equals(b)
    assert not a.equals(c)


def test_without_a_seed_one_is_drawn_and_reported_so_the_run_can_be_repeated() -> None:
    first = rd.generate(rd.LAYOUT_X, [ColumnSpec()], n=20)
    again = rd.generate(rd.LAYOUT_X, [ColumnSpec()], n=20, seed=first.seed)
    assert first.table.equals(again.table)


@pytest.mark.parametrize("key", list(rd.DISTRIBUTIONS))
def test_every_distribution_draws_a_sample_that_follows_its_own_theory(key: str) -> None:
    values = _one(key)
    assert values.shape == (100_000,) and np.all(np.isfinite(values))
    frozen = rd.theory(key)
    if rd.DISTRIBUTIONS[key].discrete:
        assert np.all(values == np.round(values))
        support = np.unique(values)
        assert np.all(frozen.pmf(support) > 0)
    else:
        assert stats.kstest(values, frozen.cdf).pvalue > 1e-4


@pytest.mark.parametrize("key", ["normal", "uniform", "exponential", "gamma", "beta", "poisson", "binomial", "weibull"])
def test_the_sample_moments_match_the_theoretical_ones(key: str) -> None:
    values = _one(key)
    moments = rd.theoretical_moments(key)
    sd = moments["variance"] ** 0.5
    assert abs(values.mean() - moments["mean"]) < 6 * sd / np.sqrt(values.size)
    assert values.var(ddof=1) == pytest.approx(moments["variance"], rel=0.05)


def test_a_distribution_without_a_mean_says_so_rather_than_failing() -> None:
    moments = rd.theoretical_moments("cauchy")
    assert all(np.isnan(v) for v in moments.values())


def test_parameters_are_the_ones_given_with_defaults_for_the_rest() -> None:
    values = _one("normal", mean=50.0, sd=0.001, n=1000)
    assert abs(values.mean() - 50.0) < 0.001
    assert rd.clean_parameters("normal", {"mean": 3}) == (3.0, 1.0)
    assert rd.default_parameters("gamma") == {"shape": 2.0, "scale": 1.0}


@pytest.mark.parametrize(
    ("key", "parameters", "words"),
    [
        ("normal", {"sd": 0}, "above"),
        ("normal", {"sd": -1}, "above"),
        ("normal", {"mean": float("nan")}, "number"),
        ("binomial", {"p": 1.5}, "at most"),
        ("binomial", {"n": 2.5}, "whole number"),
        ("uniform", {"low": 3, "high": 1}, "below its high"),
        ("triangular", {"left": 0, "mode": 5, "right": 1}, "left <= mode <= right"),
        ("poisson", {"lambda": 3}, "no parameter"),
    ],
)
def test_a_bad_parameter_is_refused_in_words(key: str, parameters: dict[str, float], words: str) -> None:
    with pytest.raises(ValueError, match=words):
        rd.generate(rd.LAYOUT_X, [ColumnSpec(key, parameters)], n=10, seed=1)


def test_an_unknown_distribution_or_layout_names_the_ones_there_are() -> None:
    with pytest.raises(ValueError, match="normal"):
        rd.distribution("nope")
    with pytest.raises(ValueError, match="XYZ"):
        rd.generate("ABC", [ColumnSpec()], n=10)


def test_columns_take_their_own_distribution_and_name() -> None:
    result = rd.generate(
        rd.LAYOUT_XYZ,
        [ColumnSpec("normal", name="height"), ColumnSpec("poisson", name="count"), ColumnSpec("uniform", {"low": 5, "high": 6})],
        n=500, seed=3)
    assert list(result.table.columns) == ["height", "count", "Z"]
    assert result.table["Z"].between(5, 6).all()
    assert (result.table["count"] % 1 == 0).all()


def test_the_layouts_need_the_right_number_of_columns_with_different_names() -> None:
    with pytest.raises(ValueError, match="2 random column"):
        rd.generate(rd.LAYOUT_XY, [ColumnSpec()], n=10)
    with pytest.raises(ValueError, match="different names"):
        rd.generate(rd.LAYOUT_XY, [ColumnSpec(name="a"), ColumnSpec(name="a")], n=10)


def test_columns_are_independent_by_default() -> None:
    table = rd.generate(rd.LAYOUT_XYZ, [ColumnSpec()] * 3, n=20_000, seed=2).table
    corr = np.corrcoef(table.to_numpy().T)
    assert np.abs(corr[~np.eye(3, dtype=bool)]).max() < 0.05


def test_normal_columns_come_out_with_the_correlation_asked() -> None:
    table = rd.generate(rd.LAYOUT_XY, [ColumnSpec(), ColumnSpec()], n=50_000, seed=4, correlation=0.7).table
    assert np.corrcoef(table["X"], table["Y"])[0, 1] == pytest.approx(0.7, abs=0.02)


def test_different_distributions_can_be_correlated_and_keep_their_own_shape() -> None:
    table = rd.generate(
        rd.LAYOUT_XY, [ColumnSpec("exponential"), ColumnSpec("uniform", {"low": 0, "high": 10})],
        n=50_000, seed=5, correlation=0.8).table
    assert stats.spearmanr(table["X"], table["Y"])[0] > 0.7
    assert stats.kstest(table["X"], stats.expon.cdf).pvalue > 1e-4
    assert stats.kstest(table["Y"], stats.uniform(0, 10).cdf).pvalue > 1e-4


def test_a_full_matrix_is_honoured_and_an_impossible_one_refused() -> None:
    matrix = [[1, 0.5, -0.3], [0.5, 1, 0.2], [-0.3, 0.2, 1]]
    table = rd.generate(rd.LAYOUT_XYZ, [ColumnSpec()] * 3, n=60_000, seed=6, correlation=matrix).table
    assert np.corrcoef(table.to_numpy().T) == pytest.approx(np.array(matrix), abs=0.02)
    with pytest.raises(ValueError, match="positive definite"):
        rd.generate(rd.LAYOUT_XYZ, [ColumnSpec()] * 3, n=10, correlation=[[1, 0.9, -0.9], [0.9, 1, 0.9], [-0.9, 0.9, 1]])
    with pytest.raises(ValueError, match="symmetric"):
        rd.generate(rd.LAYOUT_XY, [ColumnSpec()] * 2, n=10, correlation=[[1, 0.2], [0.5, 1]])
    with pytest.raises(ValueError, match="between -1 and 1"):
        rd.generate(rd.LAYOUT_XY, [ColumnSpec()] * 2, n=10, correlation=1.0)


def test_a_line_has_an_even_x_and_a_random_y_on_a_trend() -> None:
    result = rd.generate(
        rd.LAYOUT_LINE, [ColumnSpec("normal", {"sd": 0.5})],
        x_axis=Axis(0, 10, 20_001), trend=(2.0, 3.0), seed=1)
    x, y = result.table["X"].to_numpy(), result.table["Y"].to_numpy()
    assert x[0] == 0 and x[-1] == 10 and np.allclose(np.diff(x), 10 / 20_000)
    slope, intercept = np.polyfit(x, y, 1)
    assert (intercept, slope) == pytest.approx((2.0, 3.0), abs=0.02)
    assert (y - (2 + 3 * x)).std() == pytest.approx(0.5, rel=0.03)


def test_a_grid_pairs_every_x_with_every_y_and_adds_noise_to_a_function() -> None:
    result = rd.generate(
        rd.LAYOUT_GRID, [ColumnSpec("normal", {"sd": 0.1}, name="height")],
        x_axis=Axis(0, 1, 30), y_axis=Axis(-1, 1, 20, name="depth"),
        function=lambda x, y: x + y, seed=1)
    table = result.table
    assert list(table.columns) == ["X", "depth", "height"] and len(table) == 600
    assert table[["X", "depth"]].drop_duplicates().shape[0] == 600
    assert (table["height"] - table["X"] - table["depth"]).std() == pytest.approx(0.1, rel=0.1)


def test_a_grid_without_a_function_is_plain_noise() -> None:
    table = rd.generate(rd.LAYOUT_GRID, [ColumnSpec("uniform")], x_axis=Axis(0, 1, 10), y_axis=Axis(0, 1, 10), seed=1).table
    assert table["Z"].between(0, 1).all()


def test_a_function_returning_the_wrong_size_is_refused() -> None:
    with pytest.raises(ValueError, match="value"):
        rd.generate(rd.LAYOUT_GRID, [ColumnSpec()], x_axis=Axis(0, 1, 5), y_axis=Axis(0, 1, 5),
                    function=lambda x, y: np.zeros(3))


def test_too_many_rows_or_too_few_points_are_refused_in_words() -> None:
    with pytest.raises(ValueError, match="at most"):
        rd.generate(rd.LAYOUT_X, [ColumnSpec()], n=rd.MAX_ROWS + 1)
    with pytest.raises(ValueError, match="at most"):
        rd.generate(rd.LAYOUT_GRID, [ColumnSpec()], x_axis=Axis(0, 1, 2000), y_axis=Axis(0, 1, 2000))
    with pytest.raises(ValueError, match="at least 1 row"):
        rd.generate(rd.LAYOUT_X, [ColumnSpec()], n=0)
    with pytest.raises(ValueError, match="at least 2"):
        rd.generate(rd.LAYOUT_LINE, [ColumnSpec()], x_axis=Axis(0, 1, 1))
    with pytest.raises(ValueError, match="empty"):
        rd.generate(rd.LAYOUT_LINE, [ColumnSpec()], x_axis=Axis(1, 1, 10))
