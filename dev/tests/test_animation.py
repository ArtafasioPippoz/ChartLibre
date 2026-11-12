"""Animated charts: frames along a column or a function's parameter, each frame's rows, the GIF (todo I-03)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from matplotlib.figure import Figure

from app.data.sqlite_repo import SqliteRepo
from app.plugin_api.charts import animation as anim


@pytest.fixture
def repo(tmp_path: Path):
    built = SqliteRepo(db_path=tmp_path / "a.dhub")
    built.import_dataframe(pd.DataFrame({
        "year": [2001, 2000, 2002, 2000, 2001, 2002],
        "when": ["2024-03-01", "2024-01-01", "2024-02-01", "2024-01-01", "2024-03-01", "2024-02-01"],
        "group": ["b", "a", "c", "a", "b", "c"],
        "x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        "y": [1.0, 4.0, 9.0, 16.0, 25.0, 36.0],
    }), table_name="t", normalize_columns=False)
    yield built
    built.close()


def _figure(repo: SqliteRepo, options: dict | None = None) -> int:
    figure_id = int(repo.create_figure_descriptor(name="f", options=options or {}))
    axis_id = int(repo.create_axis_descriptor(figure_id=figure_id, axis_index=0, chart_type="Scatter Plot",
                                              title="", x_label="", y_label="", options={}))
    sql = repo.sql_with_row_id('SELECT "x" AS "x", "y" AS "y" FROM "t"')
    repo.create_series_descriptor(axis_id=axis_id, series_index=0, name="s", sql_query=sql,
                                  roles={"x": "x", "y": "y"}, style={})
    return figure_id


def test_frames_are_numbers_and_dates_in_order_and_categories_as_first_met(repo: SqliteRepo) -> None:
    assert repo.animation_frames(["t"], "year") == [2000, 2001, 2002]
    assert repo.animation_frames(["t"], "when") == ["2024-01-01", "2024-02-01", "2024-03-01"]
    assert repo.animation_frames(["t"], "group") == ["b", "a", "c"]
    assert repo.animation_frames(["t"], "missing") == []


@pytest.mark.parametrize(("mode", "index", "rows"), [
    (anim.EACH, 1, 2), (anim.CUMULATIVE, 1, 4), (anim.TRAILING, 2, 4), (anim.CUMULATIVE, 2, 6),
])
def test_each_frame_reads_its_rows(repo: SqliteRepo, mode: str, index: int, rows: int) -> None:
    figure_id = _figure(repo)
    descriptor = repo.load_figure_descriptor(figure_id)
    settings = anim.AnimationSettings(column="year", mode=mode, trail=2)
    values = anim.frames(repo, descriptor, settings)
    sql = anim.frame_filter(repo, settings, values, index)(descriptor.axes[0].series[0].sql_query)
    assert len(repo.query_df(sql)) == rows


def test_the_settings_go_through_the_figure_options(repo: SqliteRepo) -> None:
    settings = anim.AnimationSettings(column="year", mode=anim.TRAILING, trail=2, fps=60, loop=False)
    restored = anim.AnimationSettings.from_options({anim.OPTION_KEY: settings.to_options()})
    assert restored is not None
    assert (restored.column, restored.mode, restored.trail, restored.loop) == ("year", anim.TRAILING, 2, False)
    assert restored.fps == 30.0  # at most 30 frames a second
    assert anim.AnimationSettings.from_options({anim.OPTION_KEY: {"column": ""}}) is None
    assert anim.AnimationSettings.from_options({}) is None


def test_a_function_parameter_varies_in_the_query() -> None:
    from app.data.repo.function_sql import GridRange, function_sql, parse_function_sql

    sql = f'SELECT "x", "y" FROM ({function_sql("wave", {"a": 1.0, "b": 2.0}, GridRange(0, 1, 5))})'
    changed = anim.with_parameter(sql, "a", 0.25)
    query = parse_function_sql(changed)
    assert query is not None and query.parameters == {"a": 0.25, "b": 2.0}
    assert anim.with_parameter(sql, "c", 3.0) == sql  # no such parameter: as it was
    settings = anim.AnimationSettings(source=anim.PARAMETER, parameter="a", start=0.0, stop=1.0, steps=5)
    assert anim.frames(None, None, settings) == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert anim.caption(settings, [0.0, 0.25], 1) == "a = 0.25"


def test_a_frame_holds_the_limits_of_the_whole_data_and_says_its_value(repo: SqliteRepo) -> None:
    from app.plugin_api.charts.render_figure import render_figure_from_descriptor

    figure_id = _figure(repo)
    descriptor = repo.load_figure_descriptor(figure_id)
    settings = anim.AnimationSettings(column="year")
    values = anim.frames(repo, descriptor, settings)
    figure = Figure()
    render_figure_from_descriptor(figure=figure, descriptor=descriptor, repo=repo)
    limits = anim.axes_limits(figure)
    anim.render_frame(figure, descriptor, repo, settings, values, 0, limits)
    assert anim.axes_limits(figure) == limits
    assert [text.get_text() for text in figure.texts if text.get_gid() == anim.CAPTION_GID] == ["2000"]


def test_a_gif_of_every_frame(repo: SqliteRepo, tmp_path: Path) -> None:
    from PIL import Image

    figure_id = _figure(repo)
    descriptor = repo.load_figure_descriptor(figure_id)
    target = tmp_path / "a.gif"
    seen: list[int] = []
    assert anim.export_gif(target, descriptor, repo, anim.AnimationSettings(column="year"), size_in=(3, 2), dpi=50,
                           progress=lambda done, _total: seen.append(done) or True)
    assert seen == [1, 2, 3]
    with Image.open(target) as gif:
        assert gif.n_frames == 3


def test_stop_writes_no_gif(repo: SqliteRepo, tmp_path: Path) -> None:
    descriptor = repo.load_figure_descriptor(_figure(repo))
    target = tmp_path / "a.gif"
    assert not anim.export_gif(target, descriptor, repo, anim.AnimationSettings(column="year"), size_in=(3, 2),
                               dpi=50, progress=lambda done, _total: done < 2)
    assert not target.exists()


def test_a_sankey_cannot_be_played() -> None:
    from types import SimpleNamespace

    descriptor = SimpleNamespace(axes=[SimpleNamespace(name="Sankey Diagram"), SimpleNamespace(name="Scatter Plot")])
    assert anim.not_animatable(descriptor) == ["Sankey Diagram"]


# ----------------------------------------------------------------------
# Chart properties > Animation, in the window
# ----------------------------------------------------------------------
def _spin(qapp, seconds: float) -> None:
    import time

    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qapp.processEvents()


def test_the_animation_page_stores_the_settings_and_plays_the_chart(qapp, repo: SqliteRepo, tmp_path: Path) -> None:
    from app.main_window.main_window import MainWindow

    figure_id = _figure(repo)
    window = MainWindow(repo, repo.db_path)
    try:
        window.resize(1200, 760)
        window.show()
        window._left_panel.select("chart_properties")
        _spin(qapp, 0.6)
        control = window._properties_control
        titles = [control.tabText(index) for index in range(control.count())]
        assert titles.index("Animation") == titles.index("Series") + 1

        page = window._animation_widget
        page._enabled.setChecked(True)
        page._column.setCurrentIndex(page._column.findData("year"))
        page._apply()
        _spin(qapp, 0.5)
        stored = anim.AnimationSettings.from_options(repo.get_figure_options(figure_id))
        assert stored is not None and stored.column == "year"

        player = window._current_chart_panel().animation_player
        assert player.frame_count == 3 and page._slider.maximum() == 3  # three years, then All
        assert page._slider.isEnabled()
        player.go_to(0)
        assert page._frame_label.text() == "2000"
        panel = window._current_chart_panel()
        assert [t.get_text() for t in panel._figure.texts if t.get_gid() == anim.CAPTION_GID] == ["2000"]
        player.step(1)
        assert page._slider.value() == 1 and page._frame_label.text() == "2001"

        # Off: the figure is not animated any more, and the controls have nothing to play.
        page._enabled.setChecked(False)
        page._apply()
        _spin(qapp, 0.5)
        assert anim.AnimationSettings.from_options(repo.get_figure_options(figure_id)) is None
        assert not page._slider.isEnabled()
    finally:
        window.close()


def test_the_second_animation_demo_has_seven_playable_figures(tmp_path: Path) -> None:
    from dev.demo.demo_animation_more import build_more_animation_demo

    repo = SqliteRepo(db_path=build_more_animation_demo(tmp_path))
    try:
        figures = repo.load_figures_from_db()
        assert len(figures) == 7
        for figure_id, _name in figures:
            descriptor = repo.load_figure_descriptor(figure_id)
            settings = anim.AnimationSettings.from_options(descriptor.options)
            assert settings is not None and len(anim.frames(repo, descriptor, settings)) >= 24
    finally:
        repo.close()
