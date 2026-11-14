"""Project tables: every table of a project file - the app's own "__...__" ones too - with a preview of its rows.

This was the Database Info list in the app's Project panel; a person using the app has the Tables page, and only
somebody working on the code wants the inventory with the internal tables, so it lives here. Read-only: the file
is opened as any project is (its undo store and WAL files are made and removed as usual).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.data.sqlite_repo import SqliteRepo
from app.widgets.table_preview import style_data_table

PREVIEW_ROWS = 200


class TablesInventoryDialog(QDialog):
    """Pick a project, see its tables (rows, link) and the first rows of the one selected."""

    def __init__(self, parent: QWidget | None = None, path: Path | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Project tables")
        self.resize(900, 560)
        self._repo: SqliteRepo | None = None

        top = QHBoxLayout()
        self.path_label = QLabel("No project open", self)
        self.path_label.setProperty("muted", True)
        open_button = QPushButton("Open project...", self)
        open_button.clicked.connect(self._choose)
        top.addWidget(open_button)
        top.addWidget(self.path_label, 1)

        self.tables = QTableWidget(0, 3, self)
        self.tables.setHorizontalHeaderLabels(["Table", "Rows", "Linked"])
        header = self.tables.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tables.verticalHeader().setVisible(False)
        self.tables.setAlternatingRowColors(True)
        self.tables.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tables.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tables.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tables.itemSelectionChanged.connect(self._show_preview)

        self.preview = QTableWidget(0, 0, self)
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        style_data_table(self.preview)  # as the Data page's table
        self.caption = QLabel("", self)
        self.caption.setProperty("muted", True)
        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.preview, 1)
        right_layout.addWidget(self.caption)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self.tables)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(splitter, 1)
        if path is not None:
            self.open_project(path)

    def _choose(self) -> None:
        name, _filter = QFileDialog.getOpenFileName(self, "Open a project", str(Path.home()), "Projects (*.dhub)")
        if name:
            self.open_project(Path(name))

    def open_project(self, path: Path) -> None:
        """Show the tables of the project file *path*."""
        if self._repo is not None:
            self._repo.close()
        self._repo = SqliteRepo(db_path=Path(path))
        self.path_label.setText(str(path))
        frame = self._repo.list_user_tables(include_internal=True)
        records = frame.to_dict("records")
        self.tables.setRowCount(len(records))
        for row, record in enumerate(records):
            name = str(record.get("Table", ""))
            self.tables.setItem(row, 0, QTableWidgetItem(name))
            rows_item = QTableWidgetItem(f"{self._repo.row_count(name):,}")
            rows_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tables.setItem(row, 1, rows_item)
            self.tables.setItem(row, 2, QTableWidgetItem("Yes" if record.get("has_link") else ""))
        if records:
            self.tables.selectRow(0)

    def _show_preview(self) -> None:
        row = self.tables.currentRow()
        item = self.tables.item(row, 0) if row >= 0 else None
        if item is None or self._repo is None:
            return
        name = item.text()
        frame = self._repo.query_df(f'SELECT * FROM "{name}" LIMIT {PREVIEW_ROWS}')
        self.preview.setRowCount(len(frame.index))
        self.preview.setColumnCount(len(frame.columns))
        self.preview.setHorizontalHeaderLabels([str(column) for column in frame.columns])
        for r, values in enumerate(frame.itertuples(index=False)):
            for c, value in enumerate(values):
                self.preview.setItem(r, c, QTableWidgetItem("" if value is None else str(value)))
        total = self._repo.row_count(name)
        self.caption.setText(f"{name}: the first {len(frame.index):,} of {total:,} rows")

    def done(self, result: int) -> None:  # noqa: N802 - Qt's name
        if self._repo is not None:
            self._repo.close()
            self._repo = None
        super().done(result)
