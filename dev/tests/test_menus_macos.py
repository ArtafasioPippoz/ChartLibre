"""Menus as the platform writes them: on macOS no icon beside an item and its shortcut shown, in a context menu too."""
from __future__ import annotations

from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap

from app.styles.style import CONTEXT_MENU_ICONS, TidyMenu
from app.styles.widgets import IS_MACOS


def _icon() -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill()
    return QIcon(pixmap)


def test_a_tidy_menu_sets_its_items_as_they_are_added(qapp) -> None:
    menu = TidyMenu()
    action = QAction(_icon(), "Copy", menu)
    action.setShortcut(QKeySequence.StandardKey.Copy)
    menu.addAction(action)
    sub = menu.addMenu("More")  # a plain submenu made by addMenu(text)
    inner = sub.addAction(_icon(), "Paste")
    assert action.isIconVisibleInMenu() == CONTEXT_MENU_ICONS
    if IS_MACOS:
        assert action.isShortcutVisibleInContextMenu()
        assert menu.actions()[-1].menu() is sub
        assert isinstance(sub, TidyMenu) and inner.isIconVisibleInMenu() == CONTEXT_MENU_ICONS
