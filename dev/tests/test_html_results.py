"""Tests of html results, one section per former file:

* html_results_park: A closed window's web view is deleted by the event loop, not by Python's collector later.
* html_results_lazy_show: A lazy results pane makes its viewer when first shown, even if the window is hidden and shown under it.
"""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtCore import QObject
from PySide6.QtGui import QHideEvent
from PySide6.QtWidgets import QDialog, QVBoxLayout
from PySide6.QtWidgets import QVBoxLayout, QWidget
import pytest
import shiboken6

from app.widgets import html_results
from app.widgets.html_results import HtmlResultsView


# --- html_results_park: A closed window's web view is deleted by the event loop, not by Python's collector later.
def test_hidden_window_gives_up_its_web_view_and_gets_a_new_one_when_shown(qapp) -> None:
    dialog = QDialog()
    QVBoxLayout(dialog).addWidget(pane := HtmlResultsView(dialog))
    if not hasattr(pane._viewer, "page"):
        pytest.skip("QtWebEngine is not installed: QTextBrowser needs none of this")
    pane.setHtml("<p>report</p>")
    dialog.show()
    qapp.processEvents()
    old = pane._viewer

    dialog.hide()
    assert pane._parked and old.parent() is None and old in html_results._PARKED
    QCoreApplication.sendPostedEvents(None, int(QEvent.Type.DeferredDelete))
    assert not shiboken6.isValid(old)

    pane.setHtml("<p>later</p>")  # while parked: kept for the next view
    dialog.show()
    qapp.processEvents()
    assert not pane._parked and pane._viewer is not old and pane.text() == "<p>later</p>"
    dialog.close()


def test_hidden_again_while_parked_leaves_the_deleted_view_alone(qapp) -> None:
    # The window shown again with the pane on another tab (no showEvent: still parked), then
    # closed: Cancel's Hide reached the deleted web view ("already deleted", the log).
    dialog = QDialog()
    QVBoxLayout(dialog).addWidget(pane := HtmlResultsView(dialog))
    if not hasattr(pane._viewer, "page"):
        pytest.skip("QtWebEngine is not installed: QTextBrowser needs none of this")
    dialog.show()
    qapp.processEvents()
    dialog.hide()
    QCoreApplication.sendPostedEvents(None, int(QEvent.Type.DeferredDelete))
    assert pane._parked and not shiboken6.isValid(pane._viewer)
    assert pane.eventFilter(dialog, QHideEvent()) is False  # called directly: an error would raise
    del pane.__dict__["_watched_window"]  # the collector cleared it: the filter still answers
    assert pane.eventFilter(dialog, QHideEvent()) is False
    dialog.close()


# --- html_results_lazy_show: A lazy results pane makes its viewer when first shown, even if the window is hidden and shown under it.
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
