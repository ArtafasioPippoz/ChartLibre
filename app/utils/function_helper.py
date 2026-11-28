"""The function helper of the SymPy workpad: from a formula, the analyses and charts that make sense for it.

Give it ``sin(x)*exp(-x/5)`` and it lists what can be asked of such a function (derivatives, integral, limits,
roots, critical points, series...) and the charts worth drawing (the function, with its derivative, against its
Taylor polynomials, its tangent...). Each suggestion is a few workpad commands: the helper writes them, the
user reads, edits and runs them - nothing is hidden in a button.

No Qt here: ``suggestions()`` is plain functions over a formula, so it is tested without a window.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from app.utils.logger import applogger

#: What a suggestion is: something to compute and read, or something to draw.
ANALYSIS, CHART = "analysis", "chart"

_UNSAFE_TEXT = re.compile(r"__|\b(import|eval|exec|compile|open|getattr|globals|locals|lambda)\b")


class BadFormula(ValueError):
    """The text is not a formula the helper can read; the message says why."""


@dataclass(frozen=True)
class Suggestion:
    """One thing the helper offers: *code* is the workpad commands that do it."""

    kind: str  # ANALYSIS or CHART
    key: str
    label: str
    tip: str
    code: str


@dataclass(frozen=True)
class Formula:
    """A parsed formula: its text, the symbols in it and what kind of function it is."""

    text: str
    expression: object  # a sympy expression
    symbols: tuple[str, ...]  # every free symbol, sorted
    polynomial: bool
    rational: bool
    periodic: bool  # has sin, cos or tan of the variable


def parse(text: str) -> Formula:
    """Read *text* as a SymPy expression; BadFormula when it is empty, unsafe or not a formula."""
    text = (text or "").strip()
    if not text:
        raise BadFormula("Type a formula, e.g. sin(x)*exp(-x/5)")
    if _UNSAFE_TEXT.search(text):
        raise BadFormula("Only a formula: no imports, lambdas or calls to Python itself")
    from sympy.parsing.sympy_parser import (
        convert_xor,
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )

    transformations = standard_transformations + (implicit_multiplication_application, convert_xor)
    try:
        expression = parse_expr(text, transformations=transformations)
    except Exception as error:  # SyntaxError, TypeError, TokenError...
        failure = BadFormula(f"Cannot read it as a formula ({type(error).__name__})")
        applogger.warning("%s", failure, exc_info=error)
        raise failure from error
    if not hasattr(expression, "free_symbols"):
        raise BadFormula("Not a formula")
    import sympy

    symbols = sorted(str(symbol) for symbol in expression.free_symbols)
    variable = sympy.Symbol(symbols[0]) if symbols else None
    polynomial = bool(variable is not None and expression.is_polynomial(variable))
    rational = bool(variable is not None and expression.is_rational_function(variable))
    periodic = bool(expression.has(sympy.sin, sympy.cos, sympy.tan))
    return Formula(text, expression, tuple(symbols), polynomial, rational, periodic)


def default_variable(formula: Formula) -> str:
    """x when the formula has it, else t, else the first symbol, else x."""
    for name in ("x", "t"):
        if name in formula.symbols:
            return name
    return formula.symbols[0] if formula.symbols else "x"


def suggestions(formula: Formula, variable: str, low: float = -10.0, high: float = 10.0,
                point: float = 0.0, values: dict[str, float] | None = None) -> list[Suggestion]:
    """The analyses and charts for *formula* in *variable*, over [low, high], with *point* for the local ones.

    *values* gives the other symbols a number for the charts (a missing one is 1).
    """
    import sympy

    var = sympy.Symbol(variable)
    others = [name for name in formula.symbols if name != variable]
    periodic = bool(formula.expression.has(var) and formula.periodic)
    header = _header(formula, variable, others)
    lo, hi, p = _num(low), _num(high), _num(point)
    out: list[Suggestion] = []

    def analysis(key: str, label: str, tip: str, *lines: str) -> None:
        out.append(Suggestion(ANALYSIS, key, label, tip, "\n".join(lines)))

    def chart(key: str, label: str, tip: str, *lines: str) -> None:
        out.append(Suggestion(CHART, key, label, tip, "\n".join(lines)))

    # --- analyses ---------------------------------------------------------------
    analysis("simplify", "Simplify", "The formula in its shortest form", "print(simplify(f))")
    analysis("domain", "Singular points", "Where the function breaks: not defined or not smooth",
             f"print(singularities(f, {variable}))")
    analysis("parity", "Even or odd", "Whether f(-x) equals f(x) or -f(x)",
             f"print('even' if simplify(f.subs({variable}, -{variable}) - f) == 0 else "
             f"'odd' if simplify(f.subs({variable}, -{variable}) + f) == 0 else 'neither')")
    if periodic:
        analysis("period", "Period", "The smallest period, if it has one", f"print(periodicity(f, {variable}))")
    analysis("derivative", "Derivative", "f'", f"print(diff(f, {variable}))")
    analysis("derivative2", "Second derivative", "f'' - the curvature", f"print(diff(f, {variable}, 2))")
    analysis("critical", "Critical points", "Where f' is zero: maxima, minima, flat spots",
             f"print(solve(diff(f, {variable}), {variable}))")
    analysis("inflection", "Inflection points", "Where f'' is zero: the curve changes its bend",
             f"print(solve(diff(f, {variable}, 2), {variable}))")
    analysis("roots", "Roots", "Where f is zero", f"print(solve(f, {variable}))")
    if not formula.polynomial:
        analysis("roots_numeric", f"A root near {p}", "A numerical root, starting from the point",
                 f"print(nsolve(f, {variable}, {p}))")
    analysis("integral", "Antiderivative", "The indefinite integral", f"print(integrate(f, {variable}))")
    analysis("definite", f"Area from {lo} to {hi}", "The definite integral, exact then numerical",
             f"area = Integral(f, ({variable}, {lo}, {hi}))", "print(area.doit(), area.evalf())")
    analysis("limit_point", f"Limit at {p}", "From both sides, and each side alone",
             f"print(limit(f, {variable}, {p}), limit(f, {variable}, {p}, '+'), limit(f, {variable}, {p}, '-'))")
    analysis("limit_inf", "Limits at infinity", "What f tends to far left and far right",
             f"print(limit(f, {variable}, -oo), limit(f, {variable}, oo))")
    analysis("series", f"Taylor series around {p}", "The first terms, as a polynomial",
             f"print(series(f, {variable}, {p}, 6))")
    analysis("tangent", f"Tangent at {p}", "The line touching the curve at the point",
             f"print(f.subs({variable}, {p}) + diff(f, {variable}).subs({variable}, {p}) * ({variable} - {p}))")
    if formula.rational and not formula.polynomial:
        analysis("asymptotes", "Vertical asymptotes", "Where the denominator vanishes",
                 f"print(solve(denom(together(f)), {variable}))")
        analysis("apart", "Partial fractions", "Split into simple fractions", f"print(apart(f, {variable}))")
    if formula.polynomial and not others:
        analysis("factor", "Factor", "Break into factors", "print(factor(f))")
        analysis("degree", "Degree and coefficients", "The polynomial's shape",
                 f"print(degree(f, {variable}), Poly(f, {variable}).all_coeffs())")
        analysis("roots_poly", "Numerical roots", "All the roots, complex ones too",
                 f"print(Poly(f, {variable}).nroots())")
    if periodic:
        analysis("fourier", "Fourier series", "A sum of sines and cosines, first terms (can take a while)",
                 f"print(fourier_series(f, ({variable}, -pi, pi)).truncate(4))")
    s = sympy.Symbol("s")
    if str(s) not in formula.symbols:
        analysis("laplace", "Laplace transform", "From the variable to s",
                 "s = Symbol('s')", f"print(laplace_transform(f, {variable}, s, noconds=True))")
    if others:
        names = ", ".join(others)
        analysis("partials", "Partial derivatives", f"One for each of {names}",
                 *(f"print('d/d{name}:', diff(f, {name}))" for name in [variable, *others]))
        analysis("gradient", "Gradient and Hessian", "First and second derivatives together",
                 f"v = [{', '.join([variable, *others])}]",
                 "print([diff(f, name) for name in v])", "print(hessian(f, v))")

    # --- charts -----------------------------------------------------------------
    grid = [header_line for header_line in _grid(formula, variable, lo, hi, values)]
    chart("plot", "The function", "f over the interval", *grid, *_lines("f", "ys"))
    chart("plot_d", "With its derivative", "f and f' on the same axes", *grid,
          f"g1 = lambdify({variable}, diff(g, {variable}), 'numpy')",
          "d1 = np.asarray(g1(xs), dtype=float) * np.ones_like(xs)",
          *_lines("f", "ys", "derivative", "d1"))
    chart("plot_d2", "With its first two derivatives", "f, f' and f''", *grid,
          f"d1 = np.asarray(lambdify({variable}, diff(g, {variable}), 'numpy')(xs), dtype=float) * np.ones_like(xs)",
          f"d2 = np.asarray(lambdify({variable}, diff(g, {variable}, 2), 'numpy')(xs), dtype=float) * np.ones_like(xs)",
          *_lines("f", "ys", "derivative", "d1", "second derivative", "d2"))
    chart("plot_F", "With its antiderivative", "f and an antiderivative F, F(" + str(p) + ") = 0", *grid,
          f"F = integrate(g, {variable})",
          f"F = F - F.subs({variable}, {p})",
          f"Fs = np.asarray(lambdify({variable}, F, 'numpy')(xs), dtype=float) * np.ones_like(xs)",
          *_lines("f", "ys", "antiderivative", "Fs"))
    chart("plot_taylor", f"Against its Taylor polynomials around {p}", "Orders 1, 3 and 5 (or the ones that exist)",
          *grid,
          *(f"t{n} = np.asarray(lambdify({variable}, series(g, {variable}, {p}, {n + 1}).removeO(), 'numpy')(xs),"
            f" dtype=float) * np.ones_like(xs)" for n in (1, 3, 5)),
          *_lines("f", "ys", "order 1", "t1", "order 3", "t3", "order 5", "t5"))
    chart("plot_tangent", f"With its tangent at {p}", "The curve and the line touching it", *grid,
          f"line = g.subs({variable}, {p}) + diff(g, {variable}).subs({variable}, {p}) * ({variable} - {p})",
          f"tl = np.asarray(lambdify({variable}, line, 'numpy')(xs), dtype=float) * np.ones_like(xs)",
          *_lines("f", "ys", "tangent", "tl"))
    chart("table", "Values as a table", "A table in the project: then fit it, differentiate it, find peaks...",
          *grid, f"save('Function values', {{'{variable}': xs, 'y': ys}})")
    return out


def script(formula: Formula, variable: str, chosen: list[Suggestion], low: float = -10.0, high: float = 10.0,
           point: float = 0.0, values: dict[str, float] | None = None) -> str:
    """The commands for the *chosen* suggestions: the formula once, then each one under a comment."""
    if not chosen:
        return ""
    others = [name for name in formula.symbols if name != variable]
    lines = [_header(formula, variable, others)]
    seen_grid = False
    for item in chosen:
        lines.append(f"# {item.label}")
        for line in item.code.split("\n"):
            # The grid (xs, g, ys) is written once however many charts want it.
            if line in _GRID_MARKERS(formula, variable, low, high, values):
                if seen_grid:
                    continue
            lines.append(line)
        if item.kind == CHART:
            seen_grid = True
    return "\n".join(lines)


# --- helpers ---------------------------------------------------------------------


def _num(value: float) -> str:
    """A number as short text: 3, not 3.0."""
    value = float(value)
    return str(int(value)) if value == int(value) else repr(value)


def _header(formula: Formula, variable: str, others: list[str]) -> str:
    names = [variable, *others]
    declared = "\n".join(f"{name} = Symbol('{name}')" for name in names)
    return f"{declared}\nf = {_python(formula.text)}"


def _python(text: str) -> str:
    """The formula as Python: ^ is a power, and 2x a product, as the helper read it."""
    from sympy.printing.str import sstr

    return sstr(parse(text).expression)


def _grid(formula: Formula, variable: str, lo: str, hi: str, values: dict[str, float] | None) -> list[str]:
    others = [name for name in formula.symbols if name != variable]
    chosen = {name: (values or {}).get(name, 1.0) for name in others}
    substitute = ("g = f.subs({" + ", ".join(f"{name}: {_num(value)}" for name, value in chosen.items()) + "})"
                  if chosen else "g = f")
    return [
        substitute,
        f"xs = np.linspace({lo}, {hi}, 500)",
        f"ys = np.asarray(lambdify({variable}, g, 'numpy')(xs), dtype=float) * np.ones_like(xs)",
    ]


def _GRID_MARKERS(formula: Formula, variable: str, low: float, high: float,
                  values: dict[str, float] | None) -> set[str]:
    return set(_grid(formula, variable, _num(low), _num(high), values))


def _lines(*pairs: str) -> list[str]:
    """plot('Scatter Plot', x=xs, y={label: values, ...}) from label, values-name, label, values-name..."""
    body = ", ".join(f"'{label}': {name}" for label, name in zip(pairs[::2], pairs[1::2], strict=True))
    return [f"plot('Scatter Plot', x=xs, y={{{body}}})"]
