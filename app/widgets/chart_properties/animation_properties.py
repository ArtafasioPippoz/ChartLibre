"""Chart properties > Animation: what the figure plays along, and how (todo I-03).

A column of the series' tables - each frame its rows with one value, all up to it, or the last few - or, for a
figure drawing a stored function, one of the function's parameters from a value to another. Stored in the
figure's options ("animation"), so it is saved with the project and Undo takes it back; played by the bar under
the chart (app/widgets/chart_panel/animation_bar.py).
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.plugin_api.charts import animation as anim
from app.widgets.inspector import InspectorCard, drawn_icon
from app.styles.style import MARGIN_TOOLBOX_PAGE, fit_spin_width, stdSizeAndlayout
from app.utils.i18n import _
from app.widgets.chart_properties.base_properties import BaseProperties

#: The modes as the page shows them.
MODE_LABELS: tuple[tuple[str, str], ...] = (
    (anim.EACH, "Each frame alone"),
    (anim.CUMULATIVE, "Cumulative"),
    (anim.TRAILING, "Trailing"),
)


class AnimationPropertiesWidget(BaseProperties):
    """The Animation page: emits ``animation_changed`` with the settings to store, or None to stop animating."""

    animation_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._parameters: dict[str, float] = {}
        self._player: Any = None
        self._build_ui()
        self._install_auto_apply(self._apply)
        self._watch(self._enabled, self._source, self._column, self._mode, self._trail, self._parameter,
                    self._start, self._stop, self._steps, self._fps, self._loop, self._hold, self._caption)
        self._source.currentIndexChanged.connect(self._sync_visibility)
        self._mode.currentIndexChanged.connect(self._sync_visibility)
        self._parameter.currentIndexChanged.connect(self._parameter_chosen)
        self._enabled.toggled.connect(self._sync_visibility)
        self._set_enabled_state(False)

    # ------------------------------------------------------------------
    # The page
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*MARGIN_TOOLBOX_PAGE)

        what = InspectorCard(self, _("Play along"), "animationPlay", prefix="animation")
        form = QFormLayout()
        stdSizeAndlayout(form)
        form.setVerticalSpacing(10)
        self._enabled = QCheckBox(_("Animate this figure"), what.card)
        self._enabled.setToolTip(_("Play the figure one frame at a time, with the bar under the chart"))
        self._source = QComboBox(what.card)
        self._source.addItem(_("A column"), anim.COLUMN)
        self._source.addItem(_("A function's parameter"), anim.PARAMETER)
        self._column = QComboBox(what.card)
        self._column.setToolTip(_("Each frame draws the rows with one value of this column: a year, a time, a step"))
        self._mode = QComboBox(what.card)
        for key, label in MODE_LABELS:
            self._mode.addItem(_(label), key)
        self._mode.setToolTip(_("One value at a time, every value up to the frame's, or the last few"))
        self._trail = QSpinBox(what.card)
        self._trail.setRange(2, 1000)
        self._trail.setToolTip(_("How many frames stay on screen, the current one included"))
        self._parameter = QComboBox(what.card)
        self._parameter.setToolTip(_("The parameter of the figure's function that changes from frame to frame"))
        self._start = QDoubleSpinBox(what.card)
        self._stop = QDoubleSpinBox(what.card)
        for box in (self._start, self._stop):
            box.setRange(-1e9, 1e9)
            box.setDecimals(4)
        self._steps = QSpinBox(what.card)
        self._steps.setRange(2, 2000)
        for box in (self._column, self._mode, self._parameter, self._source):
            self._configure_combo_width(box)
        form.addRow(self._enabled)
        self._rows: dict[str, tuple[QLabel, QWidget]] = {}
        for key, label, field in (
            ("source", _("Along"), self._source),
            ("column", _("Column"), self._column),
            ("mode", _("Frames"), self._mode),
            ("trail", _("Frames shown"), self._trail),
            ("parameter", _("Parameter"), self._parameter),
            ("start", _("From"), self._start),
            ("stop", _("To"), self._stop),
            ("steps", _("Frames"), self._steps),
        ):
            caption = QLabel(label, what.card)
            form.addRow(caption, field)
            self._rows[key] = (caption, field)
        what.card.layout().addLayout(form)
        self._note = QLabel("", what.card)
        self._note.setWordWrap(True)
        self._note.setProperty("muted", True)
        what.card.layout().addWidget(self._note)
        layout.addWidget(what)

        how = InspectorCard(self, _("Playing"), "animationPlaying", prefix="animation")
        how_form = QFormLayout()
        stdSizeAndlayout(how_form)
        how_form.setVerticalSpacing(10)  # the platform's spacing between check boxes, not a tight stack
        self._fps = QDoubleSpinBox(how.card)
        self._fps.setRange(0.5, 30.0)
        self._fps.setSingleStep(0.5)
        self._fps.setSuffix(_(" frames/s"))
        self._loop = QCheckBox(_("Loop"), how.card)
        self._hold = QCheckBox(_("Hold the axes"), how.card)
        self._hold.setToolTip(_("Keep the limits of the whole data, so the axes do not jump from frame to frame"))
        self._caption = QCheckBox(_("Show the frame's value"), how.card)
        self._caption.setToolTip(_("Write the frame's value at the top right of the figure"))
        how_form.addRow(_("Speed"), self._fps)
        how_form.addRow(self._loop)
        how_form.addRow(self._hold)
        how_form.addRow(self._caption)
        how.card.layout().addLayout(how_form)

        # The player: big round buttons - back, play (the accent one), forward - then what the chart shows now.
        row = QHBoxLayout()
        row.setSpacing(14)
        self._back = self._tool("step_back", _("A frame back"), lambda: self._player and self._player.step(-1), 40)
        self._play = self._tool("play", _("Play"), lambda: self._player and self._player.toggle(), 52, accent=True)
        self._forward = self._tool("step_forward", _("A frame forward"),
                                   lambda: self._player and self._player.step(1), 40)
        row.addStretch(1)
        for button in (self._back, self._play, self._forward):
            row.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        how.card.layout().addLayout(row)
        self._frame_label = QLabel("", how.card)
        self._frame_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        how.card.layout().addWidget(self._frame_label)
        self._slider = QSlider(Qt.Orientation.Horizontal, how.card)
        self._slider.setToolTip(_("The frames; at the right end, all the data"))
        self._slider.valueChanged.connect(lambda value: self._player and self._player.go_to(value))
        how.card.layout().addWidget(self._slider)
        self._save = QPushButton(_("Save as GIF…"), how.card)
        self._save.setToolTip(_("Every frame, at the figure's size, into an animated GIF"))
        self._save.clicked.connect(lambda _checked=False: self._player and self._player.save_gif(self))
        how.card.layout().addWidget(self._save)
        layout.addWidget(how)
        layout.addStretch(1)
        self._sync_player()
        for spin in (self._trail, self._start, self._stop, self._steps, self._fps):
            fit_spin_width(spin)
        self._cards = (what, how)

    def _tool(self, kind: str, tooltip: str, action: Any, size: int, *, accent: bool = False) -> QToolButton:
        """A round player button: its glyph drawn here (white on the accent one), its look from the style sheet."""
        button = QToolButton(self)
        button.setObjectName("playerPlay" if accent else "playerButton")
        button.setProperty("glyph", kind)
        button.setFixedSize(size, size)
        button.setIconSize(QSize(int(size * 0.46), int(size * 0.46)))
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _checked=False: action())
        self._draw_glyph(button, kind)
        return button

    def _draw_glyph(self, button: QToolButton, kind: str) -> None:
        """The button's glyph, in the colour that reads on its ground (white on the accent button)."""
        palette = self.palette()
        colour = palette.color(QPalette.ColorRole.HighlightedText if button.objectName() == "playerPlay"
                               else QPalette.ColorRole.WindowText)
        button.setIcon(drawn_icon(kind, colour, 24))
        button.setProperty("glyph", kind)

    # ------------------------------------------------------------------
    # The chart's player
    # ------------------------------------------------------------------
    def set_player(self, player: Any) -> None:
        """Drive *player* (the connected chart's AnimationPlayer), or nothing with None."""
        if self._player is player:
            return
        if self._player is not None:
            try:
                self._player.changed.disconnect(self._sync_player)
            except (RuntimeError, TypeError):
                pass  # the chart, and its player, already gone
        self._player = player
        if player is not None:
            player.changed.connect(self._sync_player)
        self._sync_player()

    def _sync_player(self) -> None:
        """The controls as the player stands: the frames, the one shown, playing or not."""
        player = self._player
        count = player.frame_count if player is not None and player.active else 0
        self._slider.blockSignals(True)
        self._slider.setRange(0, count)
        self._slider.setValue(min(player.index, count) if player is not None else 0)
        self._slider.blockSignals(False)
        playing = player is not None and player.playing
        self._draw_glyph(self._play, "pause" if playing else "play")
        self._play.setToolTip(_("Pause") if playing else _("Play"))
        self._frame_label.setText(player.label() if count else _("Apply the settings to play"))
        for widget in (self._back, self._play, self._forward, self._slider, self._save):
            widget.setEnabled(count > 0)

    def clear_connected_figure(self) -> None:
        self.set_player(None)
        super().clear_connected_figure()

    def _sync_visibility(self, *_args: Any) -> None:
        """Only the rows of what is chosen: a column's or a parameter's; the trail length for Trailing."""
        on = self._enabled.isChecked()
        parameter = self._source.currentData() == anim.PARAMETER
        shown = {
            "source": on and bool(self._parameters),
            "column": on and not parameter,
            "mode": on and not parameter,
            "trail": on and not parameter and self._mode.currentData() == anim.TRAILING,
            "parameter": on and parameter,
            "start": on and parameter,
            "stop": on and parameter,
            "steps": on and parameter,
        }
        for key, (caption, field) in self._rows.items():
            caption.setVisible(shown[key])
            field.setVisible(shown[key])
        self._cards[1].setVisible(on)

    def _parameter_chosen(self, *_args: Any) -> None:
        """A parameter newly chosen starts from 0 to twice its value: a range around the one drawn now."""
        if self._reloading_depth:
            return
        value = self._parameters.get(str(self._parameter.currentData() or ""), 1.0)
        with self._reloading_controls():
            low, high = sorted((0.0, 2.0 * value if value else 1.0))
            self._start.setValue(low)
            self._stop.setValue(high)

    # ------------------------------------------------------------------
    # BaseProperties
    # ------------------------------------------------------------------
    def _reload_from_descriptor(self) -> None:
        descriptor = (self._repo.load_figure_descriptor(self._figure_id)
                      if self._repo is not None and self._figure_id is not None else None)
        if descriptor is None:
            self._set_enabled_state(False)
            return
        settings = anim.AnimationSettings.from_options(descriptor.options) or anim.AnimationSettings()
        stored = anim.AnimationSettings.from_options(descriptor.options) is not None
        self._parameters = anim.function_parameters(descriptor)
        columns = anim.frame_columns(self._repo, descriptor)

        self._column.clear()
        for name in columns:
            self._column.addItem(name, name)
        self._parameter.clear()
        for name in self._parameters:
            self._parameter.addItem(name, name)
        self._enabled.setChecked(stored)
        self._select(self._source, settings.source if self._parameters else anim.COLUMN)
        self._select(self._column, settings.column)
        self._select(self._mode, settings.mode)
        self._select(self._parameter, settings.parameter)
        self._trail.setValue(settings.trail)
        if settings.parameter:
            self._start.setValue(settings.start)
            self._stop.setValue(settings.stop)
        else:
            value = next(iter(self._parameters.values()), 1.0)
            self._start.setValue(min(0.0, 2.0 * value))
            self._stop.setValue(max(0.0, 2.0 * value) or 1.0)
        self._steps.setValue(settings.steps)
        self._fps.setValue(settings.fps)
        self._loop.setChecked(settings.loop)
        self._hold.setChecked(settings.hold)
        self._caption.setChecked(settings.caption)

        refused = anim.not_animatable(descriptor)
        if refused:
            self._note.setText(_("{charts} cannot be played: it draws the whole table as one structure, with no "
                                 "frames to go through.").format(charts=", ".join(refused)))
        elif not columns and not self._parameters:
            self._note.setText(_("Nothing to play along: the series read no table with row ids, and draw no "
                                 "function."))
        else:
            self._note.setText("")
        self._note.setVisible(bool(self._note.text()))
        self._set_enabled_state(not refused and bool(columns or self._parameters))
        self._sync_visibility()

    @staticmethod
    def _select(combo: QComboBox, value: Any) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _set_enabled_state(self, enabled: bool) -> None:
        for card in getattr(self, "_cards", ()):
            card.setEnabled(enabled)

    def settings(self) -> anim.AnimationSettings | None:
        """What the page says, or None when the figure is not animated."""
        if not self._enabled.isChecked():
            return None
        return anim.AnimationSettings(
            source=str(self._source.currentData() or anim.COLUMN),
            column=str(self._column.currentData() or ""),
            mode=str(self._mode.currentData() or anim.EACH),
            trail=self._trail.value(),
            parameter=str(self._parameter.currentData() or ""),
            start=self._start.value(),
            stop=self._stop.value(),
            steps=self._steps.value(),
            fps=self._fps.value(),
            loop=self._loop.isChecked(),
            hold=self._hold.isChecked(),
            caption=self._caption.isChecked(),
        )

    def _apply(self) -> None:
        settings = self.settings()
        self.animation_changed.emit(settings.to_options() if settings is not None and settings.active else None)
