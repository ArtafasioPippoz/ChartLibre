"""Complex functions on the plane: a safe evaluator for f(z) and the colours of domain colouring.

Domain colouring paints every point z of the plane with the value f(z): the hue is the argument
(red at 0, through yellow, green, cyan and blue, back to red at 2 pi), the lightness the modulus.
A zero is where all the hues meet going round one way, a pole is where they meet going round the
other way, and the number of turns is the order.

The expression is typed by the user, so it is parsed, not trusted: only arithmetic, numbers,
``z`` (and ``i``/``j`` for the imaginary unit), a few constants and the numpy functions named in
``FUNCTIONS`` pass. Anything else - attributes, subscripts, calls of other names - is refused
with a message naming it.
"""
from __future__ import annotations

import ast
import math
import re
from collections.abc import Callable

import numpy as np
from matplotlib.colors import hsv_to_rgb
from app.utils.logger import applogger

#: The functions an expression may call, by the names it may use.
FUNCTIONS: dict[str, Callable[..., np.ndarray]] = {
    "exp": np.exp, "log": np.log, "sqrt": np.sqrt,
    "sin": np.sin, "cos": np.cos, "tan": np.tan,
    "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh,
    "arcsin": np.arcsin, "arccos": np.arccos, "arctan": np.arctan,
    "asin": np.arcsin, "acos": np.arccos, "atan": np.arctan,
    "abs": np.abs, "conj": np.conj, "real": np.real, "imag": np.imag, "angle": np.angle,
}

#: The constants an expression may name.
CONSTANTS: dict[str, complex | float] = {"pi": math.pi, "e": math.e, "i": 1j, "j": 1j}

#: How the lightness follows the modulus.
MODULUS_SMOOTH = "smooth"   # dark at 0, white at infinity, |f| = 1 at full colour
MODULUS_RINGS = "rings"     # smooth, with a ring at every doubling of |f|
MODULUS_NONE = "none"       # the phase alone, at full colour
MODULUS_MODES: tuple[str, ...] = (MODULUS_SMOOTH, MODULUS_RINGS, MODULUS_NONE)

_ALLOWED_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Load,
                  ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd)


def compile_function(expression: str) -> Callable[[np.ndarray], np.ndarray]:
    """Return f as a callable of a complex array, or raise ValueError naming what is not allowed."""
    # "2i" as well as Python's "2j"; "^" as well as "**".
    text = re.sub(r"(?<![\w.])(\d+\.?\d*(?:[eE][-+]?\d+)?)i\b", r"\1j", expression.strip()).replace("^", "**")
    if not text:
        raise ValueError("The function is empty.")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as error:
        failure = ValueError(f"The function cannot be read: {error.msg}.")
        applogger.warning("%s", failure)
        raise failure from None
    for node in ast.walk(tree):
        if isinstance(node, _ALLOWED_NODES):
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, complex)) \
                and not isinstance(node.value, bool):
            continue
        if isinstance(node, ast.Call):
            if not (isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS) or node.keywords:
                raise ValueError(f"'{ast.unparse(node.func)}' is not a function that can be used here.")
            continue
        if isinstance(node, ast.Name):
            if node.id == "z" or node.id in CONSTANTS or node.id in FUNCTIONS:
                continue
            raise ValueError(f"'{node.id}' is not known: use z, pi, e, i and the listed functions.")
        raise ValueError(f"'{ast.unparse(node)}' is not allowed in a function of z.")
    code = compile(tree, "<f(z)>", "eval")
    names = {**FUNCTIONS, **CONSTANTS, "__builtins__": {}}

    def f(z: np.ndarray) -> np.ndarray:
        with np.errstate(all="ignore"):
            value = eval(code, names, {"z": z})  # noqa: S307 - the tree was checked above
        return np.broadcast_to(np.asarray(value, dtype=complex), np.shape(z))

    return f


def evaluate_on_grid(f: Callable[[np.ndarray], np.ndarray], x_range: tuple[float, float],
                     y_range: tuple[float, float], resolution: int
                     ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return X, Y and f(X + iY) on a grid *resolution* points wide, as tall as the ranges' ratio."""
    width = max(abs(x_range[1] - x_range[0]), 1e-300)
    height = max(abs(y_range[1] - y_range[0]), 1e-300)
    nx = max(int(resolution), 2)
    ny = int(min(max(round(nx * height / width), 2), 4 * nx))
    X, Y = np.meshgrid(np.linspace(*x_range, nx), np.linspace(*y_range, ny))
    return X, Y, f(X + 1j * Y)


def domain_colours(w: np.ndarray, modulus: str = MODULUS_SMOOTH, phase_lines: int = 0) -> np.ndarray:
    """Return the RGB image (shape w.shape + (3,)) of the complex values *w*.

    Hue is arg w, so 0 is red and 2 pi / 3 green. *modulus* chooses the lightness (MODULUS_MODES);
    *phase_lines* > 0 darkens that many evenly spaced rays of constant argument. Points where w is
    not finite are white when the modulus is infinite (a pole) and grey otherwise.
    """
    if modulus not in MODULUS_MODES:
        raise ValueError(f"Unknown modulus mode '{modulus}'.")
    w = np.asarray(w, dtype=complex)
    with np.errstate(all="ignore"):
        hue = np.mod(np.angle(w) / (2 * np.pi), 1.0)
        r = np.abs(w)
        saturation = np.ones_like(r)
        value = np.ones_like(r)
        if modulus != MODULUS_NONE:
            # 2/pi arctan maps [0, inf) onto [0, 1): black at 0, full colour at 1, white at infinity.
            lightness = (2 / np.pi) * np.arctan(r)
            saturation = np.clip(2 * (1 - lightness), 0, 1)
            value = np.clip(2 * lightness, 0, 1)
            if modulus == MODULUS_RINGS:
                fraction = np.mod(np.log2(np.where(r > 0, r, np.nan)), 1.0)
                value = value * (0.75 + 0.25 * np.nan_to_num(fraction, nan=1.0))
        if phase_lines > 0:
            ray = np.mod(hue * phase_lines, 1.0)
            value = value * np.where(np.minimum(ray, 1 - ray) < 0.02, 0.55, 1.0)
    hsv = np.stack([np.nan_to_num(hue), np.nan_to_num(saturation), np.nan_to_num(value)], axis=-1)
    rgb = hsv_to_rgb(np.clip(hsv, 0, 1))
    bad = ~np.isfinite(w)
    rgb[bad & np.isinf(r)] = 1.0
    rgb[bad & ~np.isinf(r)] = 0.5
    return rgb
