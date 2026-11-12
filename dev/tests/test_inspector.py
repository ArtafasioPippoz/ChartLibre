"""The inspector's building blocks: segments, sections, form."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLabel, QLineEdit

from app.utils import config
from app.widgets import inspector


@pytest.fixture
def user_json(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USER_CONFIG_PATH", tmp_path / "user.json")
    yield tmp_path / "user.json"


def test_pages_switch_from_segments_and_keep_tab_names(qapp):
    pages = inspector.InspectorPages()
    for title in ("Figure", "Axis", "Series"):
        pages.addTab(QLabel(title), title)
    seen = []
    pages.currentChanged.connect(seen.append)
    assert pages.count() == 3 and pages.currentIndex() == 0
    pages.segments().button(2).click()
    assert pages.currentIndex() == 2 and pages.tabText(2) == "Series" and seen == [2]
    pages.setCurrentIndex(1)
    assert pages.segments().current_index() == 1 and pages.currentWidget().text() == "Axis"


def test_segments_fit_a_narrow_panel(qapp):
    pages = inspector.InspectorPages()
    for title in ("Figure", "Axis", "Series", "Animation", "Overlays"):
        pages.addTab(QLabel(title), title)
    pages.resize(240, 400)
    pages.show()
    qapp.processEvents()
    assert pages.minimumSizeHint().width() <= 240
    assert all(pages.segments().button(i).width() > 20 for i in range(5))
    pages.close()


def test_section_opens_closes_and_remembers(qapp, user_json):
    section = inspector.InspectorSection("Line", key="series.line")
    assert section.is_open()
    section.set_open(False)
    assert section.body.isHidden()
    assert config.get_section(inspector.SECTIONS_KEY) == {"series.line": False}
    again = inspector.InspectorSection("Line", key="series.line")
    assert not again.is_open()
    closed = inspector.InspectorSection("Query", key="series.query", collapsed=True)
    assert not closed.is_open()


def test_form_label_column_fits_its_longest_label(qapp):
    form = inspector.InspectorForm()
    form.add_row("Width", QLineEdit())
    label = form.add_row("A rather long label", QLineEdit(), tooltip="Explained")
    form.resize(400, 100)
    form.show()
    qapp.processEvents()
    assert label.width() >= label.sizeHint().width()
    assert form.rows[1][1].toolTip() == "Explained"
    form.close()


def test_the_find_box_leaves_the_rows_that_have_the_words(qapp) -> None:
    from PySide6.QtWidgets import QCheckBox, QLineEdit, QVBoxLayout, QWidget

    from app.widgets.inspector import InspectorForm, InspectorSection, filter_page

    page = QWidget()
    layout = QVBoxLayout(page)
    line = InspectorSection("Line", page, key="test.find.line")
    marker = InspectorSection("Marker", page, key="test.find.marker", collapsed=True)
    for section in (line, marker):
        layout.addWidget(section)
        QVBoxLayout(section.body)
    forms = []
    for section, rows in ((line, (("Width", QLineEdit()), ("Colour", QLineEdit()))),
                          (marker, (("Size", QLineEdit()), ("Filled", QCheckBox("Fill the marker"))))):
        form = InspectorForm(section.body)
        section.body.layout().addWidget(form)
        for label, control in rows:
            form.add_row(label, control, "tip for " + label.lower())
        forms.append(form)
    page.show()

    assert filter_page(page, "width") == 1
    assert not forms[0].rows[1][1].isVisibleTo(page) and forms[0].rows[0][1].isVisibleTo(page)
    assert not marker.isVisibleTo(page)  # nothing left in it

    filter_page(page, "fill")  # a word in a control's own text; the closed section shows its body meanwhile
    assert marker.isVisibleTo(page) and forms[1].rows[1][1].isVisibleTo(page) and not line.isVisibleTo(page)
    assert not marker.is_open()  # the remembered state is untouched

    filter_page(page, "marker")  # a section title keeps the section whole
    assert all(control.isVisibleTo(page) for _label, control in forms[1].rows)

    filter_page(page, "")
    assert line.isVisibleTo(page) and forms[0].rows[1][1].isVisibleTo(page) and not marker.body.isVisibleTo(page)


def test_filtering_shrinks_the_form_to_the_rows_left(qapp) -> None:
    from PySide6.QtWidgets import QLineEdit

    from app.widgets.inspector import InspectorForm

    form = InspectorForm()
    for name in ("DPI", "Width", "Height", "Border"):
        form.add_row(name, QLineEdit())
    form.show()
    full = form.sizeHint().height()
    for index in (1, 2, 3):
        form.set_row_visible(index, False)
    assert form.sizeHint().height() < full * 0.5
    for index in (1, 2, 3):
        form.set_row_visible(index, True)
    assert form.sizeHint().height() == full
