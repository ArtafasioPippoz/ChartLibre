"""A lazy results pane makes its viewer when first shown, even if the window is hidden and shown under it."""
from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QVBoxLayout, QWidget

from app.widgets.html_results import HtmlResultsView


class _View(QWidget):
    """A viewer with a page, as a QWebEngineView has: what _park_viewer parks."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._page = QObject(parent)
        self.html = ""

    def page(self) -> QObject:
        return self._page

    def setHtml(self, markup: str) -> None:
        self.html = markup


def test_the_window_built_again_while_the_viewer_is_made_does_not_loop(qapp, monkeypatch) -> None:
    """The first web view put in a window on screen makes Qt hide and show the window in the middle of the
    call: that Hide parked the new view and that Show made another, until the process died (2026-11-12)."""
    window = QWidget()
    layout = QVBoxLayout(window)
    pane = HtmlResultsView(window, lazy=True)
    layout.addWidget(pane)
    pane.setHtml("<p>notes</p>")
    made: list[_View] = []

    def create(self: HtmlResultsView) -> QWidget:
        assert len(made) < 3, "the viewer is made again and again"
        view = _View(self)
        made.append(view)
        return view

    def rebuilt(_view: QWidget) -> None:
        window.hide()  # as Qt does to the window once its first web view is in it
        window.show()

    from app.widgets import html_results

    monkeypatch.setattr(HtmlResultsView, "_create_viewer", create)
    monkeypatch.setattr(html_results, "mark_editor_panel", rebuilt)  # called right after the view is kept
    try:
        window.show()
        qapp.processEvents()
        assert len(made) == 1
        assert pane._view is made[0] and not pane._parked
        assert made[0].html == "<p>notes</p>"
    finally:
        window.close()
        window.deleteLater()
