"""Predict with a saved model: a model of the project applied to a table, the predictions in a new table.

The model's columns are matched to the table's by name; a missing one is said before anything is written. The new
table holds the table's own columns and the model's (Prediction, and Prob(level) for a category); rows with a value
the model cannot read - an unseen level, a missing number - keep an empty prediction and are counted below.
"""
from __future__ import annotations

import re

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QLineEdit, QWidget

from app import analysis_api
from app.analysis import models
from app.data.sqlite_repo import SqliteRepo
from app.dialogs.two_panels_dialog_base import PanelDialog
from app.styles.style import load_icon, stdSizeAndlayout
from app.utils.i18n import _


class PredictDialog(PanelDialog):
    """Pick a saved model and a table; the predictions go to a new table."""

    #: Tables were written: the window reloads its list.
    applied = Signal()

    def __init__(self, repo: SqliteRepo, parent: QWidget | None = None, *, table: str | None = None) -> None:
        super().__init__(parent, title=_("Predict with a saved model"), icon=load_icon("nav_analysis"), size="small")
        self._repo = repo
        #: The table written by the last Apply, for the window to show.
        self.created_table_name: str | None = None

        card = self.add_card(_("Model and table"), "predictCard")
        form = QFormLayout()
        stdSizeAndlayout(form)
        self._model_combo = QComboBox(card)
        for row in repo.models():
            header = row["header"]
            self._model_combo.addItem(f"{row['name']} - {header.get('response', '')}", row["name"])
        self._table_combo = QComboBox(card)
        for name in [str(item) for item in repo.list_user_tables()["Table"]]:
            self._table_combo.addItem(name, name)
        if table and self._table_combo.findData(table) >= 0:
            self._table_combo.setCurrentIndex(self._table_combo.findData(table))
        self._name_edit = QLineEdit(card)
        form.addRow(_("Model"), self._model_combo)
        form.addRow(_("Table"), self._table_combo)
        form.addRow(_("New table"), self._name_edit)
        card.layout().addLayout(form)
        self._about = QLabel("", card)
        self._about.setWordWrap(True)
        self._about.setProperty("muted", True)
        card.layout().addWidget(self._about)
        self._result = QLabel("", card)
        self._result.setWordWrap(True)
        card.layout().addWidget(self._result)

        self._model_combo.currentIndexChanged.connect(self._refresh)
        self._table_combo.currentIndexChanged.connect(self._refresh)
        self._apply = self.add_action("apply", self.apply)
        self.add_action("close", self.reject)
        self._refresh()

    def _refresh(self) -> None:
        """What the model reads, whether the table has it, and a name for the new table."""
        name = self._model_combo.currentData()
        table = self._table_combo.currentData()
        self._result.setText("")
        if not name or not table:
            self._about.setText(_("This project has no saved model: keep one from an analysis that fits a model.")
                                if not name else "")
            self._apply.setEnabled(False)
            return
        header = next(row["header"] for row in self._repo.models() if row["name"] == name)
        needed = [feature["name"] for feature in header.get("features", [])]
        have = [str(column) for column in self._repo.get_columns(table)]
        missing = [column for column in needed if column not in have]
        self._about.setText(_("Reads: {columns}.").format(columns=", ".join(needed))
                            + (" " + _("Missing in the table: {columns}.").format(columns=", ".join(missing))
                               if missing else ""))
        self._apply.setEnabled(not missing)
        suggested = re.sub(r"\W+", "_", f"{table}_{name}").strip("_")
        if not self._name_edit.isModified():
            self._name_edit.setText(suggested)

    def apply(self) -> None:
        """Score the table, write the new table, say what could not be predicted."""
        name, table = self._model_combo.currentData(), self._table_combo.currentData()
        target = self._name_edit.text().strip()
        if not name or not table or not target:
            return
        existing = {str(item) for item in self._repo.list_user_tables(include_internal=True)["Table"]}
        stem, number = target, 2
        while target in existing:  # never over an existing table
            target, number = f"{stem}_{number}", number + 1
        try:
            self._repo.snapshot_for_undo([], label=f"Predict with {name}")
            analysis_api.ModelHandle(self._repo, name).predict(table, into=target)
        except analysis_api.AnalysisError as error:
            self._result.setText(str(error))
            return
        prediction = analysis_api.ModelHandle(self._repo, name).predict(table)
        notes = prediction.attrs.get("notes", [])
        self.created_table_name = target
        self._result.setText(_("{rows} row(s) written to {table}.").format(rows=len(prediction), table=target)
                             + ("\n" + "\n".join(notes) if notes else ""))
        self.applied.emit()
