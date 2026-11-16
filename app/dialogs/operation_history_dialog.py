"""How a table came to be: the operations recorded in the project (todo R-03).

Every Apply of a data operation is kept in ``__operations__`` (see
``app/data/repo/operations.py``); this shows the ones that read or wrote one
table - or, without a table, every one in the project - oldest first - what was run, on which series, with which entries, and
the report it gave - in the house report style, so it can be copied like
any other report.
"""
from __future__ import annotations

from app.styles.style import TidyMenu

from app.styles.style import field_label
import html
import re
from pathlib import Path
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QFileDialog,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from app import analysis_api
from app.data.repo.project import OperationRecord
from app.data.sqlite_repo import SqliteRepo
from app.dialogs.two_panels_dialog_base import PanelDialog
from app.styles.style import load_icon, mark_destructive_button
from app.utils import report_html
from app.utils.i18n import _
from app.utils.messages import ask
from app.widgets.html_results import HtmlResultsView, looks_like_html, plain_to_html


class OperationHistoryDialog(PanelDialog):
    """The recorded operations that read or wrote *table*; all of them when None."""

    def __init__(self, repo: SqliteRepo, table: str | None, parent: QWidget | None = None) -> None:
        super().__init__(parent, title=_("History of {table}").format(table=table) if table else _("Project history"),
                         icon=load_icon("operation_history"))
        self._repo = repo
        self._table = table
        card = self.add_card(_("History"), "operationHistoryCard", stretch=1)
        # One operation picked, as Python: its call copied, or kept as a function of the project.
        bar = QHBoxLayout()
        self._record_combo = QComboBox(card)
        self._record_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._copy_code_button = QPushButton(_("Copy as Python"), card)
        self._copy_code_button.setToolTip(_("The call that makes this analysis again; for all of them, a script"))
        self._copy_code_button.clicked.connect(self.copy_code)
        self._save_function_button = QPushButton(_("Save as function..."), card)
        self._save_function_button.setToolTip(
            _("Keep this analysis as a Python function of the project, to call from the workpad"))
        self._save_function_button.clicked.connect(self.save_as_function)
        self._record_combo.currentIndexChanged.connect(self._update_code_buttons)
        # The rest in a menu: settings as a file to keep and open, a script, the analysis run again.
        self._more_button = QPushButton(_("More..."), card)
        menu = TidyMenu(self._more_button)
        self._save_settings_action = menu.addAction(_("Save settings..."), self.save_settings)
        menu.addAction(_("Open settings..."), self.open_settings)
        menu.addAction(_("Export script..."), self.export_script)
        menu.addSeparator()
        self._rerun_action = menu.addAction(_("Run again"), self.run_again)
        self._more_button.setMenu(menu)
        bar.addWidget(self._record_combo, 1)
        bar.addWidget(self._copy_code_button)
        bar.addWidget(self._save_function_button)
        bar.addWidget(self._more_button)
        card.layout().addLayout(bar)
        self._view = HtmlResultsView(card)
        card.layout().addWidget(self._view, 1)
        self._reload()
        # Red and alone at the left: what it forgets cannot be brought back.
        self._delete_button = self.add_action(
            "delete", self._delete_history, left=True,
            presentation=(load_icon("delete"), _("Delete"), _("Forget the operations listed here")),
        )
        mark_destructive_button(self._delete_button)
        self.add_action("dismiss", self.reject)

    def _reload(self) -> None:
        self._records = self._repo.operations(table=self._table)
        self._view.setContent(history_html(self._table, self._records))
        if hasattr(self, "_delete_button"):
            self._delete_button.setEnabled(bool(self._records))
        self._record_combo.blockSignals(True)
        self._record_combo.clear()
        self._record_combo.addItem(_("All operations"), None)
        for record in self._records:
            self._record_combo.addItem(f"{record.id}. {record.operation}", record.id)
        self._record_combo.setCurrentIndex(self._record_combo.count() - 1 if self._records else 0)
        self._record_combo.blockSignals(False)
        self._update_code_buttons()

    def _picked(self) -> list[OperationRecord]:
        """The record picked, or all of them."""
        record_id = self._record_combo.currentData()
        return list(self._records) if record_id is None else [r for r in self._records if r.id == record_id]

    def _update_code_buttons(self) -> None:
        picked = self._picked()
        self._copy_code_button.setEnabled(bool(picked))
        single = self._record_combo.currentData() is not None
        runnable = bool(picked) and all(analysis_api.record_call(record) is not None for record in picked)
        self._save_function_button.setEnabled(single and runnable)
        self._save_settings_action.setEnabled(single and runnable)
        self._rerun_action.setEnabled(any(analysis_api.record_call(record) is not None for record in picked))

    def save_settings(self) -> None:
        """The picked operation's settings in a JSON file."""
        picked = self._picked()
        if len(picked) != 1:
            return
        name = re.sub(r"\W+", "_", picked[0].operation.lower()).strip("_") or "analysis"
        path, _filter = QFileDialog.getSaveFileName(self, _("Save settings"), f"{name}.json", "JSON (*.json)")
        if path:
            analysis_api.save_settings(path, picked[0])

    def open_settings(self) -> None:
        """An analysis' own window, filled from a settings file."""
        path, _filter = QFileDialog.getOpenFileName(self, _("Open settings"), "", "JSON (*.json)")
        if not path:
            return
        try:
            dialog = analysis_api.open_settings_dialog(self._repo, analysis_api.load_settings(path), self)
        except analysis_api.AnalysisError as error:
            QMessageBox.warning(self, _("Open settings"), str(error))
            return
        dialog.exec()
        self._reload()

    def export_script(self) -> None:
        """The picked operation (all of them) as a Python script."""
        path, _filter = QFileDialog.getSaveFileName(self, _("Export script"), "analyses.py", "Python (*.py)")
        if path:
            project = Path(str(self._repo.db_path)).name if getattr(self._repo, "db_path", None) else ""
            Path(path).write_text(analysis_api.history_script(self._picked(), project), encoding="utf-8")

    def run_again(self) -> None:
        """The picked operations run again on this project (all of them in order), after asking."""
        picked = [record for record in self._picked() if analysis_api.record_call(record) is not None]
        if not picked or QMessageBox.question(
                self, _("Run again"),
                _("Run {count} operation(s) again? Each writes its tables and figure anew.").format(count=len(picked)),
        ) != QMessageBox.StandardButton.Yes:
            return
        outcomes = analysis_api.run_records(self._repo, picked)
        failed = [str(outcome) for outcome in outcomes if isinstance(outcome, analysis_api.AnalysisError)]
        self._reload()
        if failed:
            QMessageBox.warning(self, _("Run again"), "\n".join(failed))

    def copy_code(self) -> None:
        """The picked operation's call (all of them: one a line) on the clipboard."""
        QApplication.clipboard().setText(analysis_api.history_code(self._picked()))

    def save_as_function(self) -> None:
        """Ask a name, then keep the picked operation as a Python function of the project."""
        picked = self._picked()
        if len(picked) != 1:
            return
        record = picked[0]
        name, accepted = QInputDialog.getText(self, _("Save as function"), field_label(_("Function name")),
                                              text=re.sub(r"\W+", "_", record.operation.lower()).strip("_"))
        name = name.strip()
        if not accepted or not name:
            return
        try:
            code = analysis_api.function_code(name, record)
        except analysis_api.AnalysisError as error:
            QMessageBox.warning(self, _("Save as function"), str(error))
            return
        if any(row["name"] == name for row in self._repo.analysis_functions()) and QMessageBox.question(
                self, _("Save as function"), _("A function called {name} exists. Replace it?").format(name=name),
        ) != QMessageBox.StandardButton.Yes:
            return
        self._repo.save_analysis_function(name, code, f"{record.operation} on {record.sources[0].get('table', '')}")

    def _delete_history(self) -> None:
        """Forget the listed operations, after asking; the tables they made stay."""
        if not self._records or not ask(self, "history.confirm_delete", count=len(self._records)):
            return
        self._repo.delete_operations([record.id for record in self._records])
        self._reload()


def _local_time(stamp: str) -> str:
    try:
        return datetime.fromisoformat(stamp).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return stamp


def _value(value: Any) -> str:
    if isinstance(value, float):
        return report_html.format_number(value)
    if isinstance(value, (list, tuple)):
        return html.escape(", ".join(str(item) for item in value))
    return html.escape(str(value))


def _record_section(record: OperationRecord) -> str:
    summary = report_html.summary_table(
        [
            (_("Applied"), _local_time(record.applied_at)),
            (_("Read"), ", ".join(str(source.get("name", "")) for source in record.sources)),
            (_("Wrote"), ", ".join(str(result.get("table", "")) for result in record.results)),
            (_("ChartLibre version"), record.app_version),
        ]
    )
    # The declared parameters when the operation has them; otherwise its
    # other entries (a model combo, a checkbox) are what it was run with.
    settings = record.parameters or record.entries
    parameters = report_html.table(
        [_("Setting"), _("Value")],
        [(html.escape(str(name)), _value(value)) for name, value in settings.items()],
        align=["left", "left"],
        empty_message=_("No settings recorded."),
    )
    call = analysis_api.record_call(record)
    code = report_html.raw_note(f"<pre>{html.escape(call)}</pre>") if call else ""
    report = ""
    if record.report.strip():
        report = report_html.raw_note(
            record.report if looks_like_html(record.report) else plain_to_html(record.report)
        )
    return report_html.section(f"{record.id}. {record.operation}", summary, parameters, code, report)


def history_html(table: str | None, records: Sequence[OperationRecord]) -> str:
    """The history page for *table*, or for the whole project when None."""
    title = _("History of {table}").format(table=table) if table else _("Project history")
    if not records:
        body = report_html.note(
            _("No operation has been applied to or from this table since the project began recording them.")
            if table else _("No operation has been applied in this project since it began recording them.")
        )
        return report_html.document(title, "", body)
    return report_html.document(
        title,
        _("{count} operation(s), oldest first").format(count=len(records)),
        *(_record_section(record) for record in records),
    )
