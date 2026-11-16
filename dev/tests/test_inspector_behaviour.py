"""The inspector's behaviour: the page chosen is remembered, an empty filter says so, the segments take the keys."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from app.main_window.main_window import MainWindow
from app.data.sqlite_repo import SqliteRepo
from app.utils import config
from app.widgets.inspector import InspectorSection, filter_page


def _window(qapp, tmp_path):
    repo = SqliteRepo(db_path=tmp_path / "i.dhub")
    window = MainWindow(repo, tmp_path / "i.dhub")
    window.resize(1200, 760)
    window.show()
    window._left_panel.select("chart_properties")
    qapp.processEvents()
    return window


def test_the_page_chosen_is_remembered(qapp, tmp_path) -> None:
    window = _window(qapp, tmp_path)
    try:
        window._properties_control.setCurrentIndex(3)
        assert config.get_value("inspector_page") == 3
    finally:
        window._properties_control.setCurrentIndex(0)
        window.close()
    assert config.get_value("inspector_page") == 0  # user.json: left as it was


def test_a_filter_with_no_match_says_so_and_clearing_brings_everything_back(qapp, tmp_path) -> None:
    window = _window(qapp, tmp_path)
    try:
        control = window._properties_control
        control.setCurrentIndex(0)
        page = window._figure_widget
        window._property_filter.setText("zzzqqq")
        assert not window._no_property_label.isHidden()
        assert not any(section.isVisibleTo(page) for section in page.findChildren(InspectorSection))
        window._property_filter.setText("")
        assert window._no_property_label.isHidden()
        assert all(section.isVisibleTo(page) for section in page.findChildren(InspectorSection))
        window._property_filter.setText("dpi")
        assert window._no_property_label.isHidden()  # DPI is on the Figure page
        window._property_filter.setText("")
    finally:
        window.close()


def test_the_arrow_keys_move_between_the_segments(qapp, tmp_path) -> None:
    window = _window(qapp, tmp_path)
    try:
        control = window._properties_control
        control.setCurrentIndex(0)
        segments = control.segments()
        first = segments.button(0)
        assert first.focusPolicy() & Qt.FocusPolicy.TabFocus
        QTest.keyClick(first, Qt.Key.Key_Right)
        assert segments.current_index() == 1 and control.currentIndex() == 1
        QTest.keyClick(segments.button(1), Qt.Key.Key_End)
        assert segments.current_index() == segments.count() - 1
        QTest.keyClick(segments.button(segments.count() - 1), Qt.Key.Key_Left)
        assert segments.current_index() == segments.count() - 2
    finally:
        window._properties_control.setCurrentIndex(0)
        window.close()
