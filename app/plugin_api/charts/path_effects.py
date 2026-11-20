"""Path effects written as text, kept as text, drawn as matplotlib.patheffects (dev/plans/path_effects_plan.txt).

A series' or a text's effect is kept as a string - it is saved in the project as one - and turned into the list of
AbstractPathEffect matplotlib draws only when the chart is drawn (kwarg_spec.resolve), as dashes.py does for line
styles. Effects are joined by "+" and drawn in that order, under the artist itself:

    ""  or  "none"                    no effect
    "outline(3, white)"               a halo: a stroke of width 3 points under the artist ("background" = the axes')
    "stroke(2, black)"                the same, dark by default: an edge
    "shadow(2, -2, 0.3, black)"       an offset copy, in points, with its alpha and colour
    "glow(8, gold)"                   a few wider and fainter strokes; the artist's own colour when none is given
    "ticked(45, 1.4, 10)"             ticks along the path: angle, length (in spacings), spacing in points
    "shadow + outline(2, white)"      both

Every argument may be left out, from the end. No eval: names, numbers and colours only, so a project file cannot run
code.
"""
from __future__ import annotations

import re
from typing import Any

#: What leaves the effect out.
NONE = frozenset({"", "none"})

#: Each effect's arguments, in order, with their defaults: a float, or a colour (None = the artist's own).
_ARGUMENTS: dict[str, tuple[tuple[str, Any], ...]] = {
    "outline": (("width", 3.0), ("color", "background")),
    "stroke": (("width", 2.0), ("color", "black")),
    "shadow": (("dx", 2.0), ("dy", -2.0), ("alpha", 0.3), ("color", "black")),
    "glow": (("width", 8.0), ("color", None)),
    "ticked": (("angle", 45.0), ("length", 1.4), ("spacing", 10.0)),
}

#: How many strokes a glow is made of, and the alpha of each.
GLOW_STEPS, GLOW_ALPHA = 4, 0.15

_CALL = re.compile(r"^([a-z]+)\s*(?:\((.*)\))?$")


def parse(text: str) -> list[tuple[str, dict[str, Any]]] | None:
    """*text* as (name, arguments) per effect, the defaults filled in; [] for no effect; None when it does not
    parse - an unknown name, a word where a number goes, a colour matplotlib does not know, too many arguments."""
    from matplotlib.colors import is_color_like

    if not isinstance(text, str):
        return None
    if text.strip().lower() in NONE:
        return []
    effects: list[tuple[str, dict[str, Any]]] = []
    for part in text.split("+"):
        match = _CALL.match(part.strip().lower())
        if match is None or match.group(1) not in _ARGUMENTS:
            return None
        name, inner = match.group(1), match.group(2)
        given = [item.strip() for item in inner.split(",")] if inner and inner.strip() else []
        spec = _ARGUMENTS[name]
        if len(given) > len(spec):
            return None
        arguments: dict[str, Any] = {}
        for index, (key, default) in enumerate(spec):
            if index >= len(given) or given[index] == "":
                arguments[key] = default
            elif key == "color":
                if given[index] != "background" and not is_color_like(given[index]):
                    return None
                arguments[key] = given[index]
            else:
                try:
                    arguments[key] = float(given[index])
                except ValueError:
                    return None
        if any(arguments.get(key, 0) < 0 for key in ("width", "spacing", "length")):
            return None
        if not 0 <= arguments.get("alpha", 0) <= 1:
            return None
        effects.append((name, arguments))
    return effects


def is_valid(text: str) -> bool:
    """Whether *text* is an effect that can be drawn (no effect included)."""
    return parse(text) is not None


def _colour(value: Any) -> Any:
    """A colour as matplotlib takes it: "background" is the axes' face colour of the style being drawn."""
    if value == "background":
        from matplotlib import rcParams

        face = rcParams.get("axes.facecolor", "white")
        return "white" if str(face).lower() in ("none", "") else face
    return value


def to_matplotlib(text: str, artist: str = "line") -> list[Any] | None:
    """The path effects matplotlib draws for *text* on an *artist* - "line", "patch" or "text" - ending with the
    artist itself; [] for no effect; None when the text does not parse (the option is then left out).

    A shadow is SimpleLineShadow under a line and SimplePatchShadow under a patch or a text: a patch shadow fills
    the path, which under a line would draw a filled polygon.
    """
    from matplotlib import patheffects as pe

    effects = parse(text)
    if effects is None:
        return None
    if not effects:
        return []
    drawn: list[Any] = []
    for name, arguments in effects:
        if name in ("outline", "stroke"):
            drawn.append(pe.Stroke(linewidth=arguments["width"], foreground=_colour(arguments["color"])))
        elif name == "shadow":
            offset = (arguments["dx"], arguments["dy"])
            colour = _colour(arguments["color"])
            if artist == "line":
                drawn.append(pe.SimpleLineShadow(offset=offset, shadow_color=colour, alpha=arguments["alpha"]))
            else:
                drawn.append(pe.SimplePatchShadow(offset=offset, shadow_rgbFace=colour, alpha=arguments["alpha"]))
        elif name == "glow":
            extra = {} if arguments["color"] is None else {"foreground": _colour(arguments["color"])}
            for step in range(GLOW_STEPS, 0, -1):  # widest and faintest first
                drawn.append(pe.Stroke(linewidth=arguments["width"] * step / GLOW_STEPS, alpha=GLOW_ALPHA, **extra))
        elif name == "ticked":
            drawn.append(pe.TickedStroke(angle=arguments["angle"], length=arguments["length"],
                                         spacing=arguments["spacing"]))
    drawn.append(pe.Normal())
    return drawn
