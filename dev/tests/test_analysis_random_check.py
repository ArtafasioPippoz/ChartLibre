"""The checks of one random column (app/analysis/random_check.py)."""
from __future__ import annotations

import numpy as np
import pytest

from app.analysis import random_check as rc
from app.analysis import random_data as rd
from app.analysis.random_data import ColumnSpec


def _sample(key: str, n: int = 2000, seed: int = 1, **parameters: float) -> np.ndarray:
    return rd.generate(rd.LAYOUT_X, [ColumnSpec(key, parameters)], n=n, seed=seed).table["X"].to_numpy()


def _row(rows: list[dict], start: str) -> dict:
    return next(r for r in rows if r["test"].startswith(start))


def test_the_anderson_darling_pvalue_matches_the_published_critical_values() -> None:
    for a2, p in ((1.933, 0.10), (2.492, 0.05), (3.857, 0.01)):
        assert rc.anderson_darling_pvalue(a2) == pytest.approx(p, abs=0.004)
    assert rc.anderson_darling_pvalue(0.0) == 1.0


def test_the_anderson_darling_test_rejects_a_true_hypothesis_about_one_time_in_twenty() -> None:
    rng = np.random.default_rng(0)
    pvalues = np.array([rc.anderson_darling_pvalue(rc.anderson_darling(rng.random(200))) for _ in range(2000)])
    assert 0.03 < (pvalues < 0.05).mean() < 0.07


@pytest.mark.parametrize("key", list(rd.DISTRIBUTIONS))
def test_a_sample_from_the_distribution_is_not_rejected(key: str) -> None:
    check = rc.check_column(_sample(key), key, name="X")
    run, failed = check.tally()
    assert run >= 8 and failed <= 2  # five per cent of the tests may reject a good sample, not many more
    assert all(r["pvalue"] > 1e-4 for r in [*check.fit, *check.uniformity] if np.isfinite(r["pvalue"]))


def test_a_sample_from_another_distribution_fails_the_fit() -> None:
    check = rc.check_column(_sample("uniform", 1000), "normal", {"mean": 0.5, "sd": 0.29})
    assert _row(check.fit, "Kolmogorov")["pvalue"] < 1e-3
    assert _row(check.fit, "Anderson")["pvalue"] < 1e-3
    assert _row(check.uniformity, "Uniformity")["pvalue"] < 1e-3


def test_a_discrete_sample_against_the_wrong_probability_fails_the_chi_square() -> None:
    check = rc.check_column(_sample("binomial", 2000, p=0.5), "binomial", {"p": 0.6})
    assert _row(check.fit, "Chi-square")["pvalue"] < 1e-3
    assert "KS" not in str([r["test"] for r in check.fit]) and len(check.fit) == 1


def test_a_discrete_column_with_hardly_any_values_says_so_in_a_note() -> None:
    check = rc.check_column(np.array([0.0, 1, 1, 0, 1, 0, 0, 1, 1, 0]), "binomial", {"n": 1, "p": 0.5})
    assert "under 5" in check.fit[0]["note"] or np.isfinite(check.fit[0]["pvalue"])


def test_the_moments_are_set_beside_the_theory() -> None:
    check = rc.check_column(_sample("normal", 5000, mean=10, sd=2), "normal", {"mean": 10, "sd": 2})
    table = check.moments.set_index("Statistic")
    assert table.loc["Mean", "Theoretical"] == 10 and table.loc["Standard deviation", "Theoretical"] == 2
    assert abs(table.loc["Mean", "Z"]) < 4 and abs(table.loc["Standard deviation", "Z"]) < 4
    assert table.loc["Skewness", "Theoretical"] == pytest.approx(0.0)
    assert np.isnan(table.loc["Skewness", "Z"])


def test_a_wrong_mean_gives_a_large_z() -> None:
    check = rc.check_column(_sample("normal", 5000), "normal", {"mean": 0.5})
    assert abs(check.moments.set_index("Statistic").loc["Mean", "Z"]) > 10


def test_a_distribution_without_moments_is_marked_undefined_and_checked_all_the_same() -> None:
    check = rc.check_column(_sample("cauchy"), "cauchy")
    assert (check.moments["Note"] == "Undefined for this distribution").all()
    assert check.moments["Z"].isna().all()
    assert _row(check.fit, "Kolmogorov")["pvalue"] > 1e-3


def test_a_normal_sample_passes_the_normality_tests_and_a_uniform_one_fails_them() -> None:
    assert min(r["pvalue"] for r in rc.check_column(_sample("normal", 500), "normal").normality
               if np.isfinite(r["pvalue"])) > 1e-3
    uniform = rc.check_column(_sample("uniform", 2000), "uniform")
    assert _row(uniform.normality, "Shapiro")["pvalue"] < 1e-6
    assert uniform.tally()[1] <= 2  # ... which is not a failure for a column meant to be uniform


def test_a_sorted_sample_fails_the_order_tests_and_its_fit_is_untouched() -> None:
    values = np.sort(_sample("normal", 500))
    check = rc.check_column(values, "normal")
    assert _row(check.order, "Wald")["pvalue"] < 1e-6
    assert _row(check.order, "Neighbour")["pvalue"] < 1e-6
    assert _row(check.fit, "Kolmogorov")["pvalue"] > 0.01  # the values are fine; only their order is not
    assert check.autocorrelation["Outside"].sum() >= 15


def test_a_sample_whose_neighbours_depend_on_each_other_fails_the_pairs_test_the_runs_test_misses() -> None:
    # the next value is large when this one is far from the median, whatever its sign: no correlation, no change
    # in the number of runs, but the pairs fill the grid unevenly.
    rng = np.random.default_rng(5)
    u = np.empty(6000)
    u[0] = 0.3
    for i in range(1, u.size):
        u[i] = (4.0 * (u[i - 1] - 0.5) ** 2 + 0.2 * rng.random()) % 1.0
    check = rc.check_column(u, "uniform")
    assert _row(check.order, "Neighbour")["pvalue"] < 1e-6


def test_the_autocorrelation_has_its_band_and_a_correlated_sample_leaves_it() -> None:
    rng = np.random.default_rng(2)
    noise = rng.normal(size=3000)
    ar = np.empty_like(noise)
    ar[0] = noise[0]
    for i in range(1, noise.size):
        ar[i] = 0.7 * ar[i - 1] + noise[i]
    acf = rc.autocorrelation(ar, 5)
    assert list(acf["Lag"]) == [1, 2, 3, 4, 5]
    assert acf["ACF"].iloc[0] == pytest.approx(0.7, abs=0.05) and acf["Outside"].iloc[0]
    assert acf["Upper"].iloc[0] == pytest.approx(1.96 / np.sqrt(3000))
    assert _row(rc.check_column(ar, "normal").order, "Ljung")["pvalue"] < 1e-6


def test_the_probability_integral_histogram_is_flat_for_a_good_sample_and_lists_its_bins() -> None:
    check = rc.check_column(_sample("exponential", 5000), "exponential")
    assert list(check.pit.columns) == ["Bin", "Observed", "Expected"] and len(check.pit) == 10
    assert check.pit["Observed"].sum() == 5000 and (check.pit["Expected"] == 500).all()


def test_the_discrete_probability_integral_is_made_uniform_and_does_not_change_between_runs() -> None:
    values = _sample("poisson", 4000, mu=4)
    u = rc.probability_integral(values, "poisson", {"mu": 4})
    assert np.array_equal(u, rc.probability_integral(values, "poisson", {"mu": 4}))
    assert u.min() > 0 and u.max() < 1 and abs(u.mean() - 0.5) < 0.02


def test_tally_counts_the_tests_run_and_the_ones_that_reject_and_ignores_notes() -> None:
    rows = [{"test": "a", "pvalue": 0.01}, {"test": "b", "pvalue": 0.5}, {"test": "c", "pvalue": float("nan")}]
    assert rc.tally(rows) == (2, 1)
    assert rc.tally(rows, alpha=0.001) == (2, 0)


def test_normality_counts_in_the_tally_only_for_a_column_meant_to_be_normal() -> None:
    values = _sample("exponential", 2000)
    as_normal = rc.check_column(values, "normal", {"mean": 1, "sd": 1})
    as_exponential = rc.check_column(values, "exponential")
    assert as_normal.tally()[0] > as_exponential.tally()[0]
    assert as_exponential.tally()[1] <= 2 < as_normal.tally()[1]


def test_too_short_a_column_is_refused_in_words_and_missing_values_are_dropped() -> None:
    with pytest.raises(ValueError, match="at least 8"):
        rc.check_column([1.0, 2.0, 3.0], "normal")
    values = _sample("normal", 200).copy()
    values[::10] = np.nan
    assert rc.check_column(values, "normal").n == 180


# ----------------------------------------------------------------------
# Between columns, a line, a grid, the verdict
# ----------------------------------------------------------------------
from app.analysis.answers import NO, YES  # noqa: E402
from app.analysis.random_data import Axis  # noqa: E402


def _table(layout: str, columns: list[ColumnSpec], seed: int = 1, **options):
    generated = rd.generate(layout, columns, seed=seed, **options)
    return generated, rc.check_generated(generated, **{k: v for k, v in options.items()
                                                       if k in ("correlation", "trend", "function")})


def test_independent_columns_are_not_rejected_by_the_independence_tests() -> None:
    _, check = _table(rd.LAYOUT_XYZ, [ColumnSpec(), ColumnSpec("exponential"), ColumnSpec("uniform")], n=1500)
    assert len(check.pairs) == 3
    for pair in check.pairs:
        assert pair.requested is None and len(pair.independence) == 5 and not pair.against_requested
        assert all(r["pvalue"] > 1e-3 for r in pair.independence)


def test_correlated_columns_reject_independence_and_match_the_correlation_asked() -> None:
    _, check = _table(rd.LAYOUT_XY, [ColumnSpec(), ColumnSpec("exponential")], n=3000, correlation=0.6)
    pair = check.pairs[0]
    assert pair.requested == 0.6
    assert _row(pair.independence, "Pearson")["pvalue"] < 1e-10
    assert _row(pair.independence, "Distance")["pvalue"] <= 0.01
    assert _row(pair.against_requested, "Spearman")["pvalue"] > 0.001
    assert pair.tally()[0] == 1  # only the test against the one asked counts


def test_normal_columns_are_also_checked_by_pearson_against_the_correlation_asked() -> None:
    _, check = _table(rd.LAYOUT_XY, [ColumnSpec(), ColumnSpec()], n=4000, correlation=0.5)
    assert _row(check.pairs[0].against_requested, "Pearson")["pvalue"] > 0.001


def test_a_sample_without_the_correlation_asked_fails_against_it() -> None:
    generated = rd.generate(rd.LAYOUT_XY, [ColumnSpec(), ColumnSpec()], n=3000, seed=1, correlation=0.0)
    check = rc.check_pair(generated.table["X"], generated.table["Y"], "X", "Y",
                          distributions=("normal", "normal"), requested=0.5)
    assert all(r["pvalue"] < 1e-6 for r in check.against_requested)


def test_the_distance_correlation_sees_a_dependence_that_correlation_misses() -> None:
    x = np.random.default_rng(1).normal(size=400)
    check = rc.check_pair(x, x ** 2, "x", "x squared")
    assert _row(check.independence, "Pearson")["pvalue"] > 0.01
    assert _row(check.independence, "Distance")["pvalue"] <= 0.01
    assert _row(check.independence, "Equal-count")["pvalue"] < 1e-6


def test_a_discrete_pair_with_a_correlation_asked_is_not_judged_against_the_copula() -> None:
    _, check = _table(rd.LAYOUT_XY, [ColumnSpec("poisson"), ColumnSpec()], n=500, correlation=0.5)
    assert check.pairs[0].against_requested[0]["note"].startswith("Not tested")
    assert check.pairs[0].tally()[0] == 0


def test_a_line_recovers_its_trend_and_its_noise_is_checked_without_it() -> None:
    generated, check = _table(rd.LAYOUT_LINE, [ColumnSpec("exponential", {"scale": 2})],
                              x_axis=Axis(0, 10, 1000), trend=(1.0, 0.5))
    assert [r["test"][:5] for r in check.extra] == ["Slope", "Inter"]
    assert all(r["pvalue"] > 1e-3 for r in check.extra)
    assert _row(check.extra, "Intercept")["note"].startswith("Found")  # asked 1 + the noise's mean 2 = 3
    assert _row(check.columns[0].fit, "Kolmogorov")["pvalue"] > 1e-3
    assert check.verdict()[0] == YES


def test_a_line_with_the_wrong_trend_is_caught() -> None:
    generated = rd.generate(rd.LAYOUT_LINE, [ColumnSpec()], x_axis=Axis(0, 10, 800), trend=(1.0, 0.5), seed=2)
    check = rc.check_generated(generated, trend=(1.0, 0.8))
    assert _row(check.extra, "Slope")["pvalue"] < 1e-10
    assert check.verdict()[0] == NO


def test_a_line_of_noise_without_a_variance_has_notes_instead_of_a_regression_test() -> None:
    _, check = _table(rd.LAYOUT_LINE, [ColumnSpec("cauchy")], x_axis=Axis(0, 1, 300))
    assert all("no variance" in r["note"] for r in check.extra)


def test_a_grid_of_noise_has_a_morans_i_near_zero_and_a_smooth_field_does_not() -> None:
    _, check = _table(rd.LAYOUT_GRID, [ColumnSpec()], x_axis=Axis(0, 1, 40), y_axis=Axis(0, 1, 30),
                      function=lambda x, y: 0.0 * x)
    row = check.extra[0]
    assert row["pvalue"] > 1e-3 and abs(row["statistic"]) < 4
    xs, ys = np.meshgrid(np.arange(30), np.arange(30))
    smooth = np.sin(xs / 5.0) + np.cos(ys / 5.0)
    assert rc.morans_i(smooth)["pvalue"] < 1e-10


def test_morans_i_rejects_a_true_hypothesis_about_one_time_in_twenty() -> None:
    rng = np.random.default_rng(0)
    pvalues = np.array([rc.morans_i(rng.normal(size=(15, 15)))["pvalue"] for _ in range(600)])
    assert 0.02 < (pvalues < 0.05).mean() < 0.09


def test_a_grid_with_its_function_taken_away_leaves_the_noise_asked_for() -> None:
    generated = rd.generate(rd.LAYOUT_GRID, [ColumnSpec("normal", {"sd": 0.2})], x_axis=Axis(0, 1, 30),
                            y_axis=Axis(0, 1, 30), function=lambda x, y: np.sin(5 * x) * y, seed=3)
    right = rc.check_generated(generated, function=lambda x, y: np.sin(5 * x) * y)
    wrong = rc.check_generated(generated)
    assert right.verdict()[0] == YES
    assert wrong.verdict()[0] == NO  # the function is left in: the "noise" is not the one asked


def test_the_verdict_counts_the_tests_and_names_the_rejections_that_chance_explains() -> None:
    generated = rd.generate(rd.LAYOUT_XY, [ColumnSpec(), ColumnSpec("exponential")], n=800, seed=1)
    check = rc.check_generated(generated)
    verdict, sentences = check.verdict()
    run, failed = check.tally()
    assert verdict == YES and run > 15
    counted = next(values for text, values in sentences if "tests were run" in text)
    assert (counted["run"], counted["failed"]) == (run, failed)
    assert counted["expected"] == pytest.approx(run * 0.05)


def test_the_verdict_says_no_naming_the_test_and_the_column() -> None:
    generated = rd.generate(rd.LAYOUT_X, [ColumnSpec("uniform")], n=1000, seed=1)
    check = rc.check_generated(generated)
    check.columns[0].distribution = "normal"  # the same numbers, judged as if a normal had been asked for
    check.columns[0].fit = rc.check_column(generated.table["X"], "normal", {"mean": 0.5, "sd": 0.29}).fit
    verdict, sentences = check.verdict()
    assert verdict == NO
    first_text, first_values = sentences[0]
    assert first_text.startswith("No:") and "X" in first_values["where"]


def test_repeating_a_good_generator_gives_flat_p_values_and_about_five_percent_rejections() -> None:
    specs = [rd.ColumnSpec("normal", {}, "X")]
    done = rc.repeat_check(lambda s: rc.check_generated(rd.generate("X", specs, n=400, seed=s)), 150, 1)
    assert done.repeats == 150 and done.seed == 1
    assert 0.02 < done.rejection_rate() < 0.09
    summary = done.summary().set_index("Test")
    assert summary.loc["Kolmogorov-Smirnov against the distribution", "Flat"] > 0.001
    assert (summary["Samples"] <= 150).all()


def test_repeating_a_wrong_claim_rejects_nearly_always_and_is_capped() -> None:
    wrong = rd.ColumnSpec("normal", {"mean": 0.5}, "X")

    def make(seed: int) -> rc.TableCheck:
        generated = rd.generate("X", [rd.ColumnSpec("normal", {}, "X")], n=400, seed=seed)
        return rc.check_generated(rd.Generated(generated.table, seed, "X", [wrong]))

    done = rc.repeat_check(make, 10, 3)
    ks = done.summary().set_index("Test").loc["Kolmogorov-Smirnov against the distribution"]
    assert ks["Rejected"] == 1.0
