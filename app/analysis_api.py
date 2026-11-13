"""An analysis as a function call: its dialog driven without a window, the report and what it wrote handed back.

    result = run_analysis(repo, "Fit Y by X", "table", {"x": ["a"], "y": ["b"]}, {"degree": 2})
    result.report_html, result.report_text, result.tables, result.figures, result.operation_id

This is the engine the assistant's run_analysis tool used, taken out of it: the analysis dialogs stay the one
implementation, and everything that wants an analysis - the assistant, the SymPy workpad (workpad names Analysis,
Chart), a saved function, a script - goes through here. Nothing is shown: the dialog is built, filled, run as its OK
runs it (one Undo step, the history row, the tables, the figure) and closed.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

#: How long an analysis may run before the call gives up waiting.
ANALYSIS_TIMEOUT_S = 600


class AnalysisError(ValueError):
    """An analysis that could not be run, in the words of its dialog (the problems it listed) or of the lookup."""


@dataclass
class AnalysisResult:
    """What one run gave back."""

    name: str
    table: str
    roles: dict[str, list[str]]
    parameters: dict[str, Any]
    model: str
    report_html: str
    report_text: str
    #: The tables it wrote, by name; the figures it drew, by id.
    tables: list[str] = field(default_factory=list)
    figures: list[int] = field(default_factory=list)
    #: Its row of the project's history (__operations__), None when the run recorded none.
    operation_id: int | None = None
    seconds: float = 0.0


def closest(name: str, known: Iterable[str]) -> str:
    """The one of *known* meant by *name* - "box_plot" for Box Plot, "body mass" for body_mass_g; else *name*."""
    def words(text: str) -> list[str]:
        return [word for word in re.split(r"[^a-z0-9]+", str(text).lower()) if word]

    wanted = words(name)
    choices = list(known)
    for test in (lambda have: have == wanted,
                 lambda have: [w for w in have if w not in ("plot", "chart")] == [w for w in wanted
                                                                                  if w not in ("plot", "chart")],
                 lambda have: bool(wanted) and all(word in have for word in wanted)):
        found = [choice for choice in choices if test(words(choice))]
        if len(found) == 1:
            return found[0]
    return name


def plain_text(html: str) -> str:
    """A report's HTML as text."""
    from PySide6.QtGui import QTextDocument

    document = QTextDocument()
    document.setHtml(html)
    return document.toPlainText().strip()


def catalogue() -> dict[str, Any]:
    """The table analyses by name: their discovery entries."""
    from app.scanners.data_operation_scanner import data_operations, reads_roles

    return {str(entry["value"]): entry for entry in data_operations if reads_roles(entry)}


def analysis_names() -> list[str]:
    return sorted(catalogue())


def find_analysis(name: str) -> tuple[str, Any]:
    """(the analysis' own name, its entry) for a name written loosely, or an AnalysisError that lists the real ones."""
    known = catalogue()
    found = closest(name, known)
    if found not in known:
        raise AnalysisError(f"No analysis named '{name}'. They are: {', '.join(sorted(known))}.")
    return found, known[found]


def find_table(repo: Any, table: str) -> str:
    """The table named (loosely), or the error that names the real ones."""
    names = [str(name) for name in repo.list_user_tables()["Table"]]
    found = closest(table, names)
    if found not in names:
        raise AnalysisError(f"No table named '{table}'. Tables: {', '.join(names) or 'none'}.")
    return found


def find_columns(repo: Any, table: str, names: Iterable[str]) -> list[str]:
    """The columns named (loosely), or the error that names the real ones."""
    known = [str(name) for name in repo.get_columns(table) if name not in ("Hide", "Selected")]
    found = [closest(name, known) for name in names]
    wrong = [name for name in found if name not in known]
    if wrong:
        raise AnalysisError(f"Not columns of {table}: {', '.join(wrong)}. Columns: {', '.join(known)}.")
    return found


def _list_of_columns(value: Any) -> list[str]:
    """Columns as a list, also when written as text: "['a', 'b']" or "a, b"."""
    if isinstance(value, str):
        return [part.strip(" '\"") for part in value.strip("[] ").split(",") if part.strip(" '\"")]
    return [str(item) for item in value]


def run_analysis(repo: Any, analysis: str, table: str, roles: Mapping[str, Any] | None = None,
                 parameters: Mapping[str, Any] | None = None, *, model: str = "", draw_on: str = "new_figure",
                 current_figure: Callable[[], int | None] = lambda: None,
                 keep_waiting: Callable[[], bool] = lambda: True,
                 timeout: float = ANALYSIS_TIMEOUT_S) -> AnalysisResult:
    """Run *analysis* on *table* as its dialog's OK would, and return what it gave.

    *roles* maps each role of the analysis (see describe_analysis) to its columns; *parameters* are its parameter
    values by name; *model* one of its models; *draw_on* where the figure goes ("new_figure", or what its
    destination list offers). *current_figure* gives the figure the window shows (for a destination on it);
    *keep_waiting* lets a caller cancel a long run. Raises AnalysisError for what is wrong with the request.
    """
    from PySide6.QtWidgets import QApplication

    from app.scanners.data_operation_scanner import import_class_from_file

    name, entry = find_analysis(analysis)
    table = find_table(repo, table)
    casting = {str(key): find_columns(repo, table, _list_of_columns(columns))
               for key, columns in dict(roles or {}).items()}
    values = dict(parameters or {})
    tables_before = set(repo.list_user_tables()["Table"].astype(str))
    operations_before = {record.id for record in repo.operations()}
    cls = import_class_from_file(entry)
    if cls is None:  # its file went, or did not load: the log says why
        raise AnalysisError(f"The analysis '{name}' could not be loaded; the log says why.")
    started = time.monotonic()
    dialog = cls(repo=repo, table=table)
    try:
        if dialog.reads_chart():  # the dialog remembers it was last used on a chart: here, a table is named
            dialog.source_table_radio.setChecked(True)
            dialog._load_tables(table)
        if dialog.table != table:
            raise AnalysisError(f"No table named '{table}'.")
        dialog.current_figure_id = current_figure()
        dialog.roles_widget.set_casting(casting)
        for form in dialog.parameter_forms():
            form.set_values(values)
        if model and getattr(dialog, "model_combo", None) is not None:
            index = dialog.model_combo.findData(model)
            if index < 0:
                raise AnalysisError(f"'{model}' is not one of {name}'s models.")
            dialog.model_combo.setCurrentIndex(index)
        combo = getattr(dialog, "destination_combo", None)
        if combo is not None and combo.findData(draw_on) >= 0:
            combo.setCurrentIndex(combo.findData(draw_on))
        problems = dialog.problems()
        if problems:
            raise AnalysisError("; ".join(problems))
        dialog.ok()
        deadline = time.monotonic() + timeout
        while dialog.job_running and time.monotonic() < deadline and keep_waiting():
            QApplication.processEvents()
            time.sleep(0.01)
        if dialog.job_running:
            dialog.stop()
            raise RuntimeError("The analysis was stopped before it finished.")
        report_html = str(getattr(dialog.results_widget(), "_html", "") or "")
        figures = list(dialog.created_figure_ids)
    finally:
        dialog.close()
    written = sorted(set(repo.list_user_tables()["Table"].astype(str)) - tables_before)
    new_operations = [record.id for record in repo.operations() if record.id not in operations_before]
    return AnalysisResult(
        name=name, table=table, roles=casting, parameters=values, model=model, report_html=report_html,
        report_text=plain_text(report_html), tables=written, figures=[int(figure) for figure in figures],
        operation_id=new_operations[-1] if new_operations else None, seconds=time.monotonic() - started)
