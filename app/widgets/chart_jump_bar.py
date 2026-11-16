"""The strip above the chart: back/forward arrows and the current chart's name.

It replaces the chart tabs' own bar, the way a recent Mac app's toolbar
does (Xcode's jump bar, Finder's back/forward): the sidebar lists every
chart, and this strip says which one is showing, steps to the one above or
below, and pops up the whole list from the name. On macOS the empty part
of the strip moves the window, as a native toolbar does.
"""
from __future__ import annotations

from app.styles.style import TidyMenu

from collections.abc import Sequence

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMenu,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from app.styles.style import IS_MACOS, action_presentation
from app.utils.i18n import _ as tr

#: A little taller than the macOS traffic lights' strip, so the 28 px
#: arrow buttons have room above and below them.
JUMP_BAR_HEIGHT: int = 36


def jump_arrow(parent: QWidget, action_id: str, callback, *, tooltip: str = "") -> QToolButton:
    """A back or forward arrow as the charts' bar draws it (chart_previous / chart_next's icon, no frame):
    the one look of "the previous one, the next one" wherever the window has it - Column Info too."""
    icon, text, default_tooltip = action_presentation(action_id)
    button = QToolButton(parent)
    button.setObjectName("chartJumpArrow")
    button.setIcon(icon)
    button.setIconSize(QSize(20, 20))
    button.setAutoRaise(True)
    button.setAccessibleName(text)
    button.setToolTip(tooltip or default_tooltip)
    button.setFixedSize(28, 28)
    button.clicked.connect(callback)
    return button


class AxisStepper(QWidget):
    """‹ › to the previous and the next axis, drawn as the charts' own arrows: on the Axis, Series and Overlays
    pages, whichever is shown moves the axis of all three."""

    step = Signal(int)  # -1 the previous axis, +1 the next

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        self._previous = jump_arrow(self, "chart_previous", lambda: self.step.emit(-1), tooltip=tr("Previous axis"))
        self._next = jump_arrow(self, "chart_next", lambda: self.step.emit(1), tooltip=tr("Next axis"))
        row.addWidget(self._previous)
        row.addWidget(self._next)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_position(self, index: int, count: int) -> None:
        """Enable only the arrows that have somewhere to go."""
        self._previous.setEnabled(index > 0)
        self._next.setEnabled(0 <= index < count - 1)

    @staticmethod
    def beside(title: QWidget, stepper: AxisStepper) -> None:
        """Put *stepper* at the right end of *title*'s line, in the layout that holds the title."""
        layout = title.parentWidget().layout() if title.parentWidget() is not None else None
        if layout is None:
            return
        index = layout.indexOf(title)
        layout.removeWidget(title)
        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(title, 1)
        line.addWidget(stepper)
        layout.insertLayout(index, line)


class ChartJumpBar(QFrame):
    """‹ › and a menu button naming the current chart."""

    previous_requested = Signal()
    next_requested = Signal()
    chart_chosen = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chartJumpBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(JUMP_BAR_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(2)

        self._previous = self._arrow("chart_previous", self.previous_requested.emit)
        self._next = self._arrow("chart_next", self.next_requested.emit)
        layout.addWidget(self._previous)
        layout.addWidget(self._next)
        layout.addSpacing(6)

        self._title = QToolButton(self)
        self._title.setObjectName("chartJumpTitle")
        self._title.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._title.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._title.setAutoRaise(True)
        self._title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._title.setToolTip(action_presentation("chart_jump")[2])
        self._menu = TidyMenu(self._title)
        self._title.setMenu(self._menu)
        layout.addWidget(self._title, 0)
        layout.addStretch(1)

        self.set_charts([], -1)

    def _arrow(self, action_id: str, callback) -> QToolButton:
        return jump_arrow(self, action_id, callback)

    def set_charts(self, names: Sequence[str], current: int) -> None:
        """Show *names* in the menu and *current* as the title."""
        self._menu.clear()
        for index, name in enumerate(names):
            action = self._menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(index == current)
            action.triggered.connect(lambda _checked=False, i=index: self.chart_chosen.emit(i))
        has_current = 0 <= current < len(names)
        self._title.setText(f"{names[current]}  " if has_current else "")
        self._title.setVisible(has_current)
        self._previous.setEnabled(has_current and current > 0)
        self._next.setEnabled(has_current and current < len(names) - 1)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if IS_MACOS and event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)
