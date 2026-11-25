"""Function helper: a formula in, the analyses and charts that suit it out, as workpad commands.

Opened from the SymPy workpad. The user types a formula, picks the variable and the interval, ticks what to
ask of it, reads the commands that result and sends them to the workpad's command box (app.workpad.function_helper).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from app.utils.i18n import _
from app.workpad import equation_helper, function_helper
from app.workpad import function_helper as helper


class FunctionHelperDialog(QDialog):
    """Formula, variable, interval and point; a list of suggestions to tick; the commands they make."""

    #: The commands to write in the workpad.
    commands = Signal(str)

    def __init__(self, parent=None, *, text: str = "", equations: bool = False) -> None:
        super().__init__(parent)
        # The same window for a formula (function_helper) and for equations (equation_helper): one kit each.
        self._kit = equation_helper if equations else function_helper
        self.setWindowTitle(_("Equation helper") if equations else _("Function helper"))
        self.resize(720, 560)  # fits a 1280x720 screen
        self._formula = None
        self._suggestions: dict[str, function_helper.Suggestion] = {}
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.formula_edit = QLineEdit(text, self)
        self.formula_edit.setPlaceholderText(
            _("e.g. x^2 - 3x = -2   x + y = 3; x - y = 1   x^2 > 4   y' + 2y = sin(x); y(0) = 1") if equations
            else _("e.g. sin(x)*exp(-x/5)   x^3 - 2x + 1   1/(x-1)"))
        self.formula_edit.textChanged.connect(self._read)
        form.addRow(_("Equations") if equations else _("Formula f ="), self.formula_edit)
        self.variable_combo = QComboBox(self)
        self.variable_combo.currentTextChanged.connect(self._rebuild)
        form.addRow(_("Variable"), self.variable_combo)
        interval = QHBoxLayout()
        self.low_spin, self.high_spin, self.point_spin = (self._spin(value) for value in (-10.0, 10.0, 0.0))
        for caption, spin in ((_("from"), self.low_spin), (_("to"), self.high_spin), (_("start near") if equations else _("at the point"), self.point_spin)):
            interval.addWidget(QLabel(caption, self))
            interval.addWidget(spin)
        interval.addStretch(1)
        form.addRow(_("Interval"), interval)
        layout.addLayout(form)
        self.message = QLabel("", self)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

        self.list = QListWidget(self)
        self.list.setMinimumHeight(180)
        self.list.itemChanged.connect(self._preview)
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        for caption, kind in ((_("All analyses"), helper.ANALYSIS), (_("All charts"), helper.CHART)):
            button = QPushButton(caption, self)
            button.clicked.connect(lambda _c=False, kind=kind: self._tick(kind))
            row.addWidget(button)
        none = QPushButton(_("None"), self)
        none.clicked.connect(lambda: self._tick(""))
        row.addWidget(none)
        row.addStretch(1)
        layout.addLayout(row)

        self.preview = QPlainTextEdit(self)
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(120)
        layout.addWidget(self.preview, 1)
        buttons = QDialogButtonBox(self)
        self.write_button = buttons.addButton(_("Write in the workpad"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Close).clicked.connect(self.reject)
        self.write_button.clicked.connect(self._write)
        layout.addWidget(buttons)
        self._read()

    def _spin(self, value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox(self)
        spin.setRange(-1e9, 1e9)
        spin.setDecimals(4)
        spin.setValue(value)
        spin.valueChanged.connect(self._rebuild)
        return spin

    # -- reading the formula -------------------------------------------------

    def _read(self) -> None:
        try:
            self._formula = self._kit.parse(self.formula_edit.text())
            self.message.setText("")
        except function_helper.BadFormula as error:
            self._formula = None
            self.message.setText(_(str(error)))
        symbols = self._formula.symbols if self._formula else ()
        previous = self.variable_combo.currentText()
        self.variable_combo.blockSignals(True)
        self.variable_combo.clear()
        self.variable_combo.addItems(list(symbols) or ["x"])
        chosen = previous if previous in symbols else (self._kit.default_variable(self._formula) if self._formula else "x")
        self.variable_combo.setCurrentText(chosen)
        self.variable_combo.blockSignals(False)
        self._rebuild()

    def _rebuild(self) -> None:
        """The list for the formula as it is now; what was ticked stays ticked."""
        ticked = {key for key, item in self._items() if item.checkState() == Qt.CheckState.Checked}
        self.list.blockSignals(True)
        self.list.clear()
        self._suggestions = {}
        if self._formula is not None:
            found = self._kit.suggestions(self._formula, self.variable_combo.currentText() or "x",
                                       self.low_spin.value(), self.high_spin.value(), self.point_spin.value())
            for kind, title in ((helper.ANALYSIS, _("Analyses")), (helper.CHART, _("Charts"))):
                heading = QListWidgetItem(title)
                heading.setFlags(Qt.ItemFlag.NoItemFlags)
                font = heading.font()
                font.setBold(True)
                heading.setFont(font)
                self.list.addItem(heading)
                for suggestion in (s for s in found if s.kind == kind):
                    self._suggestions[suggestion.key] = suggestion
                    item = QListWidgetItem(_(suggestion.label))
                    item.setToolTip(_(suggestion.tip))
                    item.setData(Qt.ItemDataRole.UserRole, suggestion.key)
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked if suggestion.key in ticked else Qt.CheckState.Unchecked)
                    self.list.addItem(item)
        self.list.blockSignals(False)
        self._preview()

    def _items(self) -> list[tuple[str, QListWidgetItem]]:
        found = []
        for row in range(self.list.count()):
            item = self.list.item(row)
            key = item.data(Qt.ItemDataRole.UserRole)
            if key:
                found.append((key, item))
        return found

    def _tick(self, kind: str) -> None:
        self.list.blockSignals(True)
        for key, item in self._items():
            on = bool(kind) and self._suggestions[key].kind == kind
            item.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.list.blockSignals(False)
        self._preview()

    # -- the commands --------------------------------------------------------

    def chosen(self) -> list[function_helper.Suggestion]:
        return [self._suggestions[key] for key, item in self._items() if item.checkState() == Qt.CheckState.Checked]

    def script(self) -> str:
        if self._formula is None:
            return ""
        return self._kit.script(self._formula, self.variable_combo.currentText() or "x", self.chosen(),
                             self.low_spin.value(), self.high_spin.value(), self.point_spin.value())

    def _preview(self, *_args) -> None:
        text = self.script()
        self.preview.setPlainText(text)
        self.write_button.setEnabled(bool(text))

    def _write(self) -> None:
        self.commands.emit(self.script())
        self.accept()
