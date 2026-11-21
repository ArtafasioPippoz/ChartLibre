"""Is this column really what it was drawn to be? The checks of one random column (no Qt, no logging).

The sample comes with the distribution it was drawn from (app.analysis.random_data), so unlike a test on data of
unknown origin the parameters are *known*: the tests below compare the sample with that exact distribution, with
no estimated parameter to correct for.

* fit        Kolmogorov-Smirnov and Anderson-Darling against the distribution (continuous); chi-square on its
             probabilities, small cells merged (discrete, where KS does not apply);
* moments    mean, standard deviation, skewness and excess kurtosis of the sample beside the theoretical ones,
             with a z-score where a standard error can be given honestly (mean, standard deviation);
* normality  the tests of app.analysis.statistics, run whether or not normal was asked for;
* order      the runs, turning-point, Durbin-Watson and Ljung-Box tests of app.analysis.statistics, the
             autocorrelation to ``lags`` with its 95% band, and a chi-square on pairs of neighbours;
* uniformity the probability integral transform F(x) of a sample from F is uniform on (0, 1): its histogram
             and a chi-square on it. For a discrete column F is made continuous by drawing the value within each
             step (the randomised transform), with a fixed generator so the result does not change between runs.

Between columns (:func:`check_pair`) the tests of independence - Pearson, Spearman, Kendall, a chi-square on
equal-count bins and the distance correlation, which sees a dependence a correlation of 0 hides - or, when a
correlation was asked for, whether the sample has it. On a line or a grid (:func:`check_generated`) the noise left
once the trend or the function is taken away goes through the column checks, and the trend is recovered by a
regression; the grid's residual also gets Moran's I, the correlation between neighbouring cells.

A test result is the row dictionary of app.analysis.statistics (test, n, statistic, pvalue, note); one that
cannot run comes back as a note, never as an exception. At the usual 5% one test in twenty rejects a perfectly
good sample, so :func:`tally` counts how many tests were run and how many rejected.
"""
from __future__ import annotations

import itertools
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from app.analysis import NUMERICAL_FAILURES
from app.analysis import random_data as rd
from app.analysis import statistics as st
from app.analysis.answers import ALPHA, NO, YES
from app.analysis.randomness import finite
from app.utils.i18n import _

#: Fewest values a column may have to be checked.
MIN_VALUES = 8
#: Autocorrelation lags shown, at most.
MAX_LAGS = 20
#: A chi-square cell should expect at least this many values.
MIN_EXPECTED = 5.0
#: Cells of the probability-integral histogram, and per side of the neighbour-pairs grid at most.
PIT_BINS = 10
MAX_PAIR_CELLS = 10
#: The most steps of a discrete distribution the chi-square lists (a Poisson with a huge mean).
MAX_STEPS = 10_000


@dataclass(slots=True)
class ColumnCheck:
    """Everything known about one random column."""

    name: str
    distribution: str
    n: int
    fit: list[dict[str, Any]] = field(default_factory=list)
    #: Statistic, Sample, Theoretical, Z, Note.
    moments: pd.DataFrame = field(default_factory=pd.DataFrame)
    normality: list[dict[str, Any]] = field(default_factory=list)
    order: list[dict[str, Any]] = field(default_factory=list)
    uniformity: list[dict[str, Any]] = field(default_factory=list)
    #: Lag, ACF, Lower, Upper, Outside.
    autocorrelation: pd.DataFrame = field(default_factory=pd.DataFrame)
    #: Bin, Observed, Expected: the histogram of F(x).
    pit: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def rows(self) -> list[dict[str, Any]]:
        """Every test row, in the order of the report."""
        return [*self.fit, *self.normality, *self.order, *self.uniformity]

    def tally(self, alpha: float = 0.05) -> tuple[int, int]:
        """(tests run, tests that reject at *alpha*) over :attr:`rows`; the normality tests count too only when
        the column was meant to be normal."""
        rows = [*self.fit, *self.order, *self.uniformity]
        if self.distribution == "normal":
            rows += self.normality
        return tally(rows, alpha)


def tally(rows: list[dict[str, Any]], alpha: float = 0.05) -> tuple[int, int]:
    """(rows with a p-value, rows whose p-value is below *alpha*)."""
    pvalues = [float(r["pvalue"]) for r in rows if np.isfinite(r.get("pvalue", np.nan))]
    return len(pvalues), sum(1 for p in pvalues if p < alpha)


# ----------------------------------------------------------------------
# Probability integral transform
# ----------------------------------------------------------------------
def probability_integral(values: np.ndarray, key: str, parameters: Any = None) -> np.ndarray:
    """F(x) for each value: uniform on (0, 1) when the values come from F. Discrete: randomised within the step."""
    frozen = rd.theory(key, parameters)
    if rd.distribution(key).discrete:
        upper = np.asarray(frozen.cdf(values), dtype=float)
        lower = np.asarray(frozen.cdf(values - 1), dtype=float)
        jitter = np.random.default_rng(0).random(values.size)
        u = lower + jitter * (upper - lower)
    else:
        u = np.asarray(frozen.cdf(values), dtype=float)
    return np.clip(u, 1e-12, 1.0 - 1e-12)


# ----------------------------------------------------------------------
# Fit
# ----------------------------------------------------------------------
def anderson_darling_pvalue(statistic: float) -> float:
    """Upper-tail probability of the Anderson-Darling A-squared for a distribution known in full (Marsaglia and
    Marsaglia, 2004: accurate to about 1e-3 for 50 values or more; the 5% point is 2.492)."""
    z = float(statistic)
    if z <= 0:
        return 1.0
    if z < 2.0:
        poly = 2.00012 + (0.247105 - (0.0649821 - (0.0347962 - (0.011672 - 0.00168691 * z) * z) * z) * z) * z
        cdf = z ** -0.5 * np.exp(-1.2337141 / z) * poly
    else:
        cdf = np.exp(-np.exp(1.0776 - (2.30695 - (0.43424 - (0.082433 - (0.008056 - 0.0003146 * z) * z) * z) * z) * z))
    return float(min(1.0, max(0.0, 1.0 - cdf)))


def anderson_darling(u: np.ndarray) -> float:
    """A-squared of values *u* that are uniform on (0, 1) under the hypothesis."""
    u = np.sort(u)
    n = u.size
    i = np.arange(1, n + 1)
    return float(-n - np.sum((2 * i - 1) * (np.log(u) + np.log1p(-u[::-1]))) / n)


def _discrete_cells(frozen: Any, count: int) -> tuple[int, np.ndarray, np.ndarray]:
    """The first step, the groups' expected counts and each step's group, small groups merged to MIN_EXPECTED."""
    low = int(frozen.ppf(1e-9))
    high = min(int(frozen.ppf(1.0 - 1e-9)), low + MAX_STEPS)
    support = np.arange(low, high + 1)
    probability = np.asarray(frozen.pmf(support), dtype=float)
    probability[0] += float(frozen.cdf(low - 1))
    probability[-1] += float(frozen.sf(high))
    expected = probability * count
    group = np.zeros(support.size, dtype=int)
    current, filled = 0, 0.0
    for index, e in enumerate(expected):
        group[index] = current
        filled += e
        if filled >= MIN_EXPECTED:
            current, filled = current + 1, 0.0
    if filled > 0 and current > 0:  # what is left over joins the last full group
        group[group == current] = current - 1
    cells = int(group.max()) + 1
    return low, np.bincount(group, weights=expected, minlength=cells), group


def _fit_discrete(values: np.ndarray, frozen: Any) -> list[dict[str, Any]]:
    n = values.size
    name = _("Chi-square against the distribution")
    low, expected, group = _discrete_cells(frozen, n)
    if expected.size < 2:
        return [st.note_row(name, n, _("Too few values for a chi-square: every cell would expect under 5"))]
    steps = np.clip(np.rint(values).astype(int), low, low + group.size - 1) - low
    observed = np.bincount(group[steps], minlength=expected.size).astype(float)
    result = stats.chisquare(observed, expected * (observed.sum() / expected.sum()))
    note = _("{cells} cells, each expecting at least {minimum:g}").format(cells=expected.size, minimum=MIN_EXPECTED)
    return [st.result_row(name, n, float(result.statistic), float(result.pvalue), note)]


def _fit_continuous(values: np.ndarray, frozen: Any) -> list[dict[str, Any]]:
    n = values.size
    rows: list[dict[str, Any]] = []
    try:
        ks = stats.kstest(values, frozen.cdf)
        rows.append(st.result_row(_("Kolmogorov-Smirnov against the distribution"), n,
                                  float(ks.statistic), float(ks.pvalue)))
    except NUMERICAL_FAILURES as exc:
        rows.append(st.note_row(_("Kolmogorov-Smirnov against the distribution"), n, str(exc)))
    u = np.clip(np.asarray(frozen.cdf(values), dtype=float), 1e-12, 1.0 - 1e-12)
    a2 = anderson_darling(u)
    note = "" if n >= 50 else _("The p-value is approximate under 50 values")
    rows.append(st.result_row(_("Anderson-Darling against the distribution"), n, a2, anderson_darling_pvalue(a2), note))
    return rows


# ----------------------------------------------------------------------
# Moments
# ----------------------------------------------------------------------
def _moments_table(values: np.ndarray, key: str, parameters: Any) -> pd.DataFrame:
    n = values.size
    theoretical = rd.theoretical_moments(key, parameters)
    sd_theory = theoretical["variance"] ** 0.5 if np.isfinite(theoretical["variance"]) else np.nan
    kurt_theory = theoretical["kurtosis"]
    sample = {
        "mean": float(np.mean(values)),
        "sd": float(np.std(values, ddof=1)),
        "skewness": float(stats.skew(values, bias=False)),
        "kurtosis": float(stats.kurtosis(values, bias=False)),
    }
    expected = {"mean": theoretical["mean"], "sd": sd_theory,
                "skewness": theoretical["skewness"], "kurtosis": kurt_theory}
    z = {name: np.nan for name in sample}
    if np.isfinite(sd_theory) and sd_theory > 0:
        z["mean"] = (sample["mean"] - expected["mean"]) / (sd_theory / np.sqrt(n))
        if np.isfinite(kurt_theory) and kurt_theory > -2.0:
            z["sd"] = (sample["sd"] - sd_theory) / (sd_theory * np.sqrt((kurt_theory + 2.0) / (4.0 * n)))
    labels = {"mean": _("Mean"), "sd": _("Standard deviation"), "skewness": _("Skewness"),
              "kurtosis": _("Excess kurtosis")}
    rows = []
    for name in sample:
        if not np.isfinite(expected[name]):
            note = _("Undefined for this distribution")
        elif name in ("skewness", "kurtosis"):
            note = _("No standard error given: it depends on the distribution")
        elif np.isnan(z[name]):
            note = _("No standard error: the distribution's fourth moment is undefined")
        else:
            note = ""
        rows.append({"Statistic": labels[name], "Sample": sample[name], "Theoretical": expected[name],
                     "Z": z[name], "Note": note})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------
# Order
# ----------------------------------------------------------------------
def autocorrelation(values: np.ndarray, lags: int = MAX_LAGS) -> pd.DataFrame:
    """The autocorrelation at lags 1..lags with the 95% band of white noise, +-1.96 / sqrt(n)."""
    n = values.size
    lags = max(1, min(int(lags), n // 4))
    centred = values - np.mean(values)
    denominator = float(np.dot(centred, centred))
    if denominator == 0.0:
        acf = np.full(lags, np.nan)
    else:
        acf = np.array([np.dot(centred[:-k], centred[k:]) / denominator for k in range(1, lags + 1)])
    band = 1.96 / np.sqrt(n)
    return pd.DataFrame({"Lag": np.arange(1, lags + 1), "ACF": acf, "Lower": -band, "Upper": band,
                         "Outside": np.abs(acf) > band})


def neighbour_pairs(u: np.ndarray) -> list[dict[str, Any]]:
    """Chi-square on the pairs (u[i], u[i+1]) in a k by k grid: independent neighbours fill it evenly. It catches
    what the runs test misses - a value that depends on the one before in a way that crosses the median."""
    name = _("Neighbour pairs chi-square")
    pairs = u.size - 1
    k = min(MAX_PAIR_CELLS, int(np.sqrt(pairs / MIN_EXPECTED)))
    if k < 2:
        return [st.note_row(name, u.size, _("Too few values: the grid would expect under 5 pairs per cell"))]
    observed, _x, _y = np.histogram2d(u[:-1], u[1:], bins=k, range=[[0, 1], [0, 1]])
    expected = pairs / (k * k)
    statistic = float(np.sum((observed - expected) ** 2 / expected))
    pvalue = float(stats.chi2.sf(statistic, k * k - 1))
    return [st.result_row(name, u.size, statistic, pvalue, _("{k} by {k} cells").format(k=k))]


# ----------------------------------------------------------------------
# Uniformity of F(x)
# ----------------------------------------------------------------------
def _uniformity(u: np.ndarray) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    n = u.size
    bins = min(PIT_BINS, max(2, int(n / MIN_EXPECTED)))
    observed, edges = np.histogram(u, bins=bins, range=(0.0, 1.0))
    expected = np.full(bins, n / bins)
    statistic = float(np.sum((observed - expected) ** 2 / expected))
    pvalue = float(stats.chi2.sf(statistic, bins - 1))
    table = pd.DataFrame({"Bin": [f"{edges[i]:.1f}-{edges[i + 1]:.1f}" for i in range(bins)],
                          "Observed": observed.astype(float), "Expected": expected})
    row = st.result_row(_("Uniformity of F(x) chi-square"), n, statistic, pvalue,
                        _("{bins} equal bins").format(bins=bins))
    return [row], table


# ----------------------------------------------------------------------
# One column
# ----------------------------------------------------------------------
def check_column(values: Any, key: str, parameters: Any = None, *, name: str = "", lags: int = MAX_LAGS) -> ColumnCheck:
    """All the checks of one column drawn from distribution *key* with *parameters*.

    The order of *values* is meaningful (the order tests); non-finite values are dropped.
    """
    values = finite(values)
    n = int(values.size)
    if n < MIN_VALUES:
        raise ValueError(_("A column needs at least {minimum} values to be checked; it has {n}").format(
            minimum=MIN_VALUES, n=n))
    dist = rd.distribution(key)
    frozen = rd.theory(key, parameters)
    u = probability_integral(values, key, parameters)

    fit = _fit_discrete(values, frozen) if dist.discrete else _fit_continuous(values, frozen)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # Shapiro-Wilk's warning about samples above 5000 values
        normality = st.normality_tests(values)
    order = st.randomness_tests(values) + neighbour_pairs(u)
    uniformity, pit = _uniformity(u)
    return ColumnCheck(
        name=name, distribution=key, n=n, fit=fit, moments=_moments_table(values, key, parameters),
        normality=normality, order=order, uniformity=uniformity,
        autocorrelation=autocorrelation(values, lags), pit=pit)


# ----------------------------------------------------------------------
# Between two columns
# ----------------------------------------------------------------------
#: The distance correlation's permutation test uses at most this many rows (its matrices are n by n) and this many
#: permutations; the rows are a fixed random choice, so the answer does not change between runs.
DCOR_ROWS = 500
DCOR_PERMUTATIONS = 199


@dataclass(slots=True)
class PairCheck:
    """Two columns of one table."""

    first: str
    second: str
    n: int
    #: The correlation asked for (the copula's), or None for independent columns.
    requested: float | None
    #: Tests whose null hypothesis is "independent".
    independence: list[dict[str, Any]] = field(default_factory=list)
    #: Tests whose null hypothesis is "the correlation is the one asked for"; empty when none was.
    against_requested: list[dict[str, Any]] = field(default_factory=list)

    @property
    def rows(self) -> list[dict[str, Any]]:
        return [*self.independence, *self.against_requested]

    @property
    def counted(self) -> list[dict[str, Any]]:
        """The rows that decide whether the pair is as drawn: independence when none was asked for, else the
        correlation asked for (independence is then expected to be rejected)."""
        return self.independence if self.requested is None else self.against_requested

    def tally(self, alpha: float = ALPHA) -> tuple[int, int]:
        return tally(self.counted, alpha)


def _distance_matrix(values: np.ndarray) -> np.ndarray:
    """Double-centred matrix of the distances between the values."""
    distance = np.abs(values[:, None] - values[None, :])
    return distance - distance.mean(axis=0) - distance.mean(axis=1)[:, None] + distance.mean()


def distance_correlation(a: np.ndarray, b: np.ndarray, *, permutations: int = DCOR_PERMUTATIONS,
                         seed: int = 0) -> tuple[float, float]:
    """(distance correlation, permutation p-value) of two columns: 0 only when they are independent, whatever
    the shape of the dependence."""
    rng = np.random.default_rng(seed)
    if a.size > DCOR_ROWS:
        keep = np.sort(rng.choice(a.size, DCOR_ROWS, replace=False))
        a, b = a[keep], b[keep]
    ma, mb = _distance_matrix(a), _distance_matrix(b)
    denominator = np.sqrt(np.mean(ma * ma) * np.mean(mb * mb))
    if denominator == 0.0:
        return float("nan"), float("nan")
    statistic = float(np.sqrt(max(np.mean(ma * mb), 0.0) / denominator))
    count = 0
    for _round in range(permutations):
        order = rng.permutation(a.size)
        shuffled = max(np.mean(ma * mb[np.ix_(order, order)]), 0.0)
        count += int(np.sqrt(shuffled / denominator) >= statistic)
    return statistic, (1 + count) / (1 + permutations)


def _bin_chi_square(a: np.ndarray, b: np.ndarray) -> dict[str, Any]:
    """Chi-square of independence on k by k equal-count bins (by rank)."""
    name = _("Equal-count bins chi-square")
    n = a.size
    k = min(PIT_BINS, int(np.sqrt(n / MIN_EXPECTED)))
    if k < 2:
        return st.note_row(name, n, _("Too few values for a grid with 5 expected per cell"))
    ia = np.floor((stats.rankdata(a, method="ordinal") - 1) * k / n).astype(int)
    ib = np.floor((stats.rankdata(b, method="ordinal") - 1) * k / n).astype(int)
    table = np.zeros((k, k))
    np.add.at(table, (ia, ib), 1.0)
    chi2, pvalue, _dof, _expected = stats.chi2_contingency(table, correction=False)
    return st.result_row(name, n, float(chi2), float(pvalue), _("{k} by {k} bins").format(k=k))


def _fisher_row(name: str, n: int, observed: float, expected: float, spread: float, note: str) -> dict[str, Any]:
    """A z-test of a correlation against a value, on Fisher's z; *spread* multiplies the variance 1 / (n - 3)."""
    z = (np.arctanh(np.clip(observed, -0.999999, 0.999999)) - np.arctanh(expected)) * np.sqrt((n - 3) / spread)
    return st.result_row(name, n, float(z), float(2.0 * stats.norm.sf(abs(z))), note)


def check_pair(a: Any, b: Any, first: str, second: str, *, distributions: tuple[str, str] = ("", ""),
               requested: float | None = None) -> PairCheck:
    """Are two columns independent, or - when *requested* (the Gaussian copula's correlation) was asked for -
    do they have the dependence asked for? *distributions* are their keys, to know whether the exact relation
    between the request and Spearman's coefficient holds (continuous columns only)."""
    both = np.column_stack([np.asarray(a, dtype=float), np.asarray(b, dtype=float)])
    both = both[np.isfinite(both).all(axis=1)]
    n = int(both.shape[0])
    if n < MIN_VALUES:
        raise ValueError(_("A pair needs at least {minimum} complete rows to be checked; it has {n}").format(
            minimum=MIN_VALUES, n=n))
    x, y = both[:, 0], both[:, 1]
    result = PairCheck(first, second, n, requested)

    pearson, spearman, kendall = stats.pearsonr(x, y), stats.spearmanr(x, y), stats.kendalltau(x, y)
    result.independence = [
        st.result_row(_("Pearson correlation"), n, float(pearson.statistic), float(pearson.pvalue)),
        st.result_row(_("Spearman correlation"), n, float(spearman.statistic), float(spearman.pvalue)),
        st.result_row(_("Kendall correlation"), n, float(kendall.statistic), float(kendall.pvalue)),
        _bin_chi_square(x, y),
    ]
    dcor, dcor_p = distance_correlation(x, y)
    if np.isfinite(dcor):
        result.independence.append(st.result_row(_("Distance correlation"), n, dcor, dcor_p,
                                                 _("{count} permutations").format(count=DCOR_PERMUTATIONS)))
    if requested is not None:
        continuous = not any(key and rd.distribution(key).discrete for key in distributions)
        if continuous:
            expected = 6.0 / np.pi * np.arcsin(requested / 2.0)
            result.against_requested.append(_fisher_row(
                _("Spearman against the one asked"), n, float(spearman.statistic), float(expected), 1.06,
                _("Asked {requested:g}: a Gaussian copula gives a Spearman of {expected:.3f}").format(
                    requested=requested, expected=expected)))
            if distributions == ("normal", "normal"):
                result.against_requested.append(_fisher_row(
                    _("Pearson against the one asked"), n, float(pearson.statistic), requested, 1.0,
                    _("Asked {requested:g}").format(requested=requested)))
        else:
            result.against_requested.append(st.note_row(
                _("Correlation against the one asked"), n,
                _("Not tested: a discrete column has ties that change the relation between the copula and the coefficients")))
    return result


# ----------------------------------------------------------------------
# A line and a grid
# ----------------------------------------------------------------------
def morans_i(field_values: np.ndarray) -> dict[str, Any]:
    """Moran's I of a 2-D array with rook neighbours (up, down, left, right): the correlation between
    neighbouring cells. About -1/(N-1) for independent cells; the z-score uses the randomisation variance."""
    name = _("Moran's I (neighbouring cells)")
    grid = np.asarray(field_values, dtype=float)
    cells = grid.size
    if grid.ndim != 2 or min(grid.shape) < 2 or cells < 9:
        return st.note_row(name, cells, _("The grid is too small for Moran's I"))
    z = grid - grid.mean()
    m2 = float(np.mean(z ** 2))
    if m2 == 0.0:
        return st.note_row(name, cells, _("Every cell has the same value"))
    pair_sum = float(np.sum(z[:, :-1] * z[:, 1:]) + np.sum(z[:-1, :] * z[1:, :]))
    pairs = z[:, :-1].size + z[:-1, :].size
    moran = (cells / pairs) * pair_sum / float(np.sum(z ** 2))
    # Binary symmetric weights: S0 = 2 pairs, S1 = 2 S0, S2 = 4 sum of squared neighbour counts.
    neighbours = np.zeros(grid.shape)
    neighbours[:, :-1] += 1
    neighbours[:, 1:] += 1
    neighbours[:-1, :] += 1
    neighbours[1:, :] += 1
    s0 = 2.0 * pairs
    s1 = 2.0 * s0
    s2 = 4.0 * float(np.sum(neighbours ** 2))
    k = float(np.mean(z ** 4)) / m2 ** 2
    n = float(cells)
    e2 = (n * ((n * n - 3 * n + 3) * s1 - n * s2 + 3 * s0 ** 2)
          - k * ((n * n - n) * s1 - 2 * n * s2 + 6 * s0 ** 2)) / ((n - 1) * (n - 2) * (n - 3) * s0 ** 2)
    expected = -1.0 / (n - 1)
    variance = e2 - expected ** 2
    if variance <= 0:
        return st.note_row(name, cells, _("The variance of Moran's I could not be computed"))
    score = (moran - expected) / np.sqrt(variance)
    return st.result_row(name, cells, float(score), float(2.0 * stats.norm.sf(abs(score))),
                         _("I = {moran:.4f}, expected {expected:.4f}").format(moran=moran, expected=expected))


def _trend_rows(x: np.ndarray, y: np.ndarray, trend: tuple[float, float], key: str, parameters: Any) -> list[dict[str, Any]]:
    """The line a + b X recovered by least squares: the slope and the intercept against the ones asked for (the
    intercept also carries the noise's mean)."""
    n = x.size
    moments = rd.theoretical_moments(key, parameters)
    names = (_("Slope against the one asked"), _("Intercept against the one asked"))
    if not np.isfinite(moments["variance"]):
        return [st.note_row(name, n, _("Not tested: the noise has no variance, so least squares has no standard error"))
                for name in names]
    fit = stats.linregress(x, y)
    mean = moments["mean"] if np.isfinite(moments["mean"]) else 0.0
    rows = []
    for name, found, error, wanted in ((names[0], fit.slope, fit.stderr, trend[1]),
                                       (names[1], fit.intercept, fit.intercept_stderr, trend[0] + mean)):
        t = (found - wanted) / error if error > 0 else float("nan")
        rows.append(st.result_row(name, n, float(t), float(2.0 * stats.t.sf(abs(t), n - 2)),
                                  _("Found {found:.4g}, asked {wanted:.4g}").format(found=found, wanted=wanted)))
    return rows


# ----------------------------------------------------------------------
# A whole table
# ----------------------------------------------------------------------
@dataclass(slots=True)
class TableCheck:
    """The checks of one generated table."""

    layout: str
    seed: int
    columns: list[ColumnCheck] = field(default_factory=list)
    pairs: list[PairCheck] = field(default_factory=list)
    #: The regression of a line and Moran's I of a grid.
    extra: list[dict[str, Any]] = field(default_factory=list)

    def counted(self) -> list[tuple[str, dict[str, Any]]]:
        """(where, row) for every test that decides whether the table is as drawn."""
        found: list[tuple[str, dict[str, Any]]] = []
        for column in self.columns:
            rows = [*column.fit, *column.order, *column.uniformity]
            if column.distribution == "normal":
                rows += column.normality
            found += [(column.name, row) for row in rows]
        for pair in self.pairs:
            found += [(f"{pair.first} / {pair.second}", row) for row in pair.counted]
        found += [("", row) for row in self.extra]
        return found

    def tally(self, alpha: float = ALPHA) -> tuple[int, int]:
        return tally([row for _where, row in self.counted()], alpha)

    def verdict(self, alpha: float = ALPHA) -> tuple[str, list[tuple[str, dict[str, Any]]]]:
        """YES when nothing argues against the table being as drawn, and the sentences that say why, as
        templates with their values (translated by the dialog).

        One test in twenty rejects a good sample at 5%, so a rejection counts against the table only when it
        would be unlikely among all the tests run (p below alpha divided by their number, Bonferroni).
        """
        tested = [(where, row) for where, row in self.counted() if np.isfinite(row.get("pvalue", np.nan))]
        run = len(tested)
        if run == 0:
            return YES, [("No test could be run on this table.", {})]
        failed = sorted(((float(row["pvalue"]), where, row["test"]) for where, row in tested
                         if float(row["pvalue"]) < alpha))
        values = {"run": run, "failed": len(failed), "alpha": alpha, "expected": run * alpha}
        sentences: list[tuple[str, dict[str, Any]]] = []
        if failed and failed[0][0] < alpha / run:
            p, where, test = failed[0]
            verdict = NO
            sentences.append(("No: {test}{where} rejects at p = {p:.3g}, far below what chance gives among {run} "
                              "tests.", {**values, "test": test, "p": p, "where": f" of {where}" if where else ""}))
        else:
            verdict = YES
            sentences.append(("Yes: nothing here argues against the table being drawn as asked.", values))
        sentences.append(("{run} tests were run and {failed} rejected at {alpha:.0%}; about {expected:.1f} are "
                          "expected to by chance when the sample is good.", values))
        if failed and verdict == YES:
            listed = "; ".join(f"{test}{f' of {where}' if where else ''} (p = {p:.3g})" for p, where, test in failed)
            sentences.append(("The ones that rejected: {listed}. Alone they are within chance; draw again with "
                              "another seed to see whether they come back.", {"listed": listed}))
        return verdict, sentences


def _requested_correlations(correlation: float | Sequence[Sequence[float]] | None, size: int) -> np.ndarray | None:
    return rd.correlation_matrix(correlation, size) if size > 1 else None


def check_generated(
    generated: rd.Generated,
    *,
    correlation: float | Sequence[Sequence[float]] | None = None,
    trend: tuple[float, float] = (0.0, 0.0),
    function: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None,
    lags: int = MAX_LAGS,
) -> TableCheck:
    """All the checks of a table from :func:`app.analysis.random_data.generate`, given the same *correlation*,
    *trend* and *function* it was generated with."""
    table, layout = generated.table, generated.layout
    result = TableCheck(layout, generated.seed)
    specs = list(generated.columns)

    if layout in (rd.LAYOUT_X, rd.LAYOUT_XY, rd.LAYOUT_XYZ):
        for spec in specs:
            result.columns.append(check_column(table[spec.name], spec.distribution, spec.parameters,
                                               name=spec.name, lags=lags))
        matrix = _requested_correlations(correlation, len(specs))
        for i, j in itertools.combinations(range(len(specs)), 2):
            a, b = specs[i], specs[j]
            result.pairs.append(check_pair(
                table[a.name], table[b.name], a.name, b.name, distributions=(a.distribution, b.distribution),
                requested=None if matrix is None else float(matrix[i, j])))
        return result

    spec = specs[0]
    if layout == rd.LAYOUT_LINE:
        x, y = table.iloc[:, 0].to_numpy(), table.iloc[:, 1].to_numpy()
        noise = y - (trend[0] + trend[1] * x)
        result.extra = _trend_rows(x, y, trend, spec.distribution, spec.parameters)
    else:
        x, y, z = (table.iloc[:, i].to_numpy() for i in range(3))
        noise = z - (np.asarray(function(x, y), dtype=float) if function is not None else 0.0)
        width = int(np.flatnonzero(y != y[0])[0])  # cells before Y changes: the grid's width, X varying fastest
        result.extra = [morans_i(noise.reshape(-1, width))]
    result.columns.append(check_column(noise, spec.distribution, spec.parameters, name=spec.name, lags=lags))
    return result


# ----------------------------------------------------------------------
# Repeating the experiment
# ----------------------------------------------------------------------
#: The most samples a repetition draws (each is checked: a second or two for a hundred of them).
MAX_REPEATS = 500


@dataclass(slots=True)
class Repeated:
    """The p-values of every test over many samples drawn with the seeds seed, seed + 1, ...

    When the generator does what it should and the test is exact, a test's p-values are spread evenly between 0
    and 1 and it rejects at alpha in a fraction alpha of the samples. That is the lesson: one p = 0.03 means little.
    """

    repeats: int
    seed: int
    #: (where, test) -> the p-values, in the order of the seeds (a sample where the test could not run is left out).
    pvalues: dict[tuple[str, str], np.ndarray] = field(default_factory=dict)

    def summary(self, alpha: float = ALPHA) -> pd.DataFrame:
        """One row per test: Where, Test, Samples, Rejected (fraction at alpha), Flat (p of a KS test of the
        p-values against the uniform; small: the test is not exact here, or the generator is not)."""
        rows = []
        for (where, test), values in self.pvalues.items():
            flat = float(stats.kstest(values, "uniform").pvalue) if len(values) >= 20 else float("nan")
            rows.append({"Where": where, "Test": test, "Samples": len(values),
                         "Rejected": float(np.mean(values < alpha)), "Flat": flat})
        return pd.DataFrame(rows, columns=["Where", "Test", "Samples", "Rejected", "Flat"])

    def pooled(self) -> np.ndarray:
        """Every p-value of every test, for one histogram."""
        parts = list(self.pvalues.values())
        return np.concatenate(parts) if parts else np.empty(0)

    def rejection_rate(self, alpha: float = ALPHA) -> float:
        pooled = self.pooled()
        return float(np.mean(pooled < alpha)) if pooled.size else float("nan")


def repeat_check(make: Callable[[int], TableCheck], repeats: int, seed: int) -> Repeated:
    """Draw and check *repeats* samples: ``make(seed + i)`` gives the checks of the i-th."""
    repeats = max(1, min(int(repeats), MAX_REPEATS))
    collected: dict[tuple[str, str], list[float]] = {}
    for index in range(repeats):
        for where, row in make(seed + index).counted():
            p = float(row.get("pvalue", np.nan))
            if np.isfinite(p):
                collected.setdefault((where, str(row["test"])), []).append(p)
    return Repeated(repeats, seed, {key: np.asarray(values) for key, values in collected.items()})
