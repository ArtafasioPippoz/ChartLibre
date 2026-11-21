"""PathEffectCombo: halos, outlines, shadows and glows for text, each with a preview drawn by matplotlib.

The value is the effect as text (app.plugin_api.charts.path_effects), the way it is saved in the project; Custom...
opens a builder for one of the user's own (path_effect_dialog) (dev/plans/path_effects_plan.txt, D).
"""
from __future__ import annotations

from functools import cache

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.plugin_api.charts.path_effects import is_valid, parse
from app.utils.i18n import _
from app.widgets.drop_down_controls.icon_combo import IconComboBox

_ICON_W, _ICON_H = 28, 16

#: The entry that asks for an effect of the user's own.
CUSTOM = "__custom__"

#: (label, value): the effects most charts want. "background" is the axes' colour of the style being drawn, so a
#: halo works on a dark theme as on a light one.
PRESETS: tuple[tuple[str, str], ...] = (
    ("Halo", "outline(6, background)"),
    ("Dark outline", "stroke(2, black)"),
    ("Shadow", "shadow"),
    ("Glow", "glow(6)"),
    ("Halo and shadow", "shadow + outline(6, background)"),
)


@cache
def _effect_icon(value: str, size: tuple[int, int] = (_ICON_W, _ICON_H)) -> QIcon:
    """An "Aa" drawn with the effect, over a dark diagonal line so a halo shows where it cuts it."""
    if value == CUSTOM or not is_valid(value) or not parse(value):
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
        figure.text(0.5, 0.45, "Aa", ha="center", va="center", fontsize=10 * grow, fontweight="bold", color="#3a3a3a",
                    path_effects=to_matplotlib(value, "text"))
        canvas = FigureCanvasAgg(figure)
        canvas.draw()
        buffer = canvas.buffer_rgba()
        height, width = buffer.shape[:2]
        image = QImage(bytes(buffer), width, height, QImage.Format.Format_RGBA8888)
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)


def path_effect_preview_icon(value: str, size: tuple[int, int] = (_ICON_W, _ICON_H)) -> QIcon:
    """The preview of an effect written as text; an empty icon for no effect or one that does not parse."""
    return _effect_icon((value or "").strip(), size)


class PathEffectCombo(IconComboBox):
    """The effect of a text, as text: the presets, None, and Custom...

    *inherit* names a first entry whose value is "" - the figure's effect, for an axis -; the explicit
    "none" then means no effect even where the figure has one. Without it, None is "".
    """

    def __init__(self, parent: QWidget | None = None, *, inherit: str = "") -> None:
        entries = [(inherit, ""), (_("None"), "none")] if inherit else [(_("None"), "")]
        entries += [(_(label), value) for label, value in PRESETS]
        entries.append((_("Custom…"), CUSTOM))
        super().__init__(parent, entries=entries, icon_for=path_effect_preview_icon,
                         icon_size=QSize(_ICON_W, _ICON_H))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip(_("An outline, a shadow or a glow drawn under the text, so it stays readable over the data"))
        self._previous = self.current_value()
        self.activated.connect(self._on_activated)

    def current_effect(self) -> str:
        """The effect chosen, as text ("" for none, or the figure's)."""
        value = self.current_value()
        return self._previous if value == CUSTOM else value

    def set_current_effect(self, effect: str) -> bool:
        """Select *effect*; one of the user's own gets an entry of its own. False when it does not parse."""
        text = (effect or "").strip()
        if text.lower() == "none" and self.findData("none", self.ROLE_VALUE) < 0:
            text = ""
        if self.findData(text, self.ROLE_VALUE) < 0:
            if not is_valid(text):
                return False
            self._add_custom(text)
        found = self.set_current_value(text)
        if found:
            self._previous = text
        return found

    def _add_custom(self, text: str) -> None:
        """An entry for the effect *text*, just above Custom…."""
        self.blockSignals(True)
        at = self.findData(CUSTOM, self.ROLE_VALUE)
        self.insertItem(at if at >= 0 else self.count(), path_effect_preview_icon(text), text, text)
        self.blockSignals(False)

    def _on_activated(self, index: int) -> None:
        """Custom… opens the effect builder; an effect it makes is added and chosen, Cancel goes back."""
        if self.itemData(index, self.ROLE_VALUE) != CUSTOM:
            self._previous = self.current_value()
            return
        from app.widgets.drop_down_controls.path_effect_dialog import PathEffectDialog

        dialog = PathEffectDialog(self._previous, self)
        if dialog.exec() and dialog.effect() and is_valid(dialog.effect()):
            self.set_current_effect(dialog.effect())
        else:
            self.set_current_value(self._previous)
        self.currentIndexChanged.emit(self.currentIndex())
