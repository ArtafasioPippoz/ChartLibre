"""Path effects written as text (app/plugin_api/charts/path_effects.py) and resolved through kwarg_spec."""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pytest
from matplotlib import patheffects as pe
from matplotlib import rc_context

from app.plugin_api.charts import kwarg_spec
from app.plugin_api.charts.path_effects import GLOW_STEPS, parse, to_matplotlib


def _kinds(effects: list) -> list[str]:
    return [type(effect).__name__ for effect in effects]


@pytest.mark.parametrize("text", ["", "none", "None", "  "])
def test_no_effect(text: str) -> None:
    assert to_matplotlib(text) == []


def test_defaults_fill_what_is_left_out() -> None:
    assert parse("shadow") == [("shadow", {"dx": 1.5, "dy": -1.5, "alpha": 0.35, "color": "black"})]
    assert parse("shadow(4)") == [("shadow", {"dx": 4.0, "dy": -1.5, "alpha": 0.35, "color": "black"})]
    assert parse("Outline( 5 , red )") == [("outline", {"width": 5.0, "color": "red"})]


def test_each_effect_draws_under_the_artist() -> None:
    assert _kinds(to_matplotlib("outline(3, white)")) == ["Stroke", "Normal"]
    assert _kinds(to_matplotlib("shadow + outline(2, white)")) == ["SimpleLineShadow", "Stroke", "Normal"]
    assert _kinds(to_matplotlib("glow(8, gold)")) == ["Stroke"] * GLOW_STEPS + ["Normal"]
    assert _kinds(to_matplotlib("ticked(30, 1, 6)")) == ["TickedStroke", "Normal"]


def test_a_shadow_fills_under_a_patch_or_a_text_and_follows_a_line() -> None:
    assert isinstance(to_matplotlib("shadow", "line")[0], pe.SimpleLineShadow)
    assert isinstance(to_matplotlib("shadow", "patch")[0], pe.SimplePatchShadow)
    assert isinstance(to_matplotlib("shadow", "text")[0], pe.SimplePatchShadow)


def test_background_is_the_axes_colour_of_the_style() -> None:
    with rc_context({"axes.facecolor": "#202020"}):
        stroke = to_matplotlib("outline")[0]
    assert stroke._gc["foreground"] == "#202020"


@pytest.mark.parametrize("text", [
    "blur(3)",                      # no such effect
    "outline(thick, white)",        # a word where a number goes
    "outline(3, notacolour)",       # a colour matplotlib does not know
    "shadow(1, 2, 0.5, red, 9)",    # too many arguments
    "shadow(1, 2, 1.5)",            # alpha above 1
    "outline(-1)",                  # a negative width
    "__import__('os').system('x')",  # code is never run, only refused
    "outline(3, white) +",          # an empty effect
])
def test_what_does_not_parse_is_refused(text: str) -> None:
    assert to_matplotlib(text) is None


def test_resolve_converts_and_drops_a_typo() -> None:
    spec = kwarg_spec.path_effects_spec("patch")
    assert _kinds(kwarg_spec.resolve(spec, [{"path_effects": "shadow"}])["path_effects"]) == [
        "SimplePatchShadow", "Normal"]
    dropped: list = []
    assert kwarg_spec.resolve(spec, [{"path_effects": "shaddow"}], dropped) == {}
    assert dropped == [("path_effects", "shaddow", str)]
    assert kwarg_spec.resolve(spec, [{"path_effects": "none"}]) == {}


def test_a_chart_with_effects_draws_and_exports() -> None:
    figure, axes = plt.subplots()
    try:
        axes.plot([0, 1, 2], [0, 1, 0], path_effects=to_matplotlib("glow(6) + outline(4, white)", "line"))
        axes.bar([0, 1], [1, 2], path_effects=to_matplotlib("shadow", "patch"))
        axes.set_title("Title", path_effects=to_matplotlib("outline(3, background)", "text"))
        for fmt in ("png", "svg"):
            buffer = io.BytesIO()
            figure.savefig(buffer, format=fmt)
            assert buffer.getvalue()
    finally:
        plt.close(figure)


# ----------------------------------------------------------------------
# Step 2: the texts of a chart, and the combo
# ----------------------------------------------------------------------
def _texts_with_effects(ax) -> tuple[int, int]:
    from app.plugin_api.charts.render_figure import _axes_texts

    texts = _axes_texts(ax)
    return sum(1 for text in texts if text.get_path_effects()), len(texts)


def test_the_figure_effect_reaches_every_text_and_an_axis_can_change_it() -> None:
    from types import SimpleNamespace

    from app.plugin_api.charts.render_figure import _apply_text_effects

    figure, (first, second, third) = plt.subplots(1, 3)
    try:
        for ax in (first, second, third):
            ax.plot([0, 1], [0, 1], label="a")
            ax.set_title("t")
            ax.set_xlabel("x")
            ax.legend()
            ax.annotate("note", (0.5, 0.5))
        figure.suptitle("All")
        axes = [SimpleNamespace(id=1, options={}), SimpleNamespace(id=2, options={"text_effect": "none"}),
                SimpleNamespace(id=3, options={"text_effect": "shadow"})]
        descriptor = SimpleNamespace(options={"text_effect": "outline(3, white)"})
        _apply_text_effects(figure, descriptor, axes, {1: first, 2: second, 3: third})
        with_effect, total = _texts_with_effects(first)
        assert with_effect == total
        assert _texts_with_effects(second)[0] == 0
        assert _kinds(third.title.get_path_effects()) == ["SimplePatchShadow", "Normal"]
        assert _kinds(figure._suptitle.get_path_effects()) == ["Stroke", "Normal"]
        assert _kinds(first.get_legend().get_texts()[0].get_path_effects()) == ["Stroke", "Normal"]
        # Zoomed: the tick labels made then copy the effect of the first.
        first.set_xlim(0, 0.1)
        figure.canvas.draw()
        assert all(tick.label1.get_path_effects() for tick in first.xaxis.get_major_ticks())
    finally:
        plt.close(figure)


def test_a_bad_axis_effect_falls_back_to_the_figure_one() -> None:
    from types import SimpleNamespace

    from app.plugin_api.charts.render_figure import _apply_text_effects

    figure, ax = plt.subplots()
    try:
        ax.set_title("t")
        _apply_text_effects(figure, SimpleNamespace(options={"text_effect": "shadow"}),
                            [SimpleNamespace(id=1, options={"text_effect": "blur"})], {1: ax})
        assert _kinds(ax.title.get_path_effects()) == ["SimplePatchShadow", "Normal"]
    finally:
        plt.close(figure)


def test_the_effect_widget_is_a_preview_and_the_helper_button(qapp) -> None:
    from app.widgets.drop_down_controls.path_effect_combo import PathEffectCombo

    changes: list[int] = []
    figure_combo = PathEffectCombo()
    figure_combo.currentIndexChanged.connect(changes.append)
    assert figure_combo.current_effect() == ""
    assert figure_combo.set_current_effect("glow(4, red) + shadow")
    assert figure_combo.current_effect() == "glow(4, red) + shadow"
    assert not figure_combo._preview.pixmap().isNull()  # the effect drawn
    assert not figure_combo.set_current_effect("blur")
    assert figure_combo.set_current_effect("none") and figure_combo.current_effect() == ""  # None is ""
    figure_combo._change("outline(6, background)")
    assert figure_combo.current_effect() == "outline(6, background)" and changes == [0]

    axis_combo = PathEffectCombo(inherit="Figure's")
    assert axis_combo.current_effect() == ""
    assert axis_combo.set_current_effect("none") and axis_combo.current_effect() == "none"
    axis_combo._on_reset()
    assert axis_combo.current_effect() == ""  # back to the figure's


def test_the_helper_colour_reaches_halo_and_dark_outline(qapp) -> None:
    from app.widgets.drop_down_controls.path_effect_dialog import PathEffectDialog

    dialog = PathEffectDialog("outline(6, background) + stroke(2, black)")
    rows = {row.name: row for row in dialog._rows}
    rows["outline"].colour.set_color("#ff0000")
    rows["outline"].colour.colorChanged.emit("#ff0000")
    rows["stroke"].colour.set_color("#00ff00")
    rows["stroke"].colour.colorChanged.emit("#00ff00")
    assert dialog.effect() == "outline(6, #ff0000) + stroke(2, #00ff00)"
    # The colour picker of an effect never hands back a transparent colour (it would draw nothing).
    assert rows["outline"].colour._alpha is False
    assert not dialog.preview.pixmap().isNull()


# ----------------------------------------------------------------------
# Step 3: series, their legend entries, reference lines
# ----------------------------------------------------------------------
def test_a_series_effect_reaches_what_it_drew_and_its_legend_entry() -> None:
    from types import SimpleNamespace

    from app.plugin_api.charts.base import SeriesArtistTags
    from app.plugin_api.charts.render_figure import _apply_series_effects

    figure, ax = plt.subplots()
    try:
        tags = SeriesArtistTags(ax)
        tags.next("line")
        ax.plot([0, 1], [0, 1], label="Line")
        tags.next("bars")
        ax.bar([0, 1], [1, 2], label="Bars")
        tags.next("plain")
        ax.plot([0, 1], [1, 0], label="Plain")
        tags.done()
        ax.legend()
        _apply_series_effects(ax, [SimpleNamespace(name="line", style={"path_effects": "outline(4, white)"}),
                                   SimpleNamespace(name="bars", style={"path_effects": "shadow"}),
                                   SimpleNamespace(name="plain", style={})])
        line, plain = ax.lines
        assert _kinds(line.get_path_effects()) == ["Stroke", "Normal"]
        assert plain.get_path_effects() == []
        assert all(_kinds(bar.get_path_effects()) == ["SimplePatchShadow", "Normal"] for bar in ax.patches)
        handles = dict(zip((text.get_text() for text in ax.get_legend().get_texts()),
                           ax.get_legend().legend_handles))
        assert _kinds(handles["Line"].get_path_effects()) == ["Stroke", "Normal"]
        assert _kinds(handles["Bars"].get_path_effects()) == ["SimplePatchShadow", "Normal"]
        assert handles["Plain"].get_path_effects() == []
    finally:
        plt.close(figure)


def test_a_reference_line_draws_its_effect() -> None:
    from app.plugin_api.charts.base import BaseAxisRenderer

    figure, ax = plt.subplots()
    try:
        BaseAxisRenderer().apply_reference_line(
            ax, {"value": 1, "orientation": "horizontal", "kwargs": {"path_effects": "shadow"}})
        BaseAxisRenderer().apply_reference_line(ax, {"value": 2, "kwargs": {"path_effects": "blur"}})
        shadowed, refused = ax.lines
        assert _kinds(shadowed.get_path_effects()) == ["SimpleLineShadow", "Normal"]
        assert refused.get_path_effects() == []  # drawn, without the effect
    finally:
        plt.close(figure)


# ----------------------------------------------------------------------
# Step 4: the dictionary editor
# ----------------------------------------------------------------------
def test_the_dictionary_editor_offers_the_effect_combo(qapp) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QStyleOptionViewItem

    from app.widgets.dictionary_editor import DictEditorPanel, DictValueDelegate, _group_for_key, _kind_for_key
    from app.widgets.drop_down_controls.path_effect_combo import PathEffectCombo

    spec = kwarg_spec.path_effects_spec("patch")
    assert _kind_for_key("path_effects", {}) == "path_effects"  # a plugin's key, with no spec of its own
    assert _group_for_key("path_effects", spec["path_effects"], "path_effects") == "Appearance"

    panel = DictEditorPanel()
    panel.set_config(spec)
    panel.set_values({"path_effects": "shadow + outline(2, white)"})
    index = panel.tree.indexFromItem(panel._key_items["path_effects"], 1)
    delegate = DictValueDelegate(panel)
    editor = delegate.createEditor(panel.tree.viewport(), QStyleOptionViewItem(), index)
    assert isinstance(editor, PathEffectCombo)
    delegate.setEditorData(editor, index)
    assert editor.current_effect() == "shadow + outline(2, white)"
    editor.set_current_effect("glow(6)")
    delegate.setModelData(editor, panel.tree.model(), index)
    assert panel.value_for_key("path_effects") == "glow(6)"
    assert not panel._key_items["path_effects"].icon(1).isNull()  # its preview
    assert index.data(Qt.ItemDataRole.DisplayRole)


# ----------------------------------------------------------------------
# Step 5: a series too dense for its effect
# ----------------------------------------------------------------------
def test_a_series_with_too_many_points_is_drawn_without_its_effect(monkeypatch) -> None:
    from types import SimpleNamespace

    import app.plugin_api.charts.render_figure as render
    from app.plugin_api.charts.base import SeriesArtistTags

    monkeypatch.setattr(render, "PATH_EFFECT_MAX_POINTS", 100)
    figure, ax = plt.subplots()
    try:
        tags = SeriesArtistTags(ax)
        tags.next("dense")
        ax.scatter(range(150), range(150), label="Dense")
        tags.next("light")
        ax.plot(range(50), range(50), label="Light")
        tags.done()
        render._apply_series_effects(ax, [SimpleNamespace(name="dense", style={"path_effects": "shadow"}),
                                          SimpleNamespace(name="light", style={"path_effects": "shadow"})])
        (points,), (line,) = ax.collections, ax.lines
        assert not points.get_path_effects()  # None or []: no effect
        assert _kinds(line.get_path_effects()) == ["SimpleLineShadow", "Normal"]
    finally:
        plt.close(figure)


# ----------------------------------------------------------------------
# Step 5 (H): the style's own text effect
# ----------------------------------------------------------------------
def test_a_style_keeps_its_text_effect_in_a_comment_line() -> None:
    from app.plugin_api.charts.path_effects import style_line, style_text_effect

    text = "axes.facecolor: 202020\n#  chartlibre.text_effect :  outline(3, background)\nlines.linewidth: 2\n"
    assert style_text_effect(text) == "outline(3, background)"
    assert style_text_effect("# chartlibre.text_effect: blur\n") == ""  # one that does not parse
    assert style_text_effect("axes.grid: True\n") == ""
    assert style_line("shadow") == "# chartlibre.text_effect: shadow\n"
    assert style_line("") == style_line("none") == ""
    assert style_text_effect(style_line("glow(4, gold)")) == "glow(4, gold)"


def test_a_figure_takes_its_styles_effect_unless_it_says_none() -> None:
    from types import SimpleNamespace

    from app.plugin_api.charts.render_figure import _apply_text_effects

    style = "# chartlibre.text_effect: shadow\naxes.grid: True\n"
    for own, expected in (("", ["SimplePatchShadow", "Normal"]), ("none", []),
                          ("outline(2, white)", ["Stroke", "Normal"])):
        figure, ax = plt.subplots()
        try:
            ax.set_title("t")
            descriptor = SimpleNamespace(options={"mpl_style": style, "text_effect": own})
            _apply_text_effects(figure, descriptor, [SimpleNamespace(id=1, options={})], {1: ax})
            assert _kinds(ax.title.get_path_effects()) == expected, own
        finally:
            plt.close(figure)


def test_the_style_editor_reads_and_writes_the_effect(qapp) -> None:
    from pathlib import Path

    from app.dialogs.edit_mpl_styles_dialog import TEXT_EFFECT_KEY, MplStyleEditorDialog

    dialog = MplStyleEditorDialog(None, initial_style_text="axes.grid: True\n# chartlibre.text_effect: shadow\n")
    try:
        assert dialog._text_effect() == "shadow"
        assert dialog._param_schema[TEXT_EFFECT_KEY]["kind"] == "path_effects"
        overrides, invalid = dialog._collect_overrides()
        assert TEXT_EFFECT_KEY not in overrides and not invalid  # not an rcParam, never validated as one
        path = Path(dialog._write_temp_style_file(dialog._current_merged_style()))
        try:
            assert "# chartlibre.text_effect: shadow\n" in path.read_text(encoding="utf-8")
        finally:
            path.unlink(missing_ok=True)
    finally:
        dialog.close()


def test_effect_builder_writes_and_reads_the_text(qapp) -> None:
    from app.plugin_api.charts.path_effects import is_valid
    from app.widgets.drop_down_controls.path_effect_dialog import PathEffectDialog

    dialog = PathEffectDialog("shadow + outline(3, background)")
    assert [row.use.isChecked() for row in dialog._rows] == [True, False, True, False, False]
    dialog._rows[1].use.setChecked(True)
    assert dialog.effect() == "shadow(1.5, -1.5, 0.35, black) + glow(8) + outline(3, background)"
    assert is_valid(dialog.effect())
    dialog.text.setText("glow(6)")
    dialog.text.textEdited.emit("glow(6)")
    assert [row.use.isChecked() for row in dialog._rows] == [False, True, False, False, False]
    for row in dialog._rows:
        row.use.setChecked(False)
    assert dialog.effect() == ""


def test_an_interaction_plot_and_an_untagging_renderer_take_the_series_effect() -> None:
    from types import SimpleNamespace

    import numpy as np

    from app.charts.interaction import InteractionAxisRenderer
    from app.data.series_frame import SeriesFrame
    from app.plugin_api.charts.base import SeriesData
    from app.plugin_api.charts.render_figure import _apply_series_effects, _tag_untagged_series

    rng = np.random.default_rng(3)
    frame = SeriesFrame({"x": ["a", "a", "b", "b"] * 6, "y": rng.normal(size=24),
                         "trace": ["u", "v"] * 12})
    sd = SeriesData(name="s", df=frame, style={"path_effects": "outline(4, white)"})
    figure, ax = plt.subplots()
    try:
        InteractionAxisRenderer().render_axis(ax, [sd], {})
        _apply_series_effects(ax, [sd])
        assert any(_kinds(line.get_path_effects()) == ["Stroke", "Normal"] for line in ax.lines)
    finally:
        plt.close(figure)

    figure, ax = plt.subplots()  # a renderer that tags nothing: its only series still gets the effect
    try:
        before = {id(artist) for artist in ax.get_children()}
        ax.plot([0, 1], [0, 1])
        series = SimpleNamespace(name="only", style={"path_effects": "outline(4, white)"})
        _tag_untagged_series(ax, before, [series])
        _apply_series_effects(ax, [series])
        assert _kinds(ax.lines[0].get_path_effects()) == ["Stroke", "Normal"]
    finally:
        plt.close(figure)


def test_several_series_of_a_box_plot_and_a_histogram_each_take_their_own_effect() -> None:
    import numpy as np

    from app.charts.box import BoxAxisRenderer
    from app.charts.histogram import HistogramAxisRenderer
    from app.data.series_frame import SeriesFrame
    from app.plugin_api.charts.base import SeriesData
    from app.plugin_api.charts.render_figure import _apply_series_effects, _tag_untagged_series

    rng = np.random.default_rng(1)
    for renderer in (BoxAxisRenderer, HistogramAxisRenderer):
        series = [SeriesData(name=name, df=SeriesFrame({"value": rng.normal(size=40) + shift}),
                             style={"path_effects": "outline(3, white)"} if name == "A" else {})
                  for shift, name in enumerate("AB")]
        figure, ax = plt.subplots()
        try:
            before = {id(artist) for artist in ax.get_children()}
            renderer().render_axis(ax, series, {})
            _tag_untagged_series(ax, before, series)
            _apply_series_effects(ax, series)
            drawn = [artist for artist in ax.get_children() if id(artist) not in before and artist.get_path_effects()]
            assert drawn, renderer  # A's artists have the effect ...
            assert {artist._chartlibre_series for artist in drawn} == {"A"}  # ... and B's do not
        finally:
            plt.close(figure)


def test_a_series_whose_line_style_is_default_draws_solid() -> None:
    from app.plugin_api.charts.dashes import solid_unless_set

    assert [solid_unless_set(value) for value in (None, "", "default", "Default", "bogus")] == ["-"] * 5
    assert solid_unless_set("--") == "--"


def test_a_kaplan_meier_effect_is_on_the_curve_and_not_on_the_band() -> None:
    import numpy as np

    from app.charts.survival import KaplanMeierAxisRenderer
    from app.data.series_frame import SeriesFrame
    from app.plugin_api.charts.base import SeriesData
    from app.plugin_api.charts.render_figure import _apply_series_effects, _tag_untagged_series

    rng = np.random.default_rng(2)
    frame = SeriesFrame({"time": rng.uniform(1, 9, 40), "event": np.ones(40)})
    sd = SeriesData(name="A", df=frame, style={"path_effects": "shadow"})
    figure, ax = plt.subplots()
    try:
        before = {id(artist) for artist in ax.get_children()}
        KaplanMeierAxisRenderer().render_axis(ax, [sd], {"confidence": 0.95, "band_alpha": 0.2})
        _tag_untagged_series(ax, before, [sd])
        _apply_series_effects(ax, [sd])
        assert ax.lines and all(line.get_path_effects() for line in ax.lines[:1])
        assert ax.collections and not any(collection.get_path_effects() for collection in ax.collections)
    finally:
        plt.close(figure)


def test_annotation_and_measurement_take_an_effect() -> None:
    from app.charts.scatter import ScatterAxisRenderer

    renderer = ScatterAxisRenderer()
    figure, ax = plt.subplots()
    try:
        text = renderer.apply_annotation(ax, {"x": 1, "y": 1, "text": "hi", "kwargs": {"path_effects": "outline(3, white)"}})
        renderer.apply_measurement(ax, {"x0": 0, "y0": 0, "x1": 1, "y1": 1, "kwargs": {"path_effects": "shadow"}})
        assert len(text.get_path_effects()) == 2
        assert ax.lines[0].get_path_effects() and all(t.get_path_effects() for t in ax.texts)
    finally:
        plt.close(figure)


def test_paths_are_drawn_from_text_points() -> None:
    from app.charts.scatter import ScatterAxisRenderer

    renderer = ScatterAxisRenderer()
    figure, ax = plt.subplots()
    try:
        renderer.apply_paths(ax, {"paths": [
            {"points": "0,0; 1,0; 1,1", "closed": "yes", "kwargs": {"facecolor": "#ccc", "path_effects": "shadow"}},
            {"points": "0,0; 2,2", "closed": "no"},
            {"points": "1,1"},
        ]})
        assert len(ax.patches) == 2
        assert ax.patches[0].get_closed() and not ax.patches[1].get_closed()
        assert ax.patches[0].get_path_effects()
    finally:
        plt.close(figure)


def test_the_xkcd_sketch_writes_its_text_in_the_bundled_comic_neue() -> None:
    from types import SimpleNamespace

    from matplotlib import font_manager

    from app.plugin_api.charts.render_figure import XKCD_FONT, _apply_sketch

    figure, ax = plt.subplots()
    try:
        ax.set_title("t")
        _apply_sketch(figure, SimpleNamespace(options={"sketch": "light"}))
        assert ax.title.get_fontfamily() != [XKCD_FONT]  # only the xkcd preset changes the face
        _apply_sketch(figure, SimpleNamespace(options={"sketch": "xkcd"}))
        assert ax.title.get_fontfamily() == [XKCD_FONT]
        assert XKCD_FONT in {font.name for font in font_manager.fontManager.ttflist}
        figure.canvas.draw()  # drawn with the font, not with a fallback
        assert font_manager.findfont(font_manager.FontProperties(family=XKCD_FONT)).endswith("ComicNeue-Regular.ttf")
    finally:
        plt.close(figure)
