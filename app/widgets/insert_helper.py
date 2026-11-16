"""Tables, Columns, Functions: three drop-downs that write a name into the text being typed.

For the SymPy workpad and the assistant: nobody remembers how a table or a column is spelt, nor which
functions a session has. A choice is sent as text (``insert``) and the panel puts it at the cursor. The menus
are filled when they open, from the project as it is then.
"""
from __future__ import annotations

from app.styles.style import TidyMenu

from collections.abc import Callable, Sequence
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QMenu, QPushButton, QWidget

from app.logs.logger import applogger
from app.styles.style import load_icon
from app.utils.i18n import _

#: A function offered: what the menu shows, what is written, what it does (the item's tooltip) and, optionally,
#: its icon (an action id).
Function = tuple[str, str, str] | tuple[str, str, str, str]
#: Menus stay readable: a project with more than this shows the first ones.
MAX_TABLES, MAX_COLUMNS = 40, 80


class InsertHelper(QWidget):
    """A row of three menu buttons over a text box; *repo()* is the open project.

    The buttons are push buttons with a menu - the pull-down button of the Mac, with its chevron - not tool
    buttons. *current_table()* is the table selected in the window: with one, Columns lists only its columns.
    """

    #: The text to put at the cursor.
    insert = Signal(str)

    def __init__(self, parent: QWidget | None, *, repo: Callable[[], Any],
                 functions: Callable[[], Sequence[Function]], quote: bool = False,
                 current_table: Callable[[], str | None] | None = None) -> None:
        super().__init__(parent)
        self._repo, self._functions, self._quote = repo, functions, quote
        self._current_table = current_table
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.tables_button = self._button(_("Tables"), _("Write a table's name"), self._fill_tables)
        self.columns_button = self._button(_("Columns"), _("Write a column's name"), self._fill_columns)
        self.functions_button = self._button(_("Functions"), _("What can be used here"), self._fill_functions)
        for button in (self.tables_button, self.columns_button, self.functions_button):
            row.addWidget(button)
        row.addStretch(1)

    def _button(self, text: str, tooltip: str, fill: Callable[[QMenu], None]) -> QPushButton:
        button = QPushButton(self)
        button.setObjectName("insertHelperButton")
        button.setText(text)
        button.setToolTip(tooltip)
        menu = TidyMenu(button)
        menu.setToolTipsVisible(True)
        menu.aboutToShow.connect(lambda: self._refill(menu, fill))
        button.setMenu(menu)
        return button

    def _refill(self, menu: QMenu, fill: Callable[[QMenu], None]) -> None:
        menu.clear()
        try:
            fill(menu)
        except Exception:  # a project that cannot be read: an empty menu, said below
            applogger.exception("Could not fill the insert menu.")
        if menu.isEmpty():
            menu.addAction(_("Nothing yet")).setEnabled(False)

    def _name(self, name: str) -> str:
        return repr(name) if self._quote else name

    def table_names(self) -> list[str]:
        return [str(name) for name in self._repo().list_user_tables()["Table"]][:MAX_TABLES]

    def column_names(self, table: str) -> list[str]:
        return [str(name) for name in self._repo().get_columns(table) if not str(name).startswith("_")][:MAX_COLUMNS]

    def _add(self, menu: QMenu, label: str, text: str, tooltip: str = "", icon: str = "") -> None:
        action = menu.addAction(label)
        if icon:
            # An icon on every item where menus carry icons; on the Mac, as its own menus, none (TidyMenu).
            action.setIcon(load_icon(icon))
        if tooltip:
            action.setToolTip(tooltip)
        action.triggered.connect(lambda _checked=False, text=text: self.insert.emit(text))

    def _fill_tables(self, menu: QMenu) -> None:
        for table in self.table_names():
            self._add(menu, table, self._name(table), icon="database_info")

    def _fill_columns(self, menu: QMenu) -> None:
        tables = self.table_names()
        selected = self._current_table() if self._current_table is not None else None
        if selected in tables:  # a table is selected in the window: only its columns
            tables = [selected]
        for table in tables:
            # One table: its columns at once. Several: a menu a table, filled when it opens.
            target = menu if len(tables) == 1 else menu.addMenu(table)
            if target is menu:
                self._columns_of(target, table)
            else:
                target.aboutToShow.connect(lambda target=target, table=table: self._columns_of(target, table))

    def _columns_of(self, menu: QMenu, table: str) -> None:
        menu.clear()
        for column in self.column_names(table):
            self._add(menu, column, self._name(column), icon="column_info")

    def _fill_functions(self, menu: QMenu) -> None:
        for label, text, tooltip, *icon in self._functions():
            if not label:
                menu.addSeparator()
                continue
            self._add(menu, label, text, tooltip, icon[0] if icon else "function_creator")
