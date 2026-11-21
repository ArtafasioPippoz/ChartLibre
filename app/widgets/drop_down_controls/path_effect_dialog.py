"""PathEffectDialog: builds an effect from its parts, so nobody has to write its text.

Each effect is a row - a box to use it, its numbers, its colour - and the text the project keeps
(app.plugin_api.charts.path_effects) is written from them as they change, with a preview drawn by matplotlib.
A line below shows that text and can be edited too: what parses is shown back in the rows.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QGridLayout, QLabel, QLineEdit, QWidget

from app.dialogs.two_panels_dialog_base import PanelDialog
from app.plugin_api.charts.path_effects import _ARGUMENTS, is_valid, parse
from app.styles.style import stdSizeAndlayout
from app.utils.i18n import _
from app.widgets.drop_down_controls.color_picker import ColorPickerButton

#: The effects the rows stand for, in the order they are drawn, with the label and what each number is.
_ROWS: tuple[tuple[str, str, str], ...] = (
    ("shadow", "Shadow", "Offset right, offset up (negative is down), opacity 0-1"),
    ("glow", "Glow", "Width in points; the colour is the artist's own when left empty"),
    ("outline", "Halo", "Width in points; Background is the axes' colour, so it works on a dark style too"),
    ("stroke", "Dark outline", "Width in points"),
    ("ticked", "Ticks along the line", "Angle, length (in spacings), spacing in points"),
)
_NUMBER_LABELS = {
    "width": "Width", "dx": "Right", "dy": "Up", "alpha": "Opacity", "angle": "Angle", "length": "Length",
    "spacing": "Spacing",
}
_RANGES = {"alpha": (0.0, 1.0, 0.05), "angle": (-180.0, 180.0, 5.0), "dy": (-50.0, 50.0, 0.5), "dx": (-50.0, 50.0, 0.5)}


_PREVIEW_W, _PREVIEW_H = 140, 56


def _background() -> str:
    """The axes' colour, which \"background\" stands for."""
    from matplotlib import rcParams

    face = str(rcParams.get("axes.facecolor", "white"))
    return "white" if face.lower() in ("none", "") else face


def _number_text(value: float) -> str:
    return f"{value:g}"


class _EffectRow:
    """One effect: its box, numbers and colour, read back as the piece of text it stands for."""

    def __init__(self, parent: QWidget, grid: QGridLayout, row: int, name: str, label: str, tip: str) -> None:
        self.name = name
        self.use = QCheckBox(_(label), parent)
        self.use.setToolTip(_(tip))
        grid.addWidget(self.use, row, 0)
        self.numbers: dict[str, QDoubleSpinBox] = {}
        self.colour: ColorPickerButton | None = None
        column = 1
        for key, default in _ARGUMENTS[name]:
            if key == "color":
                self.colour = ColorPickerButton(parent, alpha=False, stand_in={"background": _background()})
                self.colour.set_color(default if default is not None else "")
                self.colour.setToolTip(_("Colour: Background is the axes' colour"))
                self.colour.colorChanged.connect(lambda *_args: self.use.setChecked(True))
                grid.addWidget(self.colour, row, column)
            else:
                spin = QDoubleSpinBox(parent)
                low, high, step = _RANGES.get(key, (0.0, 100.0, 0.5))
                spin.setRange(low, high)
                spin.setSingleStep(step)
                spin.setDecimals(2)
                spin.setValue(float(default))
                spin.setPrefix(_(_NUMBER_LABELS.get(key, key)) + " ")
                spin.valueChanged.connect(lambda *_args: self.use.setChecked(True))
                self.numbers[key] = spin
                grid.addWidget(spin, row, column)
            column += 1

    def text(self) -> str:
        order = [key for key, _default in _ARGUMENTS[self.name]]
        arguments: list[str] = []
        for key in order:
            if key == "color":
                colour = self.colour.color() if self.colour is not None else ""
                arguments.append(colour or "")
            else:
                arguments.append(_number_text(self.numbers[key].value()))
        while arguments and arguments[-1] == "":
            arguments.pop()
        return f"{self.name}({', '.join(arguments)})"

    def load(self, arguments: dict[str, Any]) -> None:
        self.use.setChecked(True)
        for key, spin in self.numbers.items():
            spin.setValue(float(arguments[key]))
        if self.colour is not None:
            self.colour.set_color(arguments.get("color") or "")


class PathEffectDialog(PanelDialog):
    """The effect of a text or a series, built from its parts; ``effect()`` is its text when accepted."""

    def __init__(self, current: str = "", parent: QWidget | None = None, *, artist: str = "text") -> None:
        super().__init__(parent, title=_("Text effect"), size=None)
        self._artist = artist
        grid = QGridLayout()
        stdSizeAndlayout(grid)
        self.add_card(_("Effects, drawn in this order"), "pathEffectCard").layout().addLayout(grid)
        self._rows = [
            _EffectRow(self, grid, index, name, label, tip) for index, (name, label, tip) in enumerate(_ROWS)
        ]
        self.preview = QLabel(self)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setToolTip(_("The effect on a piece of text, over a dark line"))
        self.add_card(_("Preview"), "pathEffectPreviewCard").layout().addWidget(self.preview)
        self.text = QLineEdit(self)
        self.text.setToolTip(_("The effect as it is saved. It can be edited: effects joined by +, each with its "
                               "values in brackets - for example shadow(1.5, -1.5, 0.35) + outline(3, white)."))
        self.add_card(_("As text"), "pathEffectTextCard").layout().addWidget(self.text)
        self._updating = False
        for row in self._rows:
            row.use.toggled.connect(self._from_rows)
            for spin in row.numbers.values():
                spin.valueChanged.connect(self._from_rows)
            if row.colour is not None:
                row.colour.colorChanged.connect(self._from_rows)
        self.text.textEdited.connect(self._from_text)
        self._load(current)
        self._ok = self.add_action("apply", self.accept, default=True)
        self.add_action("close", self.reject)
        self._show_preview()

    def effect(self) -> str:
        """The effect as text; "" when no row is used."""
        return self.text.text().strip()

    def _load(self, text: str) -> None:
        parsed = parse(text) if text else []
        self._updating = True
        for row in self._rows:
            row.use.setChecked(False)
        for name, arguments in parsed or []:
            for row in self._rows:
                if row.name == name:
                    row.load(arguments)
        self._updating = False
        self.text.setText(text.strip() if parsed is not None else "")
        self._show_preview()

    def _from_rows(self, *_args: object) -> None:
        if self._updating:
            return
        self.text.setText(" + ".join(row.text() for row in self._rows if row.use.isChecked()))
        self._show_preview()

    def _from_text(self, text: str) -> None:
        """Typed text: shown in the rows when it parses; the OK button waits for one that does."""
        if is_valid(text.strip()):
            self._load(text)
        else:
            self.preview.setText(_("Not an effect that can be drawn yet."))
            self.preview.setPixmap(QPixmap())

    def _show_preview(self) -> None:
        from app.widgets.drop_down_controls.path_effect_combo import path_effect_preview_icon

        value = self.effect()
        icon = path_effect_preview_icon(value, (_PREVIEW_W, _PREVIEW_H), self._artist)
        if icon.isNull():
            self.preview.setPixmap(QPixmap())
            self.preview.setText(_("No effect"))
        else:
            self.preview.setText("")
            self.preview.setPixmap(icon.pixmap(_PREVIEW_W, _PREVIEW_H))
        if hasattr(self, "_ok"):
            self._ok.setEnabled(is_valid(value))
