"""Tests of window fit, one section per former file:

* screen_fit_before_show: A window larger than its screen is fitted as it is shown, not just after: it does not jump (bugs2.pptx).
* operation_pages_fit: Every data operation's pages fit their panel: no control wider than it, cut off at its edge.
* window_resize_edges: Windows frameless resizing: the bottom edge and corners are the status bar's (P0-4).
"""
from __future__ import annotations

from pathlib import Path
import importlib
import inspect

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog
from PySide6.QtWidgets import QScrollArea
import pytest

from app.data.sqlite_repo import SqliteRepo
from app.main_window.main_window import resize_edges
from app.plugin_api.data_operations.dialog_base import DataOperationDialogBase
from app.utils import dialog_state
from app.utils.screen_fit import fit_on_show
import app.data_operations as package


# --- screen_fit_before_show: A window larger than its screen is fitted as it is shown, not just after: it does not jump (bugs2.pptx).
def test_fitted_before_it_appears(qapp) -> None:
    available = QGuiApplication.primaryScreen().availableGeometry()
    dialog = QDialog()
    dialog.resize(available.width() + 300, available.height() + 300)
    fit_on_show(dialog)
    dialog.show()  # no event loop turn yet: only the Show event's own fit has run
    try:
        assert dialog.width() <= available.width() and dialog.height() <= available.height()
    finally:
        dialog.close()


# --- operation_pages_fit: Every data operation's pages fit their panel: no control wider than it, cut off at its edge.
def _operations() -> list[type[DataOperationDialogBase]]:
    found = []
    from _operations import operation_modules

    for module in operation_modules():
        for _name, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, DataOperationDialogBase) and cls.__module__ == module.__name__:
                found.append(cls)
    return found


@pytest.mark.parametrize("operation", _operations(), ids=lambda cls: cls.__name__)
def test_every_page_fits_its_panel(qapp, repo: SqliteRepo, operation) -> None:
    dialog_state.clear_state(operation.__name__)
    figure_id = int(repo.create_figure_descriptor(name="chart"))
    repo.create_axis_descriptor(figure_id=figure_id, axis_index=0, chart_type="Scatter Plot",
                                title="t", x_label="x", y_label="y", options={})
    dialog = operation(repo=repo, figure_id=figure_id, parent=None)
    try:
        dialog.resize(dialog.minimumSizeHint())  # the narrowest it can be: the case that cuts
        dialog.show()
        qapp.processEvents()
        tabs = dialog.left_tabs
        cut = []
        for index in range(tabs.count()):
            tabs.setCurrentIndex(index)
            qapp.processEvents()
            scroll = tabs.widget(index)
            if isinstance(scroll, QScrollArea) and scroll.widget() is not None:
                page = scroll.widget()
                if page.width() > scroll.viewport().width():
                    cut.append(f"{tabs.tabText(index)}: {page.width()} > {scroll.viewport().width()}")
        assert cut == []
        assert dialog.minimumSizeHint().width() <= 1280  # still on a laptop's screen
    finally:
        dialog.close()


# --- window_resize_edges: Windows frameless resizing: the bottom edge and corners are the status bar's (P0-4).
SIZE = QSize(800, 600)
MARGIN = 6
E = Qt.Edge


def edges(x: int, y: int, **kw) -> Qt.Edge:
    return resize_edges(QPoint(x, y), SIZE, MARGIN, **kw)


def test_the_interior_has_no_edge() -> None:
    assert edges(400, 300) == Qt.Edge(0)


def test_each_side_and_corner_of_a_whole_window() -> None:
    assert edges(0, 300) == E.LeftEdge
    assert edges(799, 300) == E.RightEdge
    assert edges(400, 0) == E.TopEdge
    assert edges(400, 599) == E.BottomEdge
    assert edges(0, 0) == E.TopEdge | E.LeftEdge
    assert edges(799, 0) == E.TopEdge | E.RightEdge
    assert edges(799, 599) == E.BottomEdge | E.RightEdge
    assert edges(0, 599) == E.BottomEdge | E.LeftEdge


def test_the_central_area_above_a_status_bar_has_no_bottom_edge() -> None:
    assert edges(400, 599, bottom=False) == Qt.Edge(0)
    assert edges(799, 599, bottom=False) == E.RightEdge  # the side is still the window's side


def test_the_status_bar_gives_the_bottom_edge_and_both_corners() -> None:
    """A 24 px strip: its top is the central area's bottom, not a window edge."""
    bar = QSize(800, 24)

    def at(x: int, y: int) -> Qt.Edge:
        return resize_edges(QPoint(x, y), bar, MARGIN, top=False, corner=14)

    assert at(400, 23) == E.BottomEdge
    assert at(400, 0) == Qt.Edge(0)  # the bar's top is not the window's
    assert at(795, 20) == E.BottomEdge | E.RightEdge
    assert at(2, 20) == E.BottomEdge | E.LeftEdge
    assert at(790, 22) == E.BottomEdge | E.RightEdge  # inside the wider corner zone, 14 px
    assert at(795, 5) == E.RightEdge  # up the side, above the bottom band, it is the side only
