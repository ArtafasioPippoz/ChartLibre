"""Database Info: the few facts about the file that the project's own information does not give.

Its size on disk and how many tables and rows it holds, with the Optimize DB action. Path, author and dates are
in Project information; the inventory of tables (the app's own included) with a preview of their rows is a
developer's tool (dev/developer/tables_inventory.py), and the person's own tables are on the Tables page.

A plain embeddable QWidget, not a QDialog: it sits in MainWindow's Project page (see
main_window._create_developer_page), with its own Optimize DB action.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.data.sqlite_repo import SqliteRepo
from app.logs.logger import applogger
from app.styles.style import (
    TitledCard,
    create_action_button,
    stdSizeAndlayout,
)
from app.utils.i18n import _


def _human_size(num_bytes: int) -> str:
    """Return *num_bytes* as "12.3 MB" - the units a person actually reads."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


class DatabaseInfoPanel(QWidget):
    """Size and contents of the connected database, with Optimize DB."""

    def __init__(self, repo: SqliteRepo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._repo = repo

        root = QVBoxLayout(self)
        stdSizeAndlayout(root)

        self._titled_card = TitledCard(self, _("Database Info"), "databaseInfoCard")
        self._card = self._titled_card.card
        self._card_layout = self._card.layout()

        self._form_host = QWidget(self._card)
        self._form_layout = QFormLayout(self._form_host)
        stdSizeAndlayout(self._form_layout)
        self._card_layout.addWidget(self._form_host)
        self._build_form()

        root.addWidget(self._titled_card, 0)

    def set_repo(self, repo: SqliteRepo) -> None:
        """Point the panel at a newly-opened database and refresh everything."""
        self._repo = repo
        self._build_form()

    def _build_form(self) -> None:
        """(Re)build the rows for the current repo: size, and what it holds."""
        while self._form_layout.rowCount():
            self._form_layout.removeRow(0)
        self._form_layout.addRow(_("Size on disk:"), self._selectable_label(self._db_size_text()))
        try:
            info = self._repo.database_pragma_info()
        except Exception:
            applogger.exception("Could not read database PRAGMA info.")
            return
        self._form_layout.addRow(
            _("Tables:"),
            self._selectable_label(
                _("{tables} table(s), {rows} row(s) total").format(
                    tables=f"{info.table_count:,}", rows=f"{info.total_rows:,}"
                )
            ),
        )
        if info.reclaimable_bytes:
            self._form_layout.addRow(
                _("Reclaimable:"),
                self._selectable_label(_("{amount} by Optimize DB").format(amount=_human_size(info.reclaimable_bytes))),
            )

    def _selectable_label(self, text: str) -> QLabel:
        label = QLabel(text, self)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setWordWrap(True)
        return label

    def _db_size_text(self) -> str:
        try:
            return _human_size(self._repo.db_path.stat().st_size)
        except OSError:
            return _("unknown")
