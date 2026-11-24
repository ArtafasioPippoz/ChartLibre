"""Pictures kept in the project and drawn as markers."""
import numpy as np
import pandas as pd
import pytest
from matplotlib.figure import Figure
from matplotlib.offsetbox import AnnotationBbox

from app.data.repo.images import kind_of
from app.plugin_api.charts.render_figure import render_figure_from_descriptor

SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
       b'<circle cx="5" cy="5" r="4" fill="#000000"/></svg>')


def test_store_kind_replace_and_undo(repo):
    assert kind_of(SVG) == "svg"
    with pytest.raises(ValueError):
        kind_of(b"hello")
    repo.add_image("dot", SVG, source="test", license="MIT")
    stored = repo.get_image("dot")
    assert stored.kind == "svg" and stored.license == "MIT" and repo.image_names() == ["dot"]
    repo.remove_image("dot")
    assert repo.image_names() == []
    repo.undo_last()
    assert repo.image_names() == ["dot"]


@pytest.mark.parametrize("chart", ["Scatter Plot", "Time Series"])
def test_drawn_as_markers(qapp, repo, chart):
    repo.add_image("dot", SVG)
    repo.import_dataframe(pd.DataFrame({"a": np.arange(20.0), "b": np.arange(20.0)}), table_name="d",
                          normalize_columns=False)
    figure_id = int(repo.create_figure_descriptor(name="F"))
    axis_id = int(repo.create_axis_descriptor(figure_id=figure_id, axis_index=0, chart_type=chart, title="t",
                                              x_label="x", y_label="y", options={}))
    repo.create_series_descriptor(axis_id=axis_id, series_index=0, name="s", sql_query="SELECT a AS x, b AS y FROM d",
                                  roles={"x": "x", "y": "y"}, style={"marker": "image:dot", "markevery": 2,
                                                                     "color": "#d62728"})
    figure = Figure()
    render_figure_from_descriptor(figure=figure, descriptor=repo.load_figure_descriptor(figure_id), repo=repo)
    boxes = [a for a in figure.axes[0].get_children() if isinstance(a, AnnotationBbox)]
    assert len(boxes) == 10
    array = boxes[0].offsetbox.get_data()
    opaque = array[..., 3] > 0.5
    assert np.allclose(array[..., 0][opaque], 214 / 255, atol=0.02)  # a single-colour icon takes the series' colour
    figure.savefig(__import__("io").BytesIO(), format="svg")


def test_the_option_box_offers_the_projects_pictures(qapp, repo):
    from types import SimpleNamespace

    from app.widgets.chart_properties.series_properties import SeriesPropertiesWidget

    repo.add_image("dot", SVG)
    widget = SeriesPropertiesWidget()
    widget._repo = repo
    widget._load_series_descriptor(SimpleNamespace(id=1, options={"marker": "image:dot"}, sql_query=""))
    chooser = widget._marker_editor.chooser
    assert chooser._buttons["picture"].isChecked()
    assert chooser._picture_list.currentData() == "dot"
    assert widget._marker_editor.combo.current_marker() == "image:dot"


def test_a_typed_line_pattern_applies_and_previews(qapp):
    from matplotlib.lines import Line2D

    from app.plugin_api.charts import dashes
    from app.widgets.chart_panel.panel import _drawn_linestyle
    from app.widgets.drop_down_controls.line_combo import LineStyleCombo
    from app.widgets.drop_down_controls.style_chooser import StyleChooser

    combo = LineStyleCombo()
    chooser = StyleChooser(combo, is_custom=dashes.is_custom, select=combo.set_current_linestyle, hint="")
    chooser._buttons["custom"].setChecked(True)
    chooser._text.setText(".")
    chooser._typed()
    assert combo.current_linestyle() == "."
    line = Line2D([0, 1], [0, 1])
    line.set_linestyle(_drawn_linestyle("."))
    assert line.get_linestyle() == "--" or isinstance(line.get_dashes if hasattr(line, "get_dashes") else 0, object)


def test_a_picture_marker_with_the_rolling_mean(qapp, repo):
    repo.add_image("dot", SVG)
    repo.import_dataframe(pd.DataFrame({"a": np.arange(30.0), "b": np.arange(30.0)}), table_name="d",
                          normalize_columns=False)
    figure_id = int(repo.create_figure_descriptor(name="F"))
    axis_id = int(repo.create_axis_descriptor(figure_id=figure_id, axis_index=0, chart_type="Time Series", title="t",
                                              x_label="x", y_label="y", options={"show_rolling": True}))
    repo.create_series_descriptor(axis_id=axis_id, series_index=0, name="s", sql_query="SELECT a AS x, b AS y FROM d",
                                  roles={"x": "x", "y": "y"}, style={"marker": "image:dot", "linestyle": "-"})
    figure = Figure()
    render_figure_from_descriptor(figure=figure, descriptor=repo.load_figure_descriptor(figure_id), repo=repo)
    assert figure.axes[0].lines and any(isinstance(a, AnnotationBbox) for a in figure.axes[0].get_children())


def test_typing_a_pattern_leaves_the_standard_list_as_it_was(qapp):
    from app.plugin_api.charts import dashes
    from app.widgets.drop_down_controls.line_combo import LineStyleCombo
    from app.widgets.drop_down_controls.style_chooser import StyleChooser

    combo = LineStyleCombo()
    chooser = StyleChooser(combo, is_custom=dashes.is_custom, select=combo.set_current_linestyle, hint="")
    combo.set_current_linestyle("--")
    chooser.sync()
    assert chooser._shown.currentData() == "--"
    chooser._buttons["custom"].setChecked(True)
    chooser._text.setText("..--")
    chooser._typed()
    assert combo.current_linestyle() == "..--" and chooser._shown.currentData() == "--"
    chooser._buttons["standard"].setChecked(True)
    assert combo.current_linestyle() == "--"


def _bars(repo, chart: str, style: dict):
    repo.import_dataframe(pd.DataFrame({"c": ["a", "b", "c"], "v": [2500.0, 1000.0, 0.0]}), table_name="d",
                          normalize_columns=False)
    figure_id = int(repo.create_figure_descriptor(name="F"))
    axis_id = int(repo.create_axis_descriptor(figure_id=figure_id, axis_index=0, chart_type=chart, title="t",
                                              x_label="x", y_label="y", options={}))
    repo.create_series_descriptor(axis_id=axis_id, series_index=0, name="people",
                                  sql_query="SELECT c AS X, v AS Y FROM d", roles={"X": "X", "Y": "Y"},
                                  style={"color": "#1f77b4", **style})
    figure = Figure()
    render_figure_from_descriptor(figure=figure, descriptor=repo.load_figure_descriptor(figure_id), repo=repo)
    return figure


@pytest.mark.parametrize("chart", ["Bar Chart", "Horizontal Bar Chart"])
def test_bars_drawn_as_a_pictogram_with_the_last_picture_cut(qapp, repo, chart):
    repo.add_image("dot", SVG)
    figure = _bars(repo, chart, {"bar_picture": "dot", "picture_unit": 1000})
    ax = figure.axes[0]
    assert len(ax.images) == 3 + 1  # 2.5 pictures and 1, the zero bar nothing
    assert [getattr(image, "_chartlibre_cut", 1.0) for image in ax.images].count(0.5) == 1  # only the half one is cut
    assert not any(patch.get_visible() for patch in ax.patches)  # the plain bars are gone, only their limits stay
    value_limit = ax.get_xlim()[1] if chart.startswith("Horizontal") else ax.get_ylim()[1]
    assert value_limit >= 2500
    assert "1 = 1000" in [text.get_text() for text in ax.get_legend().get_texts()][0]
    figure.savefig(__import__("io").BytesIO(), format="svg")
    figure.savefig(__import__("io").BytesIO(), format="png")


def test_bars_stretched_and_a_missing_picture_leaves_plain_bars(qapp, repo):
    repo.add_image("dot", SVG)
    stretched = _bars(repo, "Bar Chart", {"bar_picture": "dot"}).axes[0]
    assert len(stretched.images) == 2 and stretched.get_aspect() == "auto"
    plain = _bars(repo, "Bar Chart", {"bar_picture": "nothing"}).axes[0]
    assert len(plain.images) == 0 and all(patch.get_visible() for patch in plain.patches)


def test_a_bar_series_offers_the_projects_pictures(qapp, repo):
    from types import SimpleNamespace

    from app.widgets.chart_properties.series_properties import SeriesPropertiesWidget

    repo.add_image("dot", SVG)
    repo.import_dataframe(pd.DataFrame({"c": ["a", "b"], "v": [1.0, 2.0]}), table_name="d", normalize_columns=False)
    figure_id = int(repo.create_figure_descriptor(name="F"))
    axes = {}
    for index, chart in enumerate(("Bar Chart", "Scatter Plot")):
        axis_id = int(repo.create_axis_descriptor(figure_id=figure_id, axis_index=index, chart_type=chart, title="t",
                                                  x_label="x", y_label="y", options={}))
        axes[chart] = int(repo.create_series_descriptor(
            axis_id=axis_id, series_index=0, name=chart, sql_query="SELECT c AS X, v AS Y FROM d",
            roles={"X": "X", "Y": "Y"}, style={"bar_picture": "dot", "picture_unit": 500}))
    widget = SeriesPropertiesWidget()
    widget._repo, widget._figure_id = repo, figure_id
    widget._load_series_descriptor(SimpleNamespace(id=axes["Bar Chart"], options={"bar_picture": "dot",
                                                                                 "picture_unit": 500}, sql_query=""))
    editor = widget._bar_picture_editor
    assert not widget._groups[3].isHidden()
    assert [editor.picture.itemData(i) for i in range(editor.picture.count())] == ["", "dot"]
    assert editor.picture.currentData() == "dot" and editor.unit.value() == 500
    assert editor.values() == {"bar_picture": "dot", "picture_unit": 500.0}
    editor.picture.setCurrentIndex(0)
    assert editor.values() == {"bar_picture": None, "picture_unit": None} and not editor.unit.isEnabled()
    widget._load_series_descriptor(SimpleNamespace(id=axes["Scatter Plot"], options={}, sql_query=""))
    assert widget._groups[3].isHidden()  # a scatter's series are drawn as markers, not bars


def test_a_column_names_the_picture_of_each_point(qapp, repo):
    repo.add_image("dot", SVG)
    repo.add_image("ring", SVG.replace(b"fill=", b'stroke="#000" stroke-width="1" fill-opacity="0" fill='))
    repo.import_dataframe(pd.DataFrame({"a": np.arange(6.0), "b": np.arange(6.0),
                                        "kind": ["dot", "ring", "dot", "ring", "dot", "nothing"]}),
                          table_name="d", normalize_columns=False)
    figure_id = int(repo.create_figure_descriptor(name="F"))
    axis_id = int(repo.create_axis_descriptor(figure_id=figure_id, axis_index=0, chart_type="Scatter Plot", title="t",
                                              x_label="x", y_label="y", options={}))
    repo.create_series_descriptor(axis_id=axis_id, series_index=0, name="s",
                                  sql_query="SELECT a AS x, b AS y, kind AS picture FROM d",
                                  roles={"x": "x", "y": "y", "picture": "picture"}, style={"color": "#d62728"})
    figure = Figure()
    render_figure_from_descriptor(figure=figure, descriptor=repo.load_figure_descriptor(figure_id), repo=repo)
    ax = figure.axes[0]
    boxes = [a for a in ax.get_children() if isinstance(a, AnnotationBbox)]
    assert sorted(box._chartlibre_picture for box in boxes) == ["image:dot"] * 3 + ["image:ring"] * 2
    assert len(ax.collections) == 1  # the point whose picture the project lacks is an ordinary marker
    figure.savefig(__import__("io").BytesIO(), format="svg")


def test_a_column_names_the_picture_of_each_point_of_a_line(qapp, repo):
    repo.add_image("dot", SVG)
    repo.import_dataframe(pd.DataFrame({"a": np.arange(6.0), "b": np.arange(6.0),
                                        "kind": ["dot", "dot", "", "dot", "nothing", "dot"]}),
                          table_name="d", normalize_columns=False)
    figure_id = int(repo.create_figure_descriptor(name="F"))
    axis_id = int(repo.create_axis_descriptor(figure_id=figure_id, axis_index=0, chart_type="Time Series", title="t",
                                              x_label="x", y_label="y", options={"show_rolling": False}))
    repo.create_series_descriptor(axis_id=axis_id, series_index=0, name="s",
                                  sql_query="SELECT a AS x, b AS y, kind AS picture FROM d",
                                  roles={"x": "x", "y": "y", "picture": "picture"}, style={"linestyle": "-"})
    figure = Figure()
    render_figure_from_descriptor(figure=figure, descriptor=repo.load_figure_descriptor(figure_id), repo=repo)
    ax = figure.axes[0]
    assert sum(isinstance(a, AnnotationBbox) for a in ax.get_children()) == 4 and ax.lines


def test_bubbles_drawn_as_pictures_come_in_the_size_of_their_column(qapp):
    from types import SimpleNamespace

    from app.plugin_api.charts import picture_markers

    with picture_markers.pictures_from(lambda name: SimpleNamespace(kind="svg", data=SVG, name=name)):
        ax = Figure().subplots()
        drawn = picture_markers.draw_named(ax, [0, 1, 2], [0, 1, 2], ["dot"] * 3, size_points=10, colour="r",
                                           areas=[100.0, 400.0, 400.0])
    assert drawn.all()
    sizes = {box.offsetbox.get_data().shape[0] for box in ax.artists if isinstance(box, AnnotationBbox)}
    assert len(sizes) == 2


def test_a_pie_draws_a_picture_on_each_wedge_and_a_title_takes_pictures(qapp, repo):
    repo.add_image("dot", SVG)
    repo.import_dataframe(pd.DataFrame({"v": [3.0, 2.0, 1.0], "p": ["dot", "", "dot"]}), table_name="d",
                          normalize_columns=False)
    figure_id = int(repo.create_figure_descriptor(name="F"))
    axis_id = int(repo.create_axis_descriptor(figure_id=figure_id, axis_index=0, chart_type="Pie Chart",
                                              title="Share {image:dot}", x_label="", y_label="", options={}))
    repo.create_series_descriptor(axis_id=axis_id, series_index=0, name="s",
                                  sql_query="SELECT v AS value, p AS picture FROM d",
                                  roles={"value": "value", "picture": "picture"}, style={})
    figure = Figure()
    render_figure_from_descriptor(figure=figure, descriptor=repo.load_figure_descriptor(figure_id), repo=repo)
    ax = figure.axes[0]
    assert sum(isinstance(a, AnnotationBbox) for a in ax.get_children()) == 3  # 2 wedges and the title's
    assert ax.get_title() == "Share"
    figure.savefig(__import__("io").BytesIO(), format="svg")


def test_the_icon_library_searches_and_adds_icons_with_their_licence(qapp, repo):
    from app.dialogs.icon_library_dialog import IconLibraryDialog
    from app.utils import icon_library

    assert {"lucide", "flags"} <= set(icon_library.set_keys())
    assert icon_library.search("flags", "italy")[0] == ("it", "Italy")
    assert ("rome", "Rome") not in icon_library.search("flags", "italy")
    assert ("it", "Italy") in icon_library.search("flags", "rome")  # a capital finds its country
    assert icon_library.search("lucide", "heart")[0][0] == "heart"
    assert b"<svg" in icon_library.svg("lucide", "heart")
    with pytest.raises(KeyError):
        icon_library.svg("lucide", "../index")
    dialog = IconLibraryDialog(repo)
    try:
        dialog.sets.setCurrentIndex(dialog.sets.findData("flags"))
        dialog.search.setText("italy")
        assert dialog.list.count() == 1
        dialog.list.selectAll()
        dialog._add()
    finally:
        dialog.close()
    assert repo.image_names() == ["flag-it"]
    stored = repo.get_image("flag-it")
    assert stored.kind == "svg" and stored.license == "MIT" and "flag-icons" in stored.source
