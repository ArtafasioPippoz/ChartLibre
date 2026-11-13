"""SQL workpad, in ChartLibre Developer: SQL on a project file, writing on a copy until Apply.

It was a page of the app's rail; it is a tool for people who write SQL against the project's own tables, so it
lives here, where a project file is picked (the same SqlWorkpadPanel and SqlSession as before).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.data.sqlite_repo import SqliteRepo
from app.widgets.sql_workpad_panel import SqlWorkpadPanel


class SqlWorkpadDialog(QDialog):
    """Pick a project, then run SQL on it; Apply keeps the changes, closing throws the copy away."""

    def __init__(self, parent: QWidget | None = None, path: Path | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SQL workpad")
        self.resize(760, 800)
        self._repo: SqliteRepo | None = None

        top = QHBoxLayout()
        open_button = QPushButton("Open project...", self)
        open_button.clicked.connect(self._choose)
        self.path_label = QLabel("No project open", self)
        self.path_label.setProperty("muted", True)
        top.addWidget(open_button)
        top.addWidget(self.path_label, 1)

        self.panel = SqlWorkpadPanel(self, repo=lambda: self._repo)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.panel, 1)
        if path is not None:
            self.open_project(path)

    def _choose(self) -> None:
        name, _filter = QFileDialog.getOpenFileName(self, "Open a project", str(Path.home()), "Projects (*.dhub)")
        if name:
            self.open_project(Path(name))

    def open_project(self, path: Path) -> None:
        """Work on the project file *path* (the previous one's copy is thrown away)."""
        self.panel.discard()
        if self._repo is not None:
            self._repo.close()
        self._repo = SqliteRepo(db_path=Path(path))
        self.path_label.setText(str(path))

    def done(self, result: int) -> None:  # noqa: N802 - Qt's name
        self.panel.discard()  # its copy, never kept unasked
        if self._repo is not None:
            self._repo.close()
            self._repo = None
        super().done(result)
