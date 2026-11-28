"""The equation helper of the SymPy workpad: from equations, the ways to solve and draw them as workpad commands.

Same shape as ``function_helper`` (parse, default_variable, suggestions, script), so one dialog serves both.

What is typed, one item per line or separated by ``;``:

    x^3 - 2x = 1              an equation (``=``); without one, the expression is set equal to zero
    x + y = 3; x - y = 1      a system
    x^2 - 4 > 0               an inequality
    y' + 2y = sin(x)          an ordinary differential equation (y', y'' ...); y is the unknown function
    y(0) = 1                  an initial condition of the equation above

No Qt here: plain functions, tested without a window.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.utils.function_helper import ANALYSIS, CHART, BadFormula, Suggestion, _num
from app.utils.logger import applogger

_UNSAFE_TEXT = re.compile(r"__|\b(import|eval|exec|compile|open|getattr|globals|locals|lambda)\b")
_ORDER = re.compile(r"<=|>=|<|>")
_DERIVATIVE = re.compile(r"\b([A-Za-z]\w*)('+)")
_CONDITION = re.compile(r"^\s*([A-Za-z]\w*)('*)\(\s*([-+0-9.eE]+)\s*\)\s*=\s*(.+)$")


@dataclass(frozen=True)
class Equations:
    """Parsed equations: *kind* is algebraic, system, inequality or ode."""

    text: str
    kind: str
    parts: tuple[str, ...]  # each equation as the text of a Python relation, e.g. "Eq(x**2, 4)"
    symbols: tuple[str, ...]  # unknowns and parameters, sorted
    function: str  # the unknown function of an ode, else ""
    conditions: tuple[str, ...]  # initial conditions as "y(0): 1"
    linear: bool
    polynomial: bool  # a single polynomial equation in one symbol


def _split(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;\n]", text or "") if part.strip()]


def parse(text: str) -> Equations:
    """Read *text*; BadFormula when it is empty, unsafe or not equations."""
    pieces = _split(text)
    if not pieces:
        raise BadFormula("Type an equation, e.g. x^2 - 3x + 2 = 0")
    if _UNSAFE_TEXT.search(text):
        raise BadFormula("Only equations: no imports, lambdas or calls to Python itself")
    import sympy
    from sympy.parsing.sympy_parser import (
        convert_xor,
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )

    transformations = standard_transformations + (implicit_multiplication_application, convert_xor)
    ode = any(_DERIVATIVE.search(piece) and not _CONDITION.match(piece) for piece in pieces)
    independent = "x"
    unknown = ""
    if ode:
        unknown = _DERIVATIVE.search(next(p for p in pieces if _DERIVATIVE.search(p))).group(1)
        names = set(re.findall(r"\b[A-Za-z]\w*\b", text)) - {unknown}
        independent = "x" if "x" in names or "t" not in names else "t"
    var = sympy.Symbol(independent)
    function = sympy.Function(unknown) if unknown else None

    def read(source: str) -> object:
        source = source.strip()
        if function is not None:
            source = _DERIVATIVE.sub(
                lambda m: f"Derivative({m.group(1)}({independent}), {independent}, {len(m.group(2))})"
                if m.group(1) == unknown else m.group(0), source)
            source = re.sub(rf"(?<![A-Za-z_]){unknown}(?![A-Za-z_0-9]|\s*\()", f"{unknown}({independent})", source)
        try:
            return parse_expr(source, transformations=transformations,
                              local_dict={unknown: function} if function is not None else None)
        except Exception as error:
            failure = BadFormula(f"Cannot read '{source}' ({type(error).__name__})")
            applogger.warning("%s", failure, exc_info=error)
            raise failure from error

    relations: list[object] = []
    conditions: list[str] = []
    kind = "algebraic"
    for piece in pieces:
        condition = _CONDITION.match(piece)
        if ode and condition and condition.group(1) == unknown:
            value = read(condition.group(4))
            order = len(condition.group(2))
            at = condition.group(3)
            left = f"{unknown}({at})" if not order else f"Subs(Derivative({unknown}({independent}), {independent}, {order}), {independent}, {at})"
            conditions.append(f"{left}: {sympy.sstr(value)}")
            continue
        if _ORDER.search(piece):
            kind = "inequality"
            operator = _ORDER.search(piece).group(0)
            left, right = (read(side) for side in piece.split(operator, 1))
            relations.append({"<": sympy.Lt, "<=": sympy.Le, ">": sympy.Gt, ">=": sympy.Ge}[operator](left, right))
        elif "=" in piece.replace("==", ""):
            left, right = (read(side) for side in piece.replace("==", "=").split("=", 1))
            relations.append(sympy.Eq(left, right))
        else:
            relations.append(sympy.Eq(read(piece), 0))
    if not relations:
        raise BadFormula("Type the equation too, not only its initial conditions")
    if not all(isinstance(relation, sympy.core.relational.Relational) for relation in relations):
        raise BadFormula("An equation with no unknown in it (always true or false)")
    if ode:
        kind = "ode"
    elif kind != "inequality" and len(relations) > 1:
        kind = "system"
    symbols = sorted({str(symbol) for relation in relations for symbol in relation.free_symbols})
    if ode and independent not in symbols:
        symbols.append(independent)
        symbols.sort()
    expressions = [relation.lhs - relation.rhs for relation in relations if isinstance(relation, sympy.Eq)]
    unknowns = [sympy.Symbol(name) for name in symbols]
    linear = bool(expressions) and not ode and all(
        expression.is_polynomial(*unknowns) and sympy.Poly(expression, *unknowns).total_degree() <= 1
        for expression in expressions) if unknowns else False
    polynomial = (kind == "algebraic" and len(symbols) == 1 and bool(expressions)
                  and expressions[0].is_polynomial(unknowns[0]))
    parts = tuple(sympy.sstr(relation) if not isinstance(relation, sympy.Eq)
                  else f"Eq({sympy.sstr(relation.lhs)}, {sympy.sstr(relation.rhs)})" for relation in relations)
    return Equations(text, kind, parts, tuple(symbols), unknown, tuple(conditions), linear, polynomial)


def default_variable(equations: Equations) -> str:
    """The unknown to solve for: x, else t, else the first symbol (the independent variable of an ode)."""
    for name in ("x", "t"):
        if name in equations.symbols:
            return name
    return equations.symbols[0] if equations.symbols else "x"


def _header(eq: Equations) -> str:
    lines = [f"{name} = Symbol('{name}')" for name in eq.symbols]
    if eq.function:
        lines.append(f"{eq.function} = Function('{eq.function}')")
    if eq.kind == "ode":
        lines.append(f"ode = {eq.parts[0]}")
        if eq.conditions:
            lines.append("ics = {" + ", ".join(eq.conditions) + "}")
    elif len(eq.parts) == 1:
        lines.append(f"eq = {eq.parts[0]}")
    else:
        lines.append("eqs = [" + ", ".join(eq.parts) + "]")
    return "\n".join(lines)


def suggestions(eq: Equations, variable: str, low: float = -10.0, high: float = 10.0,
                point: float = 0.0, values: dict[str, float] | None = None) -> list[Suggestion]:
    """What can be done with *eq*, solving for *variable*; charts over [low, high]; *point* starts numerics."""
    lo, hi, p = _num(low), _num(high), _num(point)
    others = [name for name in eq.symbols if name != variable]
    out: list[Suggestion] = []

    def analysis(key: str, label: str, tip: str, *lines: str) -> None:
        out.append(Suggestion(ANALYSIS, key, label, tip, "\n".join(lines)))

    def chart(key: str, label: str, tip: str, *lines: str) -> None:
        out.append(Suggestion(CHART, key, label, tip, "\n".join(lines)))

    fixed = {name: (values or {}).get(name, 1.0) for name in others}
    subs = "{" + ", ".join(f"{name}: {_num(value)}" for name, value in fixed.items()) + "}"
    xs = f"xs = np.linspace({lo}, {hi}, 500)"

    def curve(expression: str) -> str:
        return (f"np.asarray(lambdify({variable}, ({expression}).subs({subs}), 'numpy')(xs), dtype=float)"
                f" * np.ones_like(xs)")

    if eq.kind == "algebraic":
        analysis("solve", f"Solve for {variable}", "Exact solutions", f"print(solve(eq, {variable}))")
        analysis("solveset", "Real solutions", "As a set, over the reals", f"print(solveset(eq, {variable}, Reals))")
        analysis("numeric", f"Numerical solution near {p}", "Newton from the point",
                 f"print(nsolve(eq.lhs - eq.rhs, {variable}, {p}))")
        for name in others:
            analysis(f"for_{name}", f"Solve for {name}", f"{name} as a function of the others",
                     f"print(solve(eq, {name}))")
        if eq.polynomial:
            analysis("factor", "Factor", "lhs - rhs in factors", "print(factor(eq.lhs - eq.rhs))")
            analysis("count", "How many real roots", "Counted with multiplicity",
                     f"print(len(real_roots(Poly(eq.lhs - eq.rhs, {variable}))))")
        chart("sides", "Both sides", "Where the curves cross, the equation holds", xs,
              f"plot('Scatter Plot', x=xs, y={{'left': {curve('eq.lhs')}, 'right': {curve('eq.rhs')}}})")
        chart("difference", "lhs minus rhs", "Where it crosses zero, the equation holds", xs,
              f"plot('Scatter Plot', x=xs, y={{'lhs - rhs': {curve('eq.lhs - eq.rhs')}}})")
    elif eq.kind == "system":
        names = ", ".join(eq.symbols)
        analysis("solve", "Solve the system", "Exact solutions", f"print(solve(eqs, [{names}], dict=True))")
        if eq.linear:
            analysis("matrix", "Matrix form", "A x = b, with its determinant and rank",
                     f"A, b = linear_eq_to_matrix([e.lhs - e.rhs for e in eqs], [{names}])",
                     "print(A, b)", "print(A.det() if A.is_square else None, A.rank())")
            analysis("linsolve", "Linear solution set", "Unique, none or a family",
                     f"print(linsolve(eqs, [{names}]))")
        analysis("numeric", "Numerical solution", "Newton from the point, every unknown at it",
                 f"print(nsolve([e.lhs - e.rhs for e in eqs], [{names}], [{', '.join([p] * len(eq.symbols))}]))")
    elif eq.kind == "inequality":
        analysis("solve", f"Solve for {variable}", "The set where it holds",
                 f"print(solve_univariate_inequality({eq.parts[0]}, {variable}, relational=False))")
        analysis("reduce", "As conditions", "The same, written as relations",
                 f"print(reduce_inequalities([{eq.parts[0]}], [{variable}]))")
        chart("sides", "Both sides", "Where the left curve is above or below the right one", xs,
              f"ineq = {eq.parts[0]}",
              f"plot('Scatter Plot', x=xs, y={{'left': {curve('ineq.lhs')}, 'right': {curve('ineq.rhs')}}})")
    else:  # ode
        f = eq.function
        analysis("classify", "Kind of equation", "What SymPy recognises it as", "print(classify_ode(ode))")
        analysis("general", "General solution", "With constants C1, C2...", "print(dsolve(ode))")
        if eq.conditions:
            analysis("particular", "Solution with the initial conditions", "The constants fixed",
                     "print(dsolve(ode, ics=ics))")
        analysis("check", "Check the solution", "Put it back: (True, 0) when right",
                 "print(checkodesol(ode, dsolve(ode)))")
        pick = "dsolve(ode, ics=ics)" if eq.conditions else "dsolve(ode)"
        chart("solution", "The solution" if eq.conditions else "Solutions for some constants",
              "Drawn over the interval", xs, f"sol = {pick}",
              *(("curve = sol.rhs", f"ys = np.asarray(lambdify({variable}, curve, 'numpy')(xs), dtype=float)"
                 " * np.ones_like(xs)", f"plot('Scatter Plot', x=xs, y={{'{f}': ys}})") if eq.conditions else
                ("consts = sorted(sol.rhs.free_symbols - {" + variable + "}, key=str)",
                 "curves = {}",
                 "for k in (-2, -1, 1, 2):",
                 "    expr = sol.rhs.subs({c: k for c in consts})",
                 f"    curves[f'C={{k}}'] = np.asarray(lambdify({variable}, expr, 'numpy')(xs), dtype=float)"
                 " * np.ones_like(xs)",
                 "plot('Scatter Plot', x=xs, y=curves)")))
    return out


def script(eq: Equations, variable: str, chosen: list[Suggestion], low: float = -10.0, high: float = 10.0,
           point: float = 0.0, values: dict[str, float] | None = None) -> str:
    """The commands for the *chosen* suggestions: the equations once, then each under a comment."""
    if not chosen:
        return ""
    lines = [_header(eq)]
    grid_done = False
    for item in chosen:
        lines.append(f"# {item.label}")
        for line in item.code.split("\n"):
            if line.startswith("xs = np.linspace") and grid_done:
                continue
            lines.append(line)
        if item.kind == CHART:
            grid_done = True
    return "\n".join(lines)
