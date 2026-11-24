"""Path effects written as text, kept as text, drawn as matplotlib.patheffects (dev/plans/path_effects_plan.txt).

A series' or a text's effect is kept as a string - it is saved in the project as one - and turned into the list of
AbstractPathEffect matplotlib draws only when the chart is drawn (kwarg_spec.resolve), as dashes.py does for line
styles. Effects are joined by "+" and drawn in that order, under the artist itself:

    ""  or  "none"                    no effect
    "outline(6, white)"               a halo: a stroke of width 6 points (half of it shows outside) under the artist ("background" = the axes')
    "stroke(2, black)"                the same, dark by default: an edge
    "shadow(1.5, -1.5, 0.35, black)"       an offset copy, in points, with its alpha and colour
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
    "outline": (("width", 6.0), ("color", "background")),
    "stroke": (("width", 2.0), ("color", "black")),
    "shadow": (("dx", 1.5), ("dy", -1.5), ("alpha", 0.35), ("color", "black")),
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


def _marker_aware_effects() -> tuple[type, type]:
    """(shadow, halo) effects that treat a marker as a shape, not as a line.

    matplotlib's SimpleLineShadow draws only a path's edge, so a marker (drawn with a face) gets a hollow grey
    ring beside it - "a grey copy, far". Here a path with a face is shadowed with that face filled, and a halo
    around a marker is a filled disc, not only a ring over its own edge.
    """
    from matplotlib import colors as mcolors
    from matplotlib import patheffects as pe

    class MarkerShadow(pe.SimpleLineShadow):
        def draw_path(self, renderer, gc, tpath, affine, rgbFace):
            gc0 = renderer.new_gc()
            gc0.copy_properties(gc)
            colour = mcolors.to_rgba(self._shadow_color if self._shadow_color is not None else "black")
            gc0.set_foreground(colour, isRGBA=True)
            gc0.set_alpha(self._alpha)
            if rgbFace is not None:
                gc0.set_linewidth(0)  # a filled shape: the fill only, or the edge would darken it twice
            gc0 = self._update_gc(gc0, self._gc)
            renderer.draw_path(gc0, tpath, affine + self._offset_transform(renderer),
                               colour if rgbFace is not None else None)
            gc0.restore()

    class MarkerHalo(pe.Stroke):
        def draw_path(self, renderer, gc, tpath, affine, rgbFace):
            gc0 = renderer.new_gc()
            gc0.copy_properties(gc)
            gc0 = self._update_gc(gc0, self._gc)
            face = gc0.get_rgb() if rgbFace is not None else None
            renderer.draw_path(gc0, tpath, affine + self._offset_transform(renderer), face)
            gc0.restore()

    # Named as the matplotlib effects they refine, which is what a saved figure and the tests look for.
    MarkerShadow.__name__ = MarkerShadow.__qualname__ = "SimpleLineShadow"
    MarkerHalo.__name__ = MarkerHalo.__qualname__ = "Stroke"
    return MarkerShadow, MarkerHalo


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
    shadow_class, halo_class = _marker_aware_effects()
    for name, arguments in effects:
        if name in ("outline", "stroke"):
            drawn.append(halo_class(linewidth=arguments["width"], foreground=_colour(arguments["color"])))
        elif name == "shadow":
            offset = (arguments["dx"], arguments["dy"])
            colour = _colour(arguments["color"])
            if artist == "line":
                drawn.append(shadow_class(offset=offset, shadow_color=colour, alpha=arguments["alpha"]))
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


#: The style sheet's own text effect (dev/plans/path_effects_plan.txt, H). An .mplstyle holds rcParams only, and
#: path effects are not one, so it is kept as a comment matplotlib skips: "# chartlibre.text_effect: outline(3)".
STYLE_KEY = "chartlibre.text_effect"

_STYLE_LINE = re.compile(r"^[ \t]*#[ \t]*chartlibre\.text_effect[ \t]*:[ \t]*(.*?)[ \t]*$", re.MULTILINE)


def style_text_effect(style_text: str) -> str:
    """The text effect a style's text carries ("" for none, or one that does not parse)."""
    match = _STYLE_LINE.search(style_text or "") if isinstance(style_text, str) else None
    effect = match.group(1) if match else ""
    return effect if effect and is_valid(effect) else ""


def style_line(effect: str) -> str:
    """The line a style file keeps *effect* in ("" for none)."""
    effect = (effect or "").strip()
    return f"# {STYLE_KEY}: {effect}\n" if effect and effect.lower() not in NONE else ""
