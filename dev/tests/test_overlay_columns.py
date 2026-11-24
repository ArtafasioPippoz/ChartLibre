"""The overlays' tables in a narrow panel: column groups, never a horizontal scroll bar."""
from __future__ import annotations

from PySide6.QtCore import Qt

from app.widgets.chart_properties.overlay_properties import _ANNOTATION_COLS, OverlayPropertiesWidget


def _shown(table) -> list[str]:
    return [table.horizontalHeaderItem(i).text() for i in range(table.columnCount()) if not table.isColumnHidden(i)]


def test_a_narrow_panel_shows_a_group_of_columns_at_a_time(qapp) -> None:
    page = OverlayPropertiesWidget()
    table = page._annotations_table
    page._add_row(table, _ANNOTATION_COLS, {"x": 1.0, "y": 2.0, "text": "peak"})
    page.resize(320, 500)
    page.show()
    qapp.processEvents()
    groups = table.column_groups
    assert groups.grouped() and table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert _shown(table) == ["X", "Y", "Type", "Text"] and not table.verticalHeader().isHidden()
    groups._chooser.button(1).click()
    assert _shown(table) == ["Color", "Font", "Size"]
    assert sum(table.columnWidth(i) for i in range(table.columnCount()) if not table.isColumnHidden(i)) <= table.width()
    groups._chooser.button(2).click()
    assert _shown(table) == ["Kwargs JSON"]
    # Every value is still read, whatever is in sight.
    assert page._payload(table, _ANNOTATION_COLS)[0]["text"] == "peak"
    page.close()


def test_a_wide_panel_shows_the_whole_table(qapp) -> None:
    page = OverlayPropertiesWidget()
    page.resize(900, 500)
    page.show()
    qapp.processEvents()
    table = page._annotations_table
    assert not table.column_groups.grouped() and len(_shown(table)) == len(_ANNOTATION_COLS)
    assert table.column_groups._chooser.isHidden()
    page.close()
