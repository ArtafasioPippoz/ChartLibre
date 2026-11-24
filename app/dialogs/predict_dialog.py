"""Predict with a saved model: a model of the project applied to a table, the predictions in a new table.

The model's columns are matched to the table's by name; a missing one is said before anything is written. The new
table holds the table's own columns and the model's (Prediction, and Prob(level) for a category); rows with a value
the model cannot read - an unseen level, a missing number - keep an empty prediction and are counted below.

The project's models are also kept in order here: renamed, deleted, exported to a file (.clmodel) and imported from
one. An imported pickled model runs only after this computer has accepted it (asked at the first Apply).
"""
from __future__ import annotations

import re

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from app import analysis_api
from app.analysis import models
from app.data.sqlite_repo import SqliteRepo
from app.dialogs.two_panels_dialog_base import PanelDialog
from app.styles.style import load_icon, mark_destructive_button, stdSizeAndlayout
from app.utils.i18n import _
from app.utils.messages import ask


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
        self._fill_models()
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
        # The models themselves: renamed, deleted, sent to a file, taken from one.
        manage = QHBoxLayout()
        stdSizeAndlayout(manage)
        self._rename_button = QPushButton(_("Rename…"), card)
        self._delete_button = mark_destructive_button(QPushButton(_("Delete"), card))
        self._export_button = QPushButton(_("Export…"), card)
        self._import_button = QPushButton(_("Import..."), card)
        self._import_button.setToolTip(_("Add a model from a file to this project"))
        for button, slot in ((self._rename_button, self._rename_model), (self._delete_button, self._delete_model),
                             (self._export_button, self._export_model), (self._import_button, self._import_model)):
            button.clicked.connect(slot)
            manage.addWidget(button)
        manage.addStretch(1)
        card.layout().addLayout(manage)
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

    def _fill_models(self, select: str | None = None) -> None:
        """The project's models in the combo, *select* (or the one that was) chosen."""
        keep = select or self._model_combo.currentData()
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        for row in self._repo.models():
            self._model_combo.addItem(f"{row['name']} - {row['header'].get('response', '')}", row["name"])
        if keep and self._model_combo.findData(keep) >= 0:
            self._model_combo.setCurrentIndex(self._model_combo.findData(keep))
        self._model_combo.blockSignals(False)

    def _rename_model(self) -> None:
        name = self._model_combo.currentData()
        if not name:
            return
        new, accepted = QInputDialog.getText(self, _("Rename"), _("Name"), text=str(name))
        if not accepted or not new.strip() or new.strip() == name:
            return
        try:
            new = models.rename_model(self._repo, str(name), new)
        except models.ModelError as error:
            self._result.setText(str(error))
            return
        self._fill_models(new)
        self._refresh()

    def _delete_model(self) -> None:
        name = self._model_combo.currentData()
        if not name or not ask(self, "model.confirm_delete", name=name):
            return
        self._repo.delete_model(str(name))
        self._fill_models()
        self._refresh()

    def _export_model(self) -> None:
        name = self._model_combo.currentData()
        if not name:
            return
        path, _filter = QFileDialog.getSaveFileName(self, _("Export…"), f"{name}{models.FILE_SUFFIX}",
                                                    f"ChartLibre model (*{models.FILE_SUFFIX})")
        if not path:
            return
        try:
            written = models.export_model(self._repo, str(name), path)
        except (models.ModelError, OSError) as error:
            self._result.setText(str(error))
            return
        self._result.setText(_("Written to {path}.").format(path=written))

    def _import_model(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, _("Import..."), "",
                                                    f"ChartLibre model (*{models.FILE_SUFFIX})")
        if not path:
            return
        try:
            name = models.import_model(self._repo, path)
        except (models.ModelError, OSError) as error:
            self._result.setText(str(error))
            return
        self._fill_models(name)
        self._refresh()

    def _trusted(self, name: str) -> bool:
        """True when the model may run here: portable, made here, or accepted now (asked once)."""
        if not models.needs_trust(self._repo, name):
            return True
        kind = next((row["kind"] for row in self._repo.models() if row["name"] == name), "")
        if not ask(self, "model.trust", name=name, kind=kind):
            return False
        models.trust_model(self._repo, name)
        return True

    def _refresh(self) -> None:
        """What the model reads, whether the table has it, and a name for the new table."""
        name = self._model_combo.currentData()
        table = self._table_combo.currentData()
        self._result.setText("")
        for button in (self._rename_button, self._delete_button, self._export_button):
            button.setEnabled(bool(name))
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
        if not name or not table or not target or not self._trusted(str(name)):
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
