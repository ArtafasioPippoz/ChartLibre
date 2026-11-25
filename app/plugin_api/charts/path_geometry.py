"""The geometry of a drawn path: straight corners and smooth (Bezier) nodes, as Matplotlib's own ``Path``.

A path is stored as text, ``"x,y; x,y,hx,hy; ..."``. A node written with two numbers is a corner; one written
with four is a *smooth* node whose outgoing handle sits at (hx, hy) - the incoming handle is its mirror image,
as with the pen tool of a vector editor. Files written before curves existed hold two numbers per node, and read
back exactly as they were (``BaseAxisRenderer.parse_path_points`` still takes the first two of each node).

The curve itself is Matplotlib's: ``Path`` with ``CURVE4`` segments, drawn by a ``PathPatch``.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
from matplotlib.path import Path

#: A node: x, y and, for a smooth node, its outgoing handle (hx, hy); None, None for a corner.
Node = tuple[float, float, float | None, float | None]

#: The handle length, as a fraction of the radius, that makes four Bezier arcs a circle (4/3 * (sqrt 2 - 1)).
CIRCLE_HANDLE: float = 0.5522847498307936


def parse_nodes(value: Any) -> list[Node]:
    """The nodes of a stored path - "x,y; x,y,hx,hy" or a list of lists; what is not numbers is left out."""
    if isinstance(value, str):
        rows: list[Any] = [part.replace(",", " ").split() for part in value.replace("\n", ";").split(";")]
    elif isinstance(value, (list, tuple)):
        rows = list(value)
    else:
        return []
    nodes: list[Node] = []
    for row in rows:
        try:
            numbers = [float(item) for item in row]
        except (TypeError, ValueError):
            continue
        if len(numbers) < 2 or not all(math.isfinite(number) for number in numbers[:2]):
            continue
        handle = (numbers[2], numbers[3]) if len(numbers) >= 4 and math.isfinite(numbers[2]) and math.isfinite(numbers[3]) else (None, None)
        nodes.append((numbers[0], numbers[1], handle[0], handle[1]))
    return nodes


def format_nodes(nodes: Iterable[Node]) -> str:
    """The stored text of *nodes*: corners as "x,y", smooth nodes as "x,y,hx,hy"."""
    parts = []
    for x, y, hx, hy in nodes:
        parts.append(f"{x:.6g},{y:.6g}" if hx is None or hy is None else f"{x:.6g},{y:.6g},{hx:.6g},{hy:.6g}")
    return "; ".join(parts)


def has_curves(nodes: Iterable[Node]) -> bool:
    """True if any node is smooth."""
    return any(hx is not None and hy is not None for _x, _y, hx, hy in nodes)


def _controls(start: Node, end: Node) -> tuple[tuple[float, float], tuple[float, float]]:
    """The two control points of the segment from *start* to *end*: start's outgoing handle, end's incoming one."""
    first = (start[2], start[3]) if start[2] is not None and start[3] is not None else (start[0], start[1])
    if end[2] is not None and end[3] is not None:
        second = (2.0 * end[0] - end[2], 2.0 * end[1] - end[3])
    else:
        second = (end[0], end[1])
    return (float(first[0]), float(first[1])), (float(second[0]), float(second[1]))


def build_path(nodes: list[Node], closed: bool) -> Path:
    """The Matplotlib ``Path`` through *nodes*: a line between two corners, a cubic Bezier when either end is smooth.

    A closed path joins the last node to the first the same way and ends with ``CLOSEPOLY``.
    """
    if not nodes:
        return Path(np.zeros((0, 2)))
    vertices: list[tuple[float, float]] = [(nodes[0][0], nodes[0][1])]
    codes: list[int] = [Path.MOVETO]
    pairs = list(zip(nodes, nodes[1:]))
    if closed and len(nodes) > 2:
        pairs.append((nodes[-1], nodes[0]))
    for start, end in pairs:
        smooth = (start[2] is not None and start[3] is not None) or (end[2] is not None and end[3] is not None)
        if smooth:
            first, second = _controls(start, end)
            vertices += [first, second, (end[0], end[1])]
            codes += [Path.CURVE4, Path.CURVE4, Path.CURVE4]
        else:
            vertices.append((end[0], end[1]))
            codes.append(Path.LINETO)
    if closed and len(nodes) > 2:
        vertices.append((nodes[0][0], nodes[0][1]))
        codes.append(Path.CLOSEPOLY)
    return Path(np.asarray(vertices, dtype=float), codes)


def rectangle_nodes(x0: float, y0: float, x1: float, y1: float) -> list[Node]:
    """The four corners of the rectangle with opposite corners (x0, y0) and (x1, y1)."""
    return [(x0, y0, None, None), (x1, y0, None, None), (x1, y1, None, None), (x0, y1, None, None)]


def ellipse_nodes(x0: float, y0: float, x1: float, y1: float) -> list[Node]:
    """Four smooth nodes that draw the ellipse inscribed in the box (x0, y0)-(x1, y1), counter-clockwise."""
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    a, b = abs(x1 - x0) / 2.0, abs(y1 - y0) / 2.0
    k = CIRCLE_HANDLE
    return [
        (cx + a, cy, cx + a, cy + k * b),
        (cx, cy + b, cx - k * a, cy + b),
        (cx - a, cy, cx - a, cy - k * b),
        (cx, cy - b, cx + k * a, cy - b),
    ]


def snap_angle(anchor: tuple[float, float], point: tuple[float, float], ratio: float = 1.0) -> tuple[float, float]:
    """*point* moved to the nearest multiple of 45 degrees from *anchor*, as seen on screen.

    *ratio* is the screen length of one y unit over one x unit, so the angle is the one the eye sees on an axes whose
    two scales differ; the distance on screen is kept.
    """
    dx, dy = point[0] - anchor[0], (point[1] - anchor[1]) * ratio
    if dx == 0 and dy == 0:
        return point
    length = math.hypot(dx, dy)
    angle = round(math.atan2(dy, dx) / (math.pi / 4.0)) * (math.pi / 4.0)
    return anchor[0] + length * math.cos(angle), anchor[1] + length * math.sin(angle) / ratio if ratio else anchor[1]
