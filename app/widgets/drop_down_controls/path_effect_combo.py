"""PathEffectCombo: the effect of a text or a series - a preview drawn by matplotlib and the Edit button.

The value is the effect as text (app.plugin_api.charts.path_effects), the way it is saved in the project; the
Edit dialog (path_effect_dialog) builds it from its parts (dev/plans/path_effects_plan.txt, D). There are no ready-made
effects to choose from: the dialog is the one way, and its colours work on every effect.
"""
from __future__ import annotations

from functools import cache

import shiboken6
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton, QWidget

from app.plugin_api.charts.path_effects import is_valid, parse
from app.utils.i18n import _

_ICON_W, _ICON_H = 28, 16  # the size the effect is drawn at; a larger preview grows from it

_PREVIEW_SIZE = (64, 24)


def _red_trash() -> QIcon:
    """The catalogue's Delete icon (the system's trash can), painted red: it goes with the red Delete buttons."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor, QPainter

    from app.styles.style import action_presentation

    ratio, side = 2, 16
    source = action_presentation("delete")[0].pixmap(QSize(side, side) * ratio)
    if source.isNull():
        return QIcon()
    painter = QPainter(source)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(source.rect(), QColor("#d9342b"))
    painter.end()
    source.setDevicePixelRatio(ratio)
    return QIcon(source)


@cache
def _effect_icon(value: str, size: tuple[int, int] = (_ICON_W, _ICON_H), artist: str = "text") -> QIcon:
    """An "Aa" - or, for a series, a line with points - drawn with the effect, over a dark diagonal line so a halo
    shows where it cuts it."""
    if not is_valid(value) or not parse(value):
        return QIcon()
    from matplotlib import rc_context
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.lines import Line2D

    from app.plugin_api.charts.path_effects import to_matplotlib

    width, height = size
    grow = height / _ICON_H  # the text and the line grow with a larger preview
    scale = 2  # drawn at twice the size, shown sharp on a Retina display
    with rc_context({"axes.facecolor": "white"}):
        figure = Figure(figsize=(width / 72, height / 72), dpi=72 * scale)
        figure.patch.set_alpha(0)
        figure.add_artist(Line2D([0.05, 0.95], [0.1, 0.9], color="#555555", linewidth=1.2 * grow,
                                 transform=figure.transFigure))
        if artist == "series":
            series = Line2D([0.15, 0.35, 0.55, 0.75, 0.9], [0.3, 0.7, 0.4, 0.75, 0.5], color="#1f77b4",
                            linewidth=1.8 * grow, marker="o", markersize=3.5 * grow, transform=figure.transFigure)
            series.set_path_effects(to_matplotlib(value, "line"))
            figure.add_artist(series)
        else:
            figure.text(0.5, 0.45, "Aa", ha="center", va="center", fontsize=10 * grow, fontweight="bold",
                        color="#3a3a3a", path_effects=to_matplotlib(value, "text"))
        canvas = FigureCanvasAgg(figure)
        canvas.draw()
        buffer = canvas.buffer_rgba()
        height, width = buffer.shape[:2]
        image = QImage(bytes(buffer), width, height, QImage.Format.Format_RGBA8888)
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)


def path_effect_preview_icon(value: str, size: tuple[int, int] = (_ICON_W, _ICON_H), artist: str = "text") -> QIcon:
    """The preview of an effect written as text, on a text or ("series") on a line with points; an empty icon for
    no effect or one that does not parse."""
    return _effect_icon((value or "").strip(), size, artist)


class PathEffectCombo(QWidget):
    """The effect of a text or a series, as text: its preview and the Edit button that builds it.

    *inherit* names the first state, whose value is "" - the figure's effect, for an axis -; the explicit "none"
    then means no effect even where the figure has one, and a small button goes back to the inherited one.
    Without it, no effect is "". (The name is the one of the combo box it replaced.)
    """

    #: Emitted when the effect changes (the index is only there for the combo boxes' own signal's sake).
    currentIndexChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None, *, inherit: str = "", artist: str = "text") -> None:
        super().__init__(parent)
        self._artist = artist  # "text", or "series": what the preview and the dialog draw the effect on
        self._inherit = inherit
        self._effect = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._preview = QLabel(self)
        self._preview.setMinimumHeight(_PREVIEW_SIZE[1] + 4)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)  # level with the row's label
        self._preview.setToolTip(_("The effect on a piece of text, over a dark line"))
        layout.addWidget(self._preview, 1)
        # A tool button: on macOS a push button shows words only (its stylesheet gives it no icon size), so a push
        # button with just the trash can drew empty.
        self._reset = QToolButton(self)
        self._reset.setIcon(_red_trash())
        self._reset.setToolTip(_("Back to %s") % inherit if inherit else _("Remove the effect"))
        self._reset.clicked.connect(self._on_reset)
        layout.addWidget(self._reset)
        self._helper = QPushButton(_("Edit…"), self)
        self._helper.setToolTip(_("An outline, a shadow or a glow drawn under the text, so it stays readable over "
                                  "the data: build it from its parts"))
        self._helper.clicked.connect(self.open_helper)
        layout.addWidget(self._helper)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._refresh()

    def current_effect(self) -> str:
        """The effect chosen, as text ("" for none, or the figure's)."""
        return self._effect

    def set_current_effect(self, effect: str) -> bool:
        """Show *effect*. False when it does not parse."""
        text = (effect or "").strip()
        if text.lower() == "none" and not self._inherit:
            text = ""
        if text and not is_valid(text):
            return False
        self._effect = text
        self._refresh()
        return True

    def open_helper(self) -> None:
        """Open the dialog on the effect; Apply keeps what it built, Close goes back."""
        from app.widgets.drop_down_controls.path_effect_dialog import PathEffectDialog

        dialog = PathEffectDialog("" if self._effect == "none" else self._effect, self, artist=self._artist)
        accepted = dialog.exec()
        if not shiboken6.isValid(self) or not shiboken6.isValid(dialog):
            return  # the editor went while the dialog was open
        if accepted and is_valid(dialog.effect()):
            self._change(dialog.effect() or ("none" if self._inherit else ""))

    def _on_reset(self) -> None:
        self._change("")

    def _change(self, effect: str) -> None:
        if effect != self._effect:
            self.set_current_effect(effect)
            self.currentIndexChanged.emit(0)

    def _refresh(self) -> None:
        icon = path_effect_preview_icon(self._effect, _PREVIEW_SIZE, self._artist)
        if icon.isNull():
            self._preview.setPixmap(QPixmap())
            self._preview.setText(self._inherit if (self._inherit and not self._effect) else _("None"))
        else:
            self._preview.setText("")
            self._preview.setPixmap(icon.pixmap(*_PREVIEW_SIZE))
        self._reset.setVisible(bool(self._effect))
