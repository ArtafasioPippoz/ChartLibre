"""Selected points on a chart (Settings > Charts: style and size) and the context menu's "Deselect all"."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from app.data.sqlite_repo import SqliteRepo
from app.utils import config
from app.widgets.chart_panel import ChartPanel


def _panel(tmp_path: Path, marker_size: float | None = None) -> tuple[SqliteRepo, ChartPanel]:
    repo = SqliteRepo(db_path=tmp_path / "p.dhub")
    x = np.arange(10, dtype=float)
    repo.import_dataframe(pd.DataFrame({"a": x, "b": x * 2.0}), table_name="t", normalize_columns=False)
    figure_id = repo.create_figure_descriptor(name="c")
    axis_id = repo.create_axis_descriptor(figure_id=figure_id, axis_index=0, chart_type="Scatter Plot",
                                          title="c", x_label="x", y_label="y", options={})
    style = {} if marker_size is None else {"markersize": marker_size}
    repo.create_series_descriptor(axis_id=axis_id, series_index=0, name="s", sql_query='SELECT "a" AS x, "b" AS y FROM "t"',
                                  roles={"x": "x", "y": "y"}, style=style)
    panel = ChartPanel(repo, figure_id)
    panel.resize(600, 400)
    panel.ensure_rendered()
    return repo, panel


def _chosen(monkeypatch: pytest.MonkeyPatch, style: str = "bold", size: int = 100) -> None:
    values = {config.SELECTED_STYLE_KEY: style, config.SELECTED_SIZE_KEY: size}
    monkeypatch.setattr(config, "get_value", lambda name, default=None: values.get(name, default))


def _selected(panel: ChartPanel) -> Any:
    (collection,) = [a for a in panel._canvas.figure.axes[0].collections if a.get_label() == panel.SELECTED_ROWS_LABEL]
    return collection


def _series(panel: ChartPanel) -> Any:
    return next(a for a in panel._canvas.figure.axes[0].collections if a.get_label() != panel.SELECTED_ROWS_LABEL)


def test_the_preferences_read_back_and_a_wrong_value_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    _chosen(monkeypatch, "ring", 150)
    assert config.selected_points_style() == "ring" and config.selected_points_size() == 150
    _chosen(monkeypatch, "sparkles", 99999)
    assert config.selected_points_style() == "bold" and config.selected_points_size() == config.SELECTED_SIZE_RANGE[1]
    monkeypatch.setattr(config, "get_value", lambda name, default=None: "many" if name == config.SELECTED_SIZE_KEY else default)
    assert config.selected_points_size() == 100


def test_bold_selected_points_are_the_series_own_marker_size_but_darker(qapp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _chosen(monkeypatch, "bold", 100)
    repo, panel = _panel(tmp_path, marker_size=5.0)
    try:
        repo.select_rows("t", [3, 4])
        panel.show_selected_rows()
        marks, series = _selected(panel), _series(panel)
        assert len(marks.get_offsets()) == 2
        assert np.allclose(marks.get_sizes(), series.get_sizes()[0])  # the same marker size: not a big ring
        series.update_scalarmappable()
        assert marks.get_facecolor()[0][:3] != pytest.approx(series.get_facecolor()[0][:3])
        assert marks.get_facecolor()[0][3] == 1.0 and marks.get_linewidths()[0] > series.get_linewidths()[0]
    finally:
        panel.deleteLater()
        repo.close()


def test_the_size_setting_scales_the_diameter_and_the_ring_style_stays_a_hollow_circle(qapp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, panel = _panel(tmp_path, marker_size=5.0)
    try:
        repo.select_rows("t", [3])
        base = 25.0
        _chosen(monkeypatch, "bold", 200)
        panel.show_selected_rows()
        assert np.allclose(_selected(panel).get_sizes(), base * 4)  # twice the diameter, four times the area
        _chosen(monkeypatch, "ring", 100)
        panel.show_selected_rows()
        ring = _selected(panel)
        assert ring.get_facecolor().size == 0 and ring.get_sizes()[0] > base  # hollow, wider than the marker
        _chosen(monkeypatch, "fill", 100)
        panel.show_selected_rows()
        assert np.allclose(_selected(panel).get_sizes(), base)
    finally:
        panel.deleteLater()
        repo.close()


def test_deselect_all_clears_the_rows_the_rings_and_tells_the_others(qapp, tmp_path: Path) -> None:
    repo, panel = _panel(tmp_path)
    try:
        told: list[list[str]] = []
        panel.rows_selected.connect(told.append)
        assert not panel.has_selected_rows()
        repo.select_rows("t", [2, 3, 4])
        panel.show_selected_rows()
        assert panel.has_selected_rows() and _selected(panel)
        assert panel.deselect_all() is True
        assert repo.selected_row_ids("t") == [] and told == [["t"]]
        assert not [a for a in panel._canvas.figure.axes[0].collections if a.get_label() == panel.SELECTED_ROWS_LABEL]
        assert panel.deselect_all() is False  # nothing left to do
    finally:
        panel.deleteLater()
        repo.close()


def test_the_context_menu_offers_deselect_all_only_while_something_is_selected(qapp, tmp_path: Path) -> None:
    repo, panel = _panel(tmp_path)
    try:
        axes = panel._canvas.figure.axes[0]
        px, py = axes.transData.transform((4.0, 8.0))
        height = panel._canvas.get_width_height(physical=True)[1]
        from PySide6.QtCore import QPoint

        pos = panel._canvas.mapTo(panel, QPoint(int(px), int(height - py)))

        def texts() -> list[str]:
            menu = panel.context_menu_for(pos)
            return [a.text() for a in menu.actions()]

        assert "Deselect all" not in texts()
        repo.select_rows("t", [4])
        assert "Deselect all" in texts()
    finally:
        panel.deleteLater()
        repo.close()


def test_settings_show_and_save_the_selected_points_options(qapp, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.dialogs import settings_dialog

    written: dict[str, Any] = {}
    monkeypatch.setattr(settings_dialog, "set_value", lambda name, value: written.__setitem__(name, value))
    _chosen(monkeypatch, "ring", 130)
    dialog = settings_dialog.SettingsDialog()
    try:
        assert dialog._selected_style_combo.currentData() == "ring" and dialog._selected_size_spin.value() == 130
        dialog._selected_style_combo.setCurrentIndex(dialog._selected_style_combo.findData("fill"))
        dialog._selected_size_spin.setValue(80)
        dialog._save()
        assert written[config.SELECTED_STYLE_KEY] == "fill" and written[config.SELECTED_SIZE_KEY] == 80
    finally:
        dialog.deleteLater()
