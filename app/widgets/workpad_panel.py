"""The SymPy workpad's panel: commands typed and run, what they gave, the names defined (app.workpad.engine)."""

from __future__ import annotations

import html
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.utils.i18n import _
from app.widgets.insert_helper import Function, InsertHelper
from app.widgets.nav_bar import NavPanel
from app.workpad.engine import UnsafeCommand, Workpad

_HELP = (
    "get(table, column) · get(table) · tables() · columns(table)<br>"
    "save(table, {'x': xs, 'y': ys}) - also put, store, write<br>"
    "plot('Scatter', x=xs, y=ys, group=g, title='...') · plot('Box Plot', table='T', y='col', group='col')<br>"
    "mean, std, median, minimum, maximum, count · everything in SymPy · Ctrl+Return runs"
)


#: The session's own words, for the Functions menu: (shown, written, what it does). "" is a separator.
_FUNCTIONS: tuple[Function, ...] = (
    ("get(table, column)", "get('', '')", "A column's values: numbers as an array, else a list"),
    ("get(table)", "get('')", "Every column of a table, as a dict"),
    ("tables()", "tables()", "The project's tables"),
    ("columns(table)", "columns('')", "A table's columns"),
    ("save(table, {...})", "save('', {'x': xs, 'y': ys})", "A new table from columns of values"),
    ("plot(type, x=, y=, group=)", "plot('Scatter', x=xs, y=ys)", "A chart of values, or of a table's columns"),
    ("", "", ""),
    ("mean(data)", "mean()", "The mean, missing values left out"),
    ("std(data)", "std()", "The standard deviation (n - 1)"),
    ("median(data)", "median()", "The median"),
    ("minimum(data)", "minimum()", "The smallest value"),
    ("maximum(data)", "maximum()", "The largest value"),
    ("count(data)", "count()", "How many values"),
    ("", "", ""),
    ("Analysis(name, table, columns)", "Analysis('', '', [])", "Run an analysis of the application"),
    ("analysis_names()", "analysis_names()", "The analyses there are"),
    ("describe_analysis(name)", "describe_analysis('')", "What an analysis reads and its parameters"),
    ("Chart(type, table, ...)", "Chart('', '')", "Draw a chart of a table"),
    ("Model(name).predict(table)", "Model('').predict('')", "Predict with a saved model"),
    ("models()", "models()", "The project's saved models"),
    ("functions()", "functions()", "The project's saved functions"),
)


class WorkpadPanel(NavPanel):
    """A SymPy session on the project; *repo()* is the open project."""

    #: The project changed (a table or a chart): the figures made, to show.
    project_changed = Signal(list)

    def __init__(self, parent: QWidget | None, *, repo: Callable[[], Any],
                 current_table: Callable[[], str | None] | None = None) -> None:
        super().__init__(parent)
        self._pad = Workpad(repo, changed=self.project_changed.emit)
        self._entries: list[str] = []
        self._history: list[str] = []

        self._transcript = QTextBrowser(self)
        self._transcript.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self._transcript.setMinimumHeight(120)
        self.add_frame(_("Session"), self._transcript, object_name="workpadSessionCard", stretch=1)

        box = QWidget(self)
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        self._helper = InsertHelper(box, repo=repo, functions=self._available_functions, quote=True,
                                   current_table=current_table)
        self._helper.insert.connect(self._insert)
        column.addWidget(self._helper)
        self._command = QPlainTextEdit(box)
        self._command.setPlaceholderText(_("e.g. m = get('Penguins', 'body_mass_g'); mean(m)"))
        self._command.setFixedHeight(self._command.fontMetrics().lineSpacing() * 4 + 12)
        column.addWidget(self._command)
        QShortcut(QKeySequence("Ctrl+Return"), self._command).activated.connect(self.run)
        row = QHBoxLayout()
        row.addStretch(1)
        clear = QPushButton(_("New session"), box)
        clear.clicked.connect(self.new_session)
        row.addWidget(clear)
        self._run_button = QPushButton(_("Run"), box)
        self._run_button.setDefault(True)
        self._run_button.clicked.connect(self.run)
        row.addWidget(self._run_button)
        column.addLayout(row)
        self.add_frame(_("Command"), box, object_name="workpadCommandCard")

        self._names = QTextBrowser(self)
        self._names.setMaximumHeight(110)
        self.add_frame(_("Names"), self._names, object_name="workpadNamesCard")
        self._render()

    def _available_functions(self) -> list[Function]:
        """The session's words, then the project's saved functions (each written as a call)."""
        offered = [(label, text, _(tip) if tip else "") for label, text, tip in _FUNCTIONS]
        try:
            saved = dict(self._pad.namespace["functions"]()) if "functions" in self._pad.namespace else {}
        except Exception:
            saved = {}
        if saved:
            offered.append(("", "", ""))
            offered.extend((f"{name}(...)", f"{name}()", str(description or "")) for name, description in
                           sorted(saved.items()))
        return offered

    def _insert(self, text: str) -> None:
        """A name chosen in the helper, at the cursor; inside a call's quotes or brackets when it has them."""
        self._command.insertPlainText(text)
        self._command.setFocus()

    def new_session(self) -> None:
        """Forget every name and the session's text."""
        self._pad.reset()
        self._entries.clear()
        self._render()

    def run(self, source: str | None = None) -> None:
        """Run the command typed (or *source*), and show what it gave."""
        text = (source if isinstance(source, str) else self._command.toPlainText()).strip()
        if not text:
            return
        entry = f"<pre style='margin:6px 0 0 0;color:#2563eb;'>&gt;&gt;&gt; {html.escape(text)}</pre>"
        try:
            printed, value = self._pad.run(text)
        except UnsafeCommand as error:
            entry += f"<pre style='margin:0;color:#b45309;'>{html.escape(str(error))}</pre>"
        except Exception as error:  # the user's command: its error is the answer
            entry += f"<pre style='margin:0;color:#dc2626;'>{html.escape(type(error).__name__)}: " \
                     f"{html.escape(str(error))}</pre>"
        else:
            if printed:
                entry += f"<pre style='margin:0;'>{html.escape(printed.rstrip())}</pre>"
            if value is not None:
                entry += f"<pre style='margin:0;'>{html.escape(_shown(value))}</pre>"
            if not isinstance(source, str):
                self._command.clear()
        self._history.append(text)
        self._entries.append(entry)
        self._render()

    def _render(self) -> None:
        intro = f"<p style='color:#6b7280;font-size:9pt;'>{_HELP}</p>"
        self._transcript.setHtml(intro + "".join(self._entries))
        bar = self._transcript.verticalScrollBar()
        bar.setValue(bar.maximum())
        rows = "".join(f"<tr><td><b>{html.escape(name)}</b></td><td>&nbsp;{html.escape(value)}</td></tr>"
                       for name, value in sorted(self._pad.names().items()))
        self._names.setHtml(f"<table>{rows}</table>" if rows else f"<i>{_('No names yet.')}</i>")


def _shown(value: Any) -> str:
    """*value* as the session shows it: SymPy's pretty print for an expression, else its text."""
    try:
        import sympy

        if isinstance(value, sympy.Basic | sympy.MatrixBase):
            return sympy.pretty(value, use_unicode=True)
    except Exception:
        pass  # SymPy cannot print it: its plain text
    return str(value)
