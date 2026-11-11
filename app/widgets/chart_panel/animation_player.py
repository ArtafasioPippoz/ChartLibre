"""What plays an animated chart: one per chart panel, driven from Chart properties > Animation.

The frame shown, the timer, the whole data's limits. Frame len(frames) is "All": the whole data, as the chart
is drawn without an animation - where it rests until Play. Each frame is a full render of the figure with its
series' queries filtered (app.plugin_api.charts.animation), on a QTimer: no matplotlib FuncAnimation, whose
own timer would fight Qt's. The controls (play, the slider, Save GIF) are on the Animation page and follow
``changed``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QFileDialog, QProgressDialog, QWidget

from app.logs.logger import applogger
from app.plugin_api.charts import animation as anim
from app.utils.i18n import _
from app.utils.messages import show_message

if TYPE_CHECKING:
    from collections.abc import Callable


class AnimationPlayer(QObject):
    """Plays the figure of *panel* (a ChartPanel) frame by frame."""

    #: The frames, the frame shown or playing changed: the controls follow.
    changed = Signal()

    def __init__(self, panel: Any) -> None:
        super().__init__(panel)
        self._panel = panel
        self._settings: anim.AnimationSettings | None = None
        self._values: list[Any] = []
        #: The frame shown; len(values) is "All", the whole data.
        self._index = 0
        self._limits: Any = None
        self._ticking = False

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    @property
    def active(self) -> bool:
        return self._settings is not None

    @property
    def frame_count(self) -> int:
        return len(self._values)

    @property
    def index(self) -> int:
        return self._index

    def label(self) -> str:
        """The frame shown, in words: its value, or "All (n frames)"."""
        if self._settings is None or self._index >= len(self._values):
            return _("All ({count} frames)").format(count=len(self._values))
        return anim.caption(self._settings, self._values, self._index)

    # ------------------------------------------------------------------
    # Called by the panel around each render
    # ------------------------------------------------------------------
    def prepare(self, descriptor: Any) -> None:
        """Before a render: read the figure's animation (the frames too, unless a frame of a play is drawn)."""
        if self._ticking:
            return
        settings = anim.AnimationSettings.from_options(getattr(descriptor, "options", None)) if descriptor else None
        if settings is not None and anim.not_animatable(descriptor):
            settings = None
        if settings is None:
            self._settings, self._values = None, []
            self._timer.stop()
            self.changed.emit()
            return
        changed = self._settings is None or settings.to_options() != self._settings.to_options()
        self._settings = settings
        try:
            self._values = anim.frames(self._panel._repo, descriptor, settings)
        except Exception:
            applogger.exception("Could not read the animation's frames")
            self._values = []
        if changed or self._index > len(self._values):
            self._index = len(self._values)  # a new animation starts on all the data
            self._timer.stop()
        self._timer.setInterval(int(round(1000.0 / settings.fps)))
        self.changed.emit()

    def frame_filter(self) -> Callable[[str], str] | None:
        """What the series' queries become in the frame shown; None for all the data."""
        if self._settings is None or not self._values or self._index >= len(self._values):
            return None
        return anim.frame_filter(self._panel._repo, self._settings, self._values, self._index)

    def after_render(self, figure: Any) -> None:
        """After a render: all the data's limits remembered, or a frame's finished (limits held, caption)."""
        if self._settings is None or not self._values:
            return
        if self._index >= len(self._values):
            self._limits = anim.axes_limits(figure)
            return
        limits = self._limits if self._settings.source == anim.COLUMN else None
        anim.finish_frame(figure, self._settings, anim.caption(self._settings, self._values, self._index), limits)

    # ------------------------------------------------------------------
    # Playing
    # ------------------------------------------------------------------
    @property
    def playing(self) -> bool:
        return self._timer.isActive()

    def toggle(self) -> None:
        if self.playing:
            self._timer.stop()
        elif self._values:
            if self._index >= len(self._values) - 1:
                self._show(0)
            self._timer.start()
        self._sync_controls()

    def step(self, delta: int) -> None:
        self._timer.stop()
        if self._values:
            self._show(max(0, min(len(self._values), self._index + delta)))
        self._sync_controls()

    def _tick(self) -> None:
        settings = self._settings
        if settings is None or not self._values:
            self._timer.stop()
            return
        following = self._index + 1
        if following >= len(self._values):
            if not settings.loop:
                self._timer.stop()
                self._sync_controls()
                return
            following = 0
        self._show(following)

    def go_to(self, index: int) -> None:
        """Show frame *index* (frame_count: all the data), from the slider."""
        if int(index) != self._index:
            self._show(max(0, min(self.frame_count, int(index))))

    def _show(self, index: int) -> None:
        """Draw frame *index* (len(values): all the data)."""
        self._index = index
        self._sync_controls()
        self._ticking = True
        try:
            self._panel.reload()
        finally:
            self._ticking = False

    def _sync_controls(self) -> None:
        self.changed.emit()

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def save_gif(self, parent: QWidget | None = None) -> None:
        """Every frame, off screen at the figure's size, into an animated GIF - with a progress bar and Stop."""
        if self._settings is None:
            return
        self._timer.stop()
        self._sync_controls()
        repo = self._panel._repo
        descriptor = repo.load_figure_descriptor(self._panel._figure_id)
        if descriptor is None:
            return
        parent = parent or self._panel
        path, _unused = QFileDialog.getSaveFileName(parent, _("Save animation"), f"{descriptor.name or 'animation'}.gif",
                                                    _("Animated GIF (*.gif)"))
        if not path:
            return
        if not path.lower().endswith(".gif"):
            path += ".gif"
        progress = QProgressDialog(_("Drawing the frames…"), _("Stop"), 0, max(1, len(self._values)), parent)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(300)

        def advance(done: int, total: int) -> bool:
            progress.setMaximum(total)
            progress.setValue(done)
            QApplication.processEvents()
            return not progress.wasCanceled()

        figure = self._panel._figure
        try:
            anim.export_gif(path, descriptor, repo, self._settings, size_in=tuple(figure.get_size_inches()),
                            dpi=100.0, progress=advance)
        except Exception as exc:
            applogger.exception("Could not save the animation")
            show_message(parent, "chart.animation_export_failed", error=exc)
        finally:
            progress.close()
