"""Random data: samples drawn with numpy.random from a chosen distribution, in five table layouts.

The engine behind the Random data operation. Nothing here knows about Qt, the repository or a chart: it takes
the distribution of each column and returns a table, so the dialog, a test, a script and the assistant all draw
the same numbers from the same seed.

A *distribution* is an entry of the registry: its parameters (with their valid range), the numpy call that draws
from it and the scipy.stats twin that says what it should look like (density, cdf, moments), which is what the
checks of the sample are made against. One ``numpy.random.Generator`` serves the whole table and its columns are
drawn in order, so the same seed gives the same table.

The layouts:

* ``X``          one random column;
* ``XY``         two random columns, independent or correlated;
* ``XYZ``        three random columns, independent or correlated;
* ``GRID``       X and Y evenly spaced over a grid (every X with every Y), Z random, optionally on top of a
                 function of x and y;
* ``LINE``       X evenly spaced, Y random, optionally on top of a straight trend a + b X.

Correlation is a Gaussian copula: correlated normal numbers are turned into each column's own distribution
through its quantile function, so any distributions can be correlated. For normal columns the requested value is
exactly the Pearson correlation; for the others it is the correlation of the copula (Spearman's is close to it).
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from app.analysis.function_plot import SPACING_LINEAR, build_range
from app.utils.i18n import _

#: Most rows one table may have; a grid counts every X with every Y.
MAX_ROWS = 1_000_000

LAYOUT_X = "X"
LAYOUT_XY = "XY"
LAYOUT_XYZ = "XYZ"
LAYOUT_GRID = "GRID"
LAYOUT_LINE = "LINE"

#: How many random columns each layout has.
RANDOM_COLUMNS: dict[str, int] = {LAYOUT_X: 1, LAYOUT_XY: 2, LAYOUT_XYZ: 3, LAYOUT_GRID: 1, LAYOUT_LINE: 1}

#: Names the columns take when the caller gives none.
DEFAULT_NAMES: dict[str, tuple[str, ...]] = {
    LAYOUT_X: ("X",),
    LAYOUT_XY: ("X", "Y"),
    LAYOUT_XYZ: ("X", "Y", "Z"),
    LAYOUT_GRID: ("Z",),
    LAYOUT_LINE: ("Y",),
}


# ----------------------------------------------------------------------
# The registry of distributions
# ----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Parameter:
    """One parameter of a distribution, with the range it is valid in."""

    name: str
    default: float
    #: None = unbounded on that side.
    minimum: float | None = None
    maximum: float | None = None
    #: True when the bound itself is not valid (a scale must be above 0, not 0).
    open_minimum: bool = False
    open_maximum: bool = False
    integer: bool = False

    def check(self, value: float, distribution: str) -> float:
        """The value, or a ValueError in words when it lies outside the range."""
        value = float(value)
        if not np.isfinite(value):
            raise ValueError(_("The {parameter} of the {distribution} distribution must be a number").format(
                parameter=self.name, distribution=distribution))
        if self.integer and value != int(value):
            raise ValueError(_("The {parameter} of the {distribution} distribution must be a whole number").format(
                parameter=self.name, distribution=distribution))
        if self.minimum is not None and (value <= self.minimum if self.open_minimum else value < self.minimum):
            raise ValueError(_("The {parameter} of the {distribution} distribution must be {sign} {bound:g}").format(
                parameter=self.name, distribution=distribution,
                sign=_("above") if self.open_minimum else _("at least"), bound=self.minimum))
        if self.maximum is not None and (value >= self.maximum if self.open_maximum else value > self.maximum):
            raise ValueError(_("The {parameter} of the {distribution} distribution must be {sign} {bound:g}").format(
                parameter=self.name, distribution=distribution,
                sign=_("below") if self.open_maximum else _("at most"), bound=self.maximum))
        return value


@dataclass(frozen=True, slots=True)
class Distribution:
    """What the registry knows about one distribution."""

    key: str
    label: str
    discrete: bool
    parameters: tuple[Parameter, ...]
    #: numpy: draw(rng, size, p) with p the parameters in order.
    draw: Callable[[np.random.Generator, int, tuple[float, ...]], np.ndarray]
    #: scipy.stats: the frozen distribution the sample should follow.
    frozen: Callable[[tuple[float, ...]], Any]
    #: A rule the parameters must satisfy together (triangular: left <= mode <= right), or None.
    joint_check: Callable[[tuple[float, ...]], str] | None = None


def _normal() -> Distribution:
    return Distribution(
        "normal", "Normal", False,
        (Parameter("mean", 0.0), Parameter("sd", 1.0, 0.0, open_minimum=True)),
        lambda rng, n, p: rng.normal(p[0], p[1], n),
        lambda p: stats.norm(p[0], p[1]))


def _uniform() -> Distribution:
    return Distribution(
        "uniform", "Uniform", False,
        (Parameter("low", 0.0), Parameter("high", 1.0)),
        lambda rng, n, p: rng.uniform(p[0], p[1], n),
        lambda p: stats.uniform(p[0], p[1] - p[0]),
        lambda p: "" if p[0] < p[1] else _("The low of the uniform distribution must be below its high"))


def _triangular() -> Distribution:
    def joint(p: tuple[float, ...]) -> str:
        if p[0] < p[2] and p[0] <= p[1] <= p[2]:
            return ""
        return _("The triangular distribution needs left <= mode <= right, with left below right")

    return Distribution(
        "triangular", "Triangular", False,
        (Parameter("left", 0.0), Parameter("mode", 0.5), Parameter("right", 1.0)),
        lambda rng, n, p: rng.triangular(p[0], p[1], p[2], n),
        lambda p: stats.triang((p[1] - p[0]) / (p[2] - p[0]), p[0], p[2] - p[0]),
        joint)


def _integers() -> Distribution:
    return Distribution(
        "integers", "Integers (uniform)", True,
        (Parameter("low", 0.0, integer=True), Parameter("high", 9.0, integer=True)),
        lambda rng, n, p: rng.integers(int(p[0]), int(p[1]) + 1, n).astype(float),
        lambda p: stats.randint(int(p[0]), int(p[1]) + 1),
        lambda p: "" if p[0] <= p[1] else _("The low of the integers must not be above their high"))


def _registry() -> dict[str, Distribution]:
    positive = {"minimum": 0.0, "open_minimum": True}
    entries = [
        _normal(),
        _uniform(),
        Distribution("exponential", "Exponential", False,
                     (Parameter("scale", 1.0, **positive),),
                     lambda rng, n, p: rng.exponential(p[0], n),
                     lambda p: stats.expon(scale=p[0])),
        Distribution("lognormal", "Lognormal", False,
                     (Parameter("mu", 0.0), Parameter("sigma", 1.0, **positive)),
                     lambda rng, n, p: rng.lognormal(p[0], p[1], n),
                     lambda p: stats.lognorm(p[1], scale=float(np.exp(p[0])))),
        Distribution("gamma", "Gamma", False,
                     (Parameter("shape", 2.0, **positive), Parameter("scale", 1.0, **positive)),
                     lambda rng, n, p: rng.gamma(p[0], p[1], n),
                     lambda p: stats.gamma(p[0], scale=p[1])),
        Distribution("beta", "Beta", False,
                     (Parameter("a", 2.0, **positive), Parameter("b", 5.0, **positive)),
                     lambda rng, n, p: rng.beta(p[0], p[1], n),
                     lambda p: stats.beta(p[0], p[1])),
        Distribution("chisquare", "Chi-square", False,
                     (Parameter("df", 3.0, **positive),),
                     lambda rng, n, p: rng.chisquare(p[0], n),
                     lambda p: stats.chi2(p[0])),
        Distribution("t", "Student t", False,
                     (Parameter("df", 5.0, **positive),),
                     lambda rng, n, p: rng.standard_t(p[0], n),
                     lambda p: stats.t(p[0])),
        Distribution("weibull", "Weibull", False,
                     (Parameter("shape", 1.5, **positive), Parameter("scale", 1.0, **positive)),
                     lambda rng, n, p: rng.weibull(p[0], n) * p[1],
                     lambda p: stats.weibull_min(p[0], scale=p[1])),
        Distribution("laplace", "Laplace", False,
                     (Parameter("location", 0.0), Parameter("scale", 1.0, **positive)),
                     lambda rng, n, p: rng.laplace(p[0], p[1], n),
                     lambda p: stats.laplace(p[0], p[1])),
        Distribution("logistic", "Logistic", False,
                     (Parameter("location", 0.0), Parameter("scale", 1.0, **positive)),
                     lambda rng, n, p: rng.logistic(p[0], p[1], n),
                     lambda p: stats.logistic(p[0], p[1])),
        _triangular(),
        # No mean and no variance: the classic random-but-not-normal sample; its moments come out undefined.
        Distribution("cauchy", "Cauchy", False,
                     (Parameter("location", 0.0), Parameter("scale", 1.0, **positive)),
                     lambda rng, n, p: p[0] + p[1] * rng.standard_cauchy(n),
                     lambda p: stats.cauchy(p[0], p[1])),
        _integers(),
        Distribution("binomial", "Binomial", True,
                     (Parameter("n", 10.0, 1.0, integer=True), Parameter("p", 0.5, 0.0, 1.0)),
                     lambda rng, n, p: rng.binomial(int(p[0]), p[1], n).astype(float),
                     lambda p: stats.binom(int(p[0]), p[1])),
        Distribution("poisson", "Poisson", True,
                     (Parameter("mu", 4.0, **positive),),
                     lambda rng, n, p: rng.poisson(p[0], n).astype(float),
                     lambda p: stats.poisson(p[0])),
        Distribution("geometric", "Geometric", True,
                     (Parameter("p", 0.3, 0.0, 1.0, open_minimum=True),),
                     lambda rng, n, p: rng.geometric(p[0], n).astype(float),
                     lambda p: stats.geom(p[0])),
    ]
    return {entry.key: entry for entry in entries}


DISTRIBUTIONS: dict[str, Distribution] = _registry()


def distribution(key: str) -> Distribution:
    """The registry entry for *key*, or a ValueError naming the ones there are."""
    try:
        return DISTRIBUTIONS[key]
    except KeyError:
        raise ValueError(_("Unknown distribution '{key}'. Available: {names}").format(
            key=key, names=", ".join(DISTRIBUTIONS))) from None


def default_parameters(key: str) -> dict[str, float]:
    return {p.name: p.default for p in distribution(key).parameters}


def clean_parameters(key: str, values: Mapping[str, float] | None = None) -> tuple[float, ...]:
    """The parameters of *key* in order: the values given (defaults for the missing ones), each checked."""
    dist = distribution(key)
    given = dict(values or {})
    unknown = set(given) - {p.name for p in dist.parameters}
    if unknown:
        raise ValueError(_("The {distribution} distribution has no parameter {names}").format(
            distribution=dist.label, names=", ".join(sorted(unknown))))
    ordered = tuple(p.check(given.get(p.name, p.default), dist.label) for p in dist.parameters)
    if dist.joint_check is not None:
        problem = dist.joint_check(ordered)
        if problem:
            raise ValueError(problem)
    return ordered


def theory(key: str, values: Mapping[str, float] | None = None) -> Any:
    """The scipy.stats frozen distribution a column of *key* should follow: .pdf/.pmf, .cdf, .ppf, ..."""
    return distribution(key).frozen(clean_parameters(key, values))


def theoretical_moments(key: str, values: Mapping[str, float] | None = None) -> dict[str, float]:
    """mean, variance, skewness, excess kurtosis; nan where the distribution has none (Cauchy, a Student t with
    few degrees of freedom)."""
    with np.errstate(all="ignore"):
        found = theory(key, values).stats(moments="mvsk")
    names = ("mean", "variance", "skewness", "kurtosis")
    return {name: (float(v) if np.isfinite(v) else float("nan")) for name, v in zip(names, found)}


# ----------------------------------------------------------------------
# The request
# ----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """One random column: its name, its distribution and the parameters (the missing ones take their default)."""

    distribution: str = "normal"
    parameters: Mapping[str, float] = field(default_factory=dict)
    #: None = the layout's default name.
    name: str | None = None


@dataclass(frozen=True, slots=True)
class Axis:
    """An evenly spaced column: X (and Y on a grid)."""

    start: float = 0.0
    stop: float = 1.0
    points: int = 100
    name: str | None = None
    spacing: str = SPACING_LINEAR


@dataclass(frozen=True, slots=True)
class Generated:
    """The table and what is needed to draw it again."""

    table: pd.DataFrame
    #: The seed actually used (the one asked for, or the one drawn when none was given).
    seed: int
    layout: str
    #: The specs with their final names, in column order of the random columns.
    columns: tuple[ColumnSpec, ...]


def _correlation_matrix(correlation: float | Sequence[Sequence[float]] | None, size: int) -> np.ndarray | None:
    """The correlation matrix asked for, or None for independent columns. A number is the one correlation
    between every pair."""
    if correlation is None:
        return None
    if np.isscalar(correlation):
        r = float(correlation)  # type: ignore[arg-type]
        if r == 0.0:
            return None
        matrix = np.full((size, size), r)
        np.fill_diagonal(matrix, 1.0)
    else:
        matrix = np.asarray(correlation, dtype=float)
        if matrix.shape != (size, size):
            raise ValueError(_("The correlation matrix must be {size} by {size}").format(size=size))
        if not np.allclose(matrix, matrix.T) or not np.allclose(np.diag(matrix), 1.0):
            raise ValueError(_("The correlation matrix must be symmetric with 1 on its diagonal"))
        if np.allclose(matrix, np.eye(size)):
            return None
    if np.any(np.abs(matrix[~np.eye(size, dtype=bool)]) >= 1.0):
        raise ValueError(_("A correlation must lie strictly between -1 and 1"))
    if np.linalg.eigvalsh(matrix).min() <= 1e-9:
        raise ValueError(_("The correlations are not possible together (the matrix is not positive definite)"))
    return matrix


def _draw_columns(rng: np.random.Generator, columns: Sequence[ColumnSpec], rows: int,
                  matrix: np.ndarray | None) -> list[np.ndarray]:
    """One array per column: each from its own distribution, tied by the copula when *matrix* is given."""
    cleaned = [(distribution(c.distribution), clean_parameters(c.distribution, c.parameters)) for c in columns]
    if matrix is None:
        return [dist.draw(rng, rows, p) for dist, p in cleaned]
    normal = rng.multivariate_normal(np.zeros(len(columns)), matrix, size=rows, method="cholesky")
    uniform = np.clip(stats.norm.cdf(normal), 1e-12, 1.0 - 1e-12)
    return [np.asarray(dist.frozen(p).ppf(uniform[:, i]), dtype=float) for i, (dist, p) in enumerate(cleaned)]


def _axis_values(axis: Axis) -> np.ndarray:
    if axis.points < 2:
        raise ValueError(_("An evenly spaced column needs at least 2 points"))
    return build_range(axis.start, axis.stop, axis.points, axis.spacing)


def _check_rows(rows: int) -> int:
    rows = int(rows)
    if rows < 1:
        raise ValueError(_("The table needs at least 1 row"))
    if rows > MAX_ROWS:
        raise ValueError(_("A table may have at most {limit:,} rows; {rows:,} were asked for").format(
            limit=MAX_ROWS, rows=rows))
    return rows


def _named(layout: str, columns: Sequence[ColumnSpec]) -> tuple[ColumnSpec, ...]:
    expected = RANDOM_COLUMNS[layout]
    if len(columns) != expected:
        raise ValueError(_("This layout has {expected} random column(s); {given} were given").format(
            expected=expected, given=len(columns)))
    names = DEFAULT_NAMES[layout]
    named = tuple(ColumnSpec(c.distribution, dict(c.parameters), c.name or names[i]) for i, c in enumerate(columns))
    if len({c.name for c in named}) != len(named):
        raise ValueError(_("The columns must have different names"))
    return named


def generate(
    layout: str,
    columns: Sequence[ColumnSpec],
    *,
    n: int = 1000,
    seed: int | None = None,
    correlation: float | Sequence[Sequence[float]] | None = None,
    x_axis: Axis | None = None,
    y_axis: Axis | None = None,
    function: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None,
    trend: tuple[float, float] = (0.0, 0.0),
) -> Generated:
    """Draw a table.

    *n* is the number of rows of the layouts X, XY and XYZ; the grid and the line take their rows from the axes.
    *correlation* (XY, XYZ): one number for every pair, or the full matrix. *function* (GRID): f(x, y) added to
    the random Z. *trend* (LINE): (a, b) of the line a + b X the random Y is added to.
    """
    if layout not in RANDOM_COLUMNS:
        raise ValueError(_("Unknown layout '{layout}'. Available: {names}").format(
            layout=layout, names=", ".join(RANDOM_COLUMNS)))
    named = _named(layout, columns)
    if seed is None:
        seed = int(np.random.SeedSequence().entropy % 2**32)  # type: ignore[operator]
    seed = int(seed)
    if seed < 0:
        raise ValueError(_("The seed must not be negative"))
    rng = np.random.default_rng(seed)

    if layout in (LAYOUT_X, LAYOUT_XY, LAYOUT_XYZ):
        rows = _check_rows(n)
        matrix = _correlation_matrix(correlation, len(named)) if len(named) > 1 else None
        arrays = _draw_columns(rng, named, rows, matrix)
        table = pd.DataFrame({c.name: a for c, a in zip(named, arrays)})
    elif layout == LAYOUT_LINE:
        axis = x_axis or Axis(name="X")
        x = _axis_values(axis)
        _check_rows(x.size)
        noise = _draw_columns(rng, named, x.size, None)[0]
        table = pd.DataFrame({axis.name or "X": x, named[0].name: trend[0] + trend[1] * x + noise})
    else:
        x_axis = x_axis or Axis(name="X")
        y_axis = y_axis or Axis(name="Y")
        x_values, y_values = _axis_values(x_axis), _axis_values(y_axis)
        _check_rows(x_values.size * y_values.size)
        x_grid, y_grid = np.meshgrid(x_values, y_values)
        x_flat, y_flat = x_grid.ravel(), y_grid.ravel()
        z = _draw_columns(rng, named, x_flat.size, None)[0]
        if function is not None:
            base = np.asarray(function(x_flat, y_flat), dtype=float)
            if base.shape != x_flat.shape:
                raise ValueError(_("The function returned {got} value(s) for {wanted} point(s)").format(
                    got=base.size, wanted=x_flat.size))
            z = z + base
        x_name, y_name = x_axis.name or "X", y_axis.name or "Y"
        if len({x_name, y_name, named[0].name}) != 3:
            raise ValueError(_("The columns must have different names"))
        table = pd.DataFrame({x_name: x_flat, y_name: y_flat, named[0].name: z})
    return Generated(table, seed, layout, named)
