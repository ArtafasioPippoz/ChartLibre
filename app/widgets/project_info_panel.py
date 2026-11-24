"""Project info, in the Project panel: who made the project, when, what it is about, its sources.

Edits the project's own ``__project_info__`` entries (see app/data/repo/project_info.py): author, notes and
bibliographic references. The creation date and the preview are shown, not edited. Every change is saved a
moment after it is made (no Apply, no modal window); the author typed here is also remembered for this
computer, so a new project starts with it already filled in.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, QDateTime, QLocale, QSize, Qt, QTime, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.data.sqlite_repo import (
    DatabaseError,
    SqliteRepo,
    dump_references,
    parse_references,
)
from app.logs.logger import applogger
from app.styles.style import TitledCard, create_action_button, mark_editor_panel, stdSizeAndlayout
from app.utils.config import get_value, set_value
from app.utils.i18n import _

#: user.json key: the author last typed, offered to the next new project.
AUTHOR_SETTING = "project_author"


def readable_date(iso: str, *, with_time: bool = True) -> str:
    """An ISO 8601 timestamp as local date (and time) written as this computer writes them, or the text
    unchanged. Not strftime's %x: without a C locale set it is the American 10/25/26, in an Italian window."""
    try:
        moment = datetime.fromisoformat(iso).astimezone()
    except (TypeError, ValueError):
        return iso
    day = QDate(moment.year, moment.month, moment.day)
    if not with_time:
        return QLocale().toString(day, QLocale.FormatType.ShortFormat)
    return QLocale().toString(QDateTime(day, QTime(moment.hour, moment.minute, moment.second)),
                              QLocale.FormatType.ShortFormat)


def default_author() -> str:
    """The author remembered on this computer, or an empty string."""
    return str(get_value(AUTHOR_SETTING, "") or "")


def _human_size(num_bytes: int) -> str:
    """*num_bytes* as "12.3 MB" - the units a person actually reads."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


class ProjectInfoPanel(QWidget):
    """Author, creation date, notes, references and preview of the open project, edited in place."""

    saved = Signal()

    #: The preview, at the size the Load demo dialog shows it, halved.
    PREVIEW_SIZE = QSize(160, 100)

    def __init__(self, repo: SqliteRepo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._repo = repo
        self._loading = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(600)
        self._timer.timeout.connect(self.save)

        root = QVBoxLayout(self)
        stdSizeAndlayout(root)
        titled = TitledCard(self, _("Project information"), "projectInfoCard")
        card = titled.card
        card_layout = card.layout()
        form = QFormLayout()
        stdSizeAndlayout(form)

        self.file_label = QLabel("", card)
        self.file_label.setProperty("muted", True)
        self.file_label.setWordWrap(True)
        self.file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(_("File"), self.file_label)

        self.author_edit = QLineEdit(card)
        self.author_edit.setPlaceholderText(_("Your name, or your group's"))
        form.addRow(_("Author"), self.author_edit)

        self.created_label = QLabel("", card)
        self.created_label.setToolTip(_("When the project was created. A project older than this record "
                                        "shows the date its file was created."))
        form.addRow(_("Created"), self.created_label)

        self.notes_edit = QPlainTextEdit(card)
        self.notes_edit.setPlaceholderText(_("What the project is about, where the data came from, what is left to do..."))
        self.notes_edit.setMinimumHeight(54)
        self.notes_edit.setMaximumHeight(64)
        form.addRow(_("Notes"), self.notes_edit)
        # What the file holds: its size, the tables and rows in it, what Optimize could give back.
        self.size_label = QLabel("", card)
        self.size_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(_("Size on disk"), self.size_label)
        self.contents_label = QLabel("", card)
        self.contents_label.setWordWrap(True)
        form.addRow(_("Tables"), self.contents_label)
        card_layout.addLayout(form)

        # The first figure, as the project's preview shows it.
        self.preview_label = QLabel(card)
        self.preview_label.setFixedSize(self.PREVIEW_SIZE)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setToolTip(_("The project's first figure, drawn again each time the project is saved."))
        card_layout.addWidget(self.preview_label, 0, Qt.AlignmentFlag.AlignHCenter)

        references = TitledCard(self, _("References"), "projectReferencesCard")
        refs_layout = references.card.layout()
        self.references_table = QTableWidget(0, 3, references.card)
        self.references_table.setHorizontalHeaderLabels([_("Citation"), _("DOI"), _("Link")])
        self.references_table.setToolTip(_("The sources of the data and methods: a citation, and if it has them a DOI "
                                           "(10.xxxx/...) and a web link. Reports list them with their links."))
        header = self.references_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(1, 110)
        header.resizeSection(2, 110)
        self.references_table.verticalHeader().setVisible(False)
        self.references_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.references_table.setMinimumHeight(64)
        self.references_table.setMaximumHeight(88)
        mark_editor_panel(self.references_table)
        self.references_table.setAlternatingRowColors(True)
        refs_layout.addWidget(self.references_table, 1)
        reference_buttons = QHBoxLayout()
        stdSizeAndlayout(reference_buttons)
        create_action_button(parent=references.card, action_id="add",
                             action=lambda: self._append_reference({}, edit=True), layout=reference_buttons)
        create_action_button(parent=references.card, action_id="delete", action=self._remove_references,
                             layout=reference_buttons)
        reference_buttons.addStretch(1)
        refs_layout.addLayout(reference_buttons)

        root.addWidget(titled)
        root.addWidget(references)

        self.set_repo(repo)
        for signal in (self.author_edit.textEdited, self.notes_edit.textChanged,
                       self.references_table.itemChanged):
            signal.connect(self._changed)

    def set_repo(self, repo: SqliteRepo) -> None:
        """Show *repo*'s project information (a project was opened or created)."""
        self._timer.stop()
        self._repo = repo
        info = repo.project_info()
        self._loading = True
        try:
            self.file_label.setText(str(repo.db_path or ""))
            self.author_edit.setText(info.get("author", ""))
            self.created_label.setText(readable_date(info.get("created", "")) or _("unknown"))
            self.notes_edit.setPlainText(info.get("notes", ""))
            self._show_database_facts()
            self.references_table.setRowCount(0)
            for entry in parse_references(info.get("references")):
                self._append_reference(entry)
            self._show_preview(info.get("preview_path"))
        finally:
            self._loading = False

    def _show_database_facts(self) -> None:
        """The file's size and its tables and rows (Database info, folded into this card)."""
        try:
            size = _human_size(Path(str(self._repo.db_path)).stat().st_size)
        except OSError:
            size = _("unknown")
        self.size_label.setText(size)
        try:
            info = self._repo.database_pragma_info()
            text = _("{tables} table(s), {rows} row(s) total").format(tables=f"{info.table_count:,}",
                                                                     rows=f"{info.total_rows:,}")
            if info.reclaimable_bytes:
                text += " - " + _("{amount} could be reclaimed (Preferences > Advanced)").format(
                    amount=_human_size(info.reclaimable_bytes))
        except Exception:
            applogger.exception("Could not read database PRAGMA info.")
            text = ""
        self.contents_label.setText(text)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self._show_database_facts()  # tables came and went since it was last seen

    def _changed(self, *_args) -> None:
        if not self._loading:
            self._timer.start()

    def focus_author(self) -> None:
        """A new project: the cursor in the Author field."""
        self.author_edit.setFocus()

    def _show_preview(self, entry: str | None) -> None:
        from app.utils.project_preview import project_preview_bytes

        self.preview_label.clear()
        picture = QPixmap()
        png = self._repo.project_preview() or (
            project_preview_bytes(Path(str(self._repo.db_path)), entry) if self._repo.db_path else None
        )
        if png:
            picture.loadFromData(png)
        if picture.isNull():
            self.preview_label.hide()  # nothing to show until the project is saved: no empty box
            return
        self.preview_label.show()
        ratio = self.devicePixelRatioF()
        scaled = picture.scaled(self.PREVIEW_SIZE * ratio, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(ratio)
        self.preview_label.setPixmap(scaled)

    def _append_reference(self, entry: dict[str, str], *, edit: bool = False) -> None:
        row = self.references_table.rowCount()
        self.references_table.insertRow(row)
        item = QTableWidgetItem(entry.get("citation", ""))
        self.references_table.setItem(row, 0, item)
        for column, key in enumerate(("doi", "url"), start=1):
            self.references_table.setItem(row, column, QTableWidgetItem(entry.get(key, "")))
        if edit:
            self.references_table.setCurrentCell(row, 0)
            self.references_table.editItem(item)

    def _remove_references(self) -> None:
        rows = sorted({index.row() for index in self.references_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.references_table.removeRow(row)

    def references(self) -> list[dict[str, str]]:
        """The references as typed, rows with no citation left out."""
        result = []
        for row in range(self.references_table.rowCount()):
            values = {}
            for column, key in enumerate(("citation", "doi", "url")):
                item = self.references_table.item(row, column)
                text = item.text().strip() if item is not None else ""
                if text:
                    values[key] = text
            if values.get("citation"):
                result.append(values)
        return result


    def save(self) -> None:
        """Store the entries now (the timer does it a moment after a change)."""
        self._timer.stop()
        author = self.author_edit.text().strip()
        try:
            self._repo.set_project_info({
                "author": author,
                "notes": self.notes_edit.toPlainText(),
                "references": dump_references(self.references()),
            })
        except DatabaseError as exc:
            applogger.exception("Could not save the project info: %s", exc)
            return
        if author:
            set_value(AUTHOR_SETTING, author)
        self.saved.emit()
