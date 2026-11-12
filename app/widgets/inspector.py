"""Building blocks of the chart-properties inspector (dev/plans/chart_properties_ui_plan.txt).

One column read top to bottom, as Keynote, Numbers and Figma have, instead
of tabs of framed cards:

- SegmentedControl: the pages as one row of words, the chosen one filled.
  Words, not icons: five pictograms for Figure, Axis, Series, Animation and
  Overlays were not understood. A word too long for its segment is elided,
  its full text in the tooltip.
- InspectorPages: the segments over a stack of pages. It keeps the part of
  QTabWidget's interface the window and the tests use (count, widget,
  currentIndex, setCurrentIndex, tabText, currentChanged), so the pages
  inside did not have to change.
- InspectorSection: a bold title with a chevron over its rows, no box; open
  or closed is remembered per section in user.json ("inspector_sections").
- InspectorForm: the label/control grid of a section, labels in one column
  as wide as its longest label.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyleOptionToolButton,
    QStylePainter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.utils import config

SECTIONS_KEY = "inspector_sections"


class _Segment(QToolButton):
    """One word of a SegmentedControl: shrinks below its text by eliding it."""

    def __init__(self, text: str, parent: QWidget) -> None:
        super().__init__(parent)
        self._full_text = text
        self.setText(text)
        self.setCheckable(True)
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def full_text(self) -> str:
        return self._full_text

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        room = self.width() - 8
        option.text = self.fontMetrics().elidedText(self._full_text, Qt.TextElideMode.ElideRight, max(room, 0))
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, option)


class SegmentedControl(QFrame):
    """Exclusive words drawn as one control; emits the index chosen."""

    current_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("segmentedControl")
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.idClicked.connect(self.current_changed.emit)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def add_segment(self, text: str, tooltip: str = "") -> int:
        index = len(self._group.buttons())
        button = _Segment(text, self)
        button.setObjectName("segment")
        button.setToolTip(tooltip or text)
        self._group.addButton(button, index)
        self.layout().addWidget(button, 1)
        if index == 0:
            button.setChecked(True)
        return index

    def button(self, index: int) -> QToolButton | None:
        return self._group.button(index)

    def count(self) -> int:
        return len(self._group.buttons())

    def text(self, index: int) -> str:
        button = self._group.button(index)
        return button.full_text() if isinstance(button, _Segment) else ""

    def current_index(self) -> int:
        return self._group.checkedId()

    def set_current_index(self, index: int) -> None:
        button = self._group.button(index)
        if button is not None and not button.isChecked():
            button.setChecked(True)
            self.current_changed.emit(index)


class InspectorPages(QWidget):
    """A SegmentedControl over a QStackedWidget, with QTabWidget's names."""

    currentChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("inspectorPages")
        self._segments = SegmentedControl(self)
        self._stack = QStackedWidget(self)
        bar = QWidget(self)
        bar.setObjectName("inspectorSegmentsBar")
        bar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(8, 6, 8, 6)
        bar_layout.addWidget(self._segments)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(bar)
        self._header_layout = layout
        layout.addWidget(self._stack, 1)
        self._segments.current_changed.connect(self._show)

    def set_header(self, widget: QWidget) -> None:
        """*widget* (the selection line) between the segments and the pages."""
        self._header_layout.insertWidget(1, widget)

    def segments(self) -> SegmentedControl:
        return self._segments

    def addTab(self, page: QWidget, title: str) -> int:  # noqa: N802 - QTabWidget's name
        self._stack.addWidget(page)
        return self._segments.add_segment(title)

    def setTabToolTip(self, index: int, tooltip: str) -> None:  # noqa: N802
        button = self._segments.button(index)
        if button is not None:
            button.setToolTip(tooltip)

    def count(self) -> int:
        return self._stack.count()

    def widget(self, index: int) -> QWidget | None:
        return self._stack.widget(index)

    def currentWidget(self) -> QWidget | None:  # noqa: N802
        return self._stack.currentWidget()

    def currentIndex(self) -> int:  # noqa: N802
        return self._stack.currentIndex()

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        self._segments.set_current_index(index)
        self._show(index)

    def tabText(self, index: int) -> str:  # noqa: N802
        return self._segments.text(index)

    def _show(self, index: int) -> None:
        if 0 <= index < self._stack.count() and index != self._stack.currentIndex():
            self._stack.setCurrentIndex(index)
            self.currentChanged.emit(index)


class InspectorSection(QWidget):
    """A title row with a chevron over a body; no border, no ground of its own."""

    toggled = Signal(bool)

    def __init__(self, title: str, parent: QWidget | None = None, *, key: str, collapsed: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("inspectorSection")
        self._key = key
        remembered = config.get_section(SECTIONS_KEY).get(key)
        is_open = remembered if isinstance(remembered, bool) else not collapsed
        self._header = QToolButton(self)
        self._header.setObjectName("inspectorSectionTitle")
        self._header.setText(title)
        self._header.setCheckable(True)
        self._header.setChecked(is_open)
        self._header.setAutoRaise(True)
        self._header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._header.setIconSize(QSize(10, 10))
        # The system font at its normal size, one weight up: the platforms' own section headings.
        font = self._header.font()
        font.setWeight(QFont.Weight.Medium)
        self._header.setFont(font)
        self._header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._header.toggled.connect(self._on_toggled)
        self.body = QWidget(self)
        self.body.setObjectName("inspectorSectionBody")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 6)
        layout.setSpacing(4)
        layout.addWidget(self._header)
        layout.addWidget(self.body)
        self._apply(is_open)

    def title(self) -> str:
        return self._header.text()

    def is_open(self) -> bool:
        return self._header.isChecked()

    def set_open(self, is_open: bool) -> None:
        self._header.setChecked(is_open)

    def _apply(self, is_open: bool) -> None:
        from app.styles.style.widgets import _chevron_icon

        # A thin chevron before the title: right when closed, down when open (as Claude's own sections).
        self._header.setIcon(_chevron_icon(down=is_open, color=self._header.palette().color(QPalette.ColorRole.WindowText)))
        self.body.setVisible(is_open or self._forced_open)

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "_header"):
            self._apply(self._header.isChecked())  # the chevron follows a light / dark switch
        super().changeEvent(event)

    #: While a filter is on, a closed section shows its body anyway (its remembered state is not touched).
    _forced_open: bool = False

    def force_open(self, forced: bool) -> None:
        self._forced_open = forced
        self._apply(self._header.isChecked())

    def _on_toggled(self, is_open: bool) -> None:
        self._apply(is_open)
        sections = dict(config.get_section(SECTIONS_KEY))
        sections[self._key] = is_open
        config.set_section(SECTIONS_KEY, sections)
        self.toggled.emit(is_open)


class InspectorForm(QWidget):
    """Label and control rows; the label column as wide as its longest label."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(14, 0, 0, 0)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(6)
        self._grid.setColumnStretch(1, 1)
        self.rows: list[tuple[QLabel | None, QWidget]] = []

    def add_row(self, label: str, control: QWidget, tooltip: str = "") -> QLabel:
        row = self._grid.rowCount()
        caption = QLabel(label, self)
        caption.setObjectName("inspectorLabel")
        caption.setBuddy(control)
        if tooltip:
            caption.setToolTip(tooltip)
            if not control.toolTip():
                control.setToolTip(tooltip)
        self._grid.addWidget(caption, row, 0, Qt.AlignmentFlag.AlignVCenter)
        self._grid.addWidget(control, row, 1)
        self.rows.append((caption, control))
        return caption

    def set_row_visible(self, index: int, visible: bool) -> None:
        label, control = self.rows[index]
        if label is not None:
            label.setVisible(visible)
        control.setVisible(visible)

    def add_wide(self, control: QWidget) -> None:
        row = self._grid.rowCount()
        self._grid.addWidget(control, row, 0, 1, 2)
        self.rows.append((None, control))


class InspectorCard(InspectorSection):
    """What the page's cards were, as an inspector section: a title row over a body, no frame.

    ``card`` is the body, so the builders keep using ``section.card.layout()`` as they did on a TitledCard;
    open or closed is remembered under "<prefix>.<object name>".
    """

    def __init__(self, parent: QWidget | None, title: str, object_name: str = "", *, collapsible: bool = False,
                 collapsed: bool = False, prefix: str = "") -> None:
        prefix = prefix or ("figure" if object_name.startswith("figure") else "section")
        super().__init__(title, parent, key=f"{prefix}.{object_name or title}", collapsed=collapsed)
        if object_name:
            self.setObjectName(object_name)
        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

    @property
    def card(self) -> QWidget:
        return self.body


class InspectorCard(InspectorSection):
    """What the page's cards were, as an inspector section: a title row over a body, no frame.

    ``card`` is the body, so the builders keep using ``section.card.layout()`` as they did on a TitledCard;
    open or closed is remembered under "<prefix>.<object name>".
    """

    def __init__(self, parent: QWidget | None, title: str, object_name: str = "", *, collapsible: bool = False,
                 collapsed: bool = False, prefix: str = "") -> None:
        prefix = prefix or ("figure" if object_name.startswith("figure") else "section")
        super().__init__(title, parent, key=f"{prefix}.{object_name or title}", collapsed=collapsed)
        if object_name:
            self.setObjectName(object_name)
        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

    @property
    def card(self) -> QWidget:
        return self.body


class SelectionLine(QFrame):
    """What is being edited, as one line: the axis > the series, a menu on each.

    It replaces the combo at the top of the Axis page and the one at the top of the Series page, which stay
    (hidden) as the model and the signal source: a choice here sets the combo and sends its ``activated``, so
    everything that listened to the combo still hears it. Up / Down / Delete are the menu's last items and
    press the pages' own buttons.
    """

    def __init__(self, axis_combo, series_combo, axis_actions, series_actions, parent: QWidget | None = None, *,
                 note: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("selectionLine")
        self._axis_combo = axis_combo
        self._series_combo = series_combo
        self.axis_button = self._make_button("selectionAxis")
        self.series_button = self._make_button("selectionSeries")
        self._separator = QLabel(">", self)
        self._separator.setObjectName("selectionSeparator")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 2, 10, 2)
        outer.setSpacing(2)
        layout = QHBoxLayout()
        layout.setSpacing(4)
        layout.addWidget(self.axis_button, 1)
        layout.addWidget(self._separator, 0)
        layout.addWidget(self.series_button, 1)
        outer.addLayout(layout)
        if note is not None:  # "Also editing ..." (shift-click on the chart), below the line
            note.setParent(self)
            outer.addWidget(note)
        self._wire(self.axis_button, axis_combo, axis_actions)
        self._wire(self.series_button, series_combo, series_actions)
        for combo in (axis_combo, series_combo):
            combo.currentIndexChanged.connect(self.refresh)
            model = combo.model()
            for signal in (model.rowsInserted, model.rowsRemoved, model.modelReset, model.dataChanged):
                signal.connect(self.refresh)
        self.refresh()

    def _make_button(self, name: str) -> QToolButton:
        from PySide6.QtWidgets import QMenu

        button = QToolButton(self)
        button.setObjectName(name)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        button.setMenu(QMenu(button))
        return button

    def _wire(self, button: QToolButton, combo, actions: dict[str, QPushButton | QToolButton]) -> None:
        menu = button.menu()
        menu.aboutToShow.connect(lambda: self._fill(menu, combo, actions))

    def _fill(self, menu, combo, actions) -> None:
        menu.clear()
        for index in range(combo.count()):
            action = menu.addAction(combo.itemText(index))
            action.setCheckable(True)
            action.setChecked(index == combo.currentIndex())
            action.triggered.connect(lambda _checked=False, i=index: self._choose(combo, i))
        if actions:
            menu.addSeparator()
        for text, key in (("Up", "up"), ("Down", "down"), ("Delete", "delete")):
            source = actions.get(key)
            if source is not None:
                action = menu.addAction(source.toolTip() or source.text() or text)
                action.setEnabled(source.isEnabled())
                action.triggered.connect(lambda _checked=False, b=source: b.click())

    @staticmethod
    def _choose(combo, index: int) -> None:
        if index != combo.currentIndex():
            combo.setCurrentIndex(index)
        combo.activated.emit(index)

    def refresh(self, *_args) -> None:
        for button, combo, empty in ((self.axis_button, self._axis_combo, "No axis"),
                                     (self.series_button, self._series_combo, "No series")):
            text = combo.currentText() if combo.count() and combo.currentIndex() >= 0 else empty
            metrics = button.fontMetrics()
            button.setToolTip(text)
            button.setText(metrics.elidedText(text, Qt.TextElideMode.ElideRight, 140) + "  \u25be")


def _texts(widget: QWidget | None) -> str:
    """The words a widget and everything inside it show: captions, button texts and tooltips, lower case."""
    if widget is None:
        return ""
    found: list[str] = []
    for item in (widget, *widget.findChildren(QWidget)):
        found.append(item.toolTip())
        if isinstance(item, (QLabel, QAbstractButton)):  # not what the user typed in a field
            found.append(item.text())
    return " ".join(found).lower()


def _owner(widget: QWidget) -> InspectorSection | None:
    parent = widget.parentWidget()
    while parent is not None and not isinstance(parent, InspectorSection):
        parent = parent.parentWidget()
    return parent


def filter_page(page: QWidget, text: str) -> int:
    """Leave on *page* only the rows whose label or tooltip holds *text*, under the sections they belong to.

    A section whose title holds it stays whole; one with nothing left is hidden; a closed one shows its body
    while the filter is on (its remembered open / closed is not touched). An empty *text* puts everything
    back. Returns how many rows or sections matched.
    """
    needle = text.strip().lower()
    sections = page.findChildren(InspectorSection)
    forms = page.findChildren(InspectorForm)
    if not needle:
        for form in forms:
            for index in range(len(form.rows)):
                form.set_row_visible(index, True)
        for section in sections:
            section.force_open(False)
            section.setVisible(True)
        return 0
    shown: dict[int, bool] = {id(section): False for section in sections}
    for section in sections:
        if needle in section.title().lower():
            shown[id(section)] = True
    matched = 0
    for form in forms:
        owner = _owner(form)
        whole = owner is not None and needle in owner.title().lower()
        for index, (label, control) in enumerate(form.rows):
            hit = whole or needle in _texts(label) or needle in _texts(control)
            form.set_row_visible(index, hit)
            if hit and owner is not None:
                shown[id(owner)] = True
                matched += 1
    for section in sections:  # sections with no InspectorForm: found by what they hold
        if not section.findChildren(InspectorForm) and needle in _texts(section.body):
            shown[id(section)] = True
            matched += 1
    for section in reversed(sections):  # an outer section is shown when an inner one is
        if shown[id(section)]:
            outer = _owner(section)
            if outer is not None:
                shown[id(outer)] = True
    for section in sections:
        visible = shown[id(section)]
        section.setVisible(visible)
        section.force_open(visible)
    return matched
