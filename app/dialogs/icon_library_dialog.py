"""The icon library: the icons that come with the application (Lucide, the flags), searched and added to the project.

Each icon is added with its set's name, version, source and licence, so a chart that uses it can credit it. A
single-colour icon (Lucide's) takes the series' colour when drawn; a flag keeps its own.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QWidget,
)

from app.dialogs.two_panels_dialog_base import PanelDialog
from app.logs.logger import applogger
from app.utils import icon_library
from app.utils.i18n import _

_THUMB = 56
#: Shown at most; a search narrows the rest.
_LIMIT = 300


def _thumbnail(data: bytes, colour: str, side: int = _THUMB) -> QPixmap:
    """The SVG on a transparent square; "currentColor" (Lucide's) drawn in *colour*, the interface's text."""
    text = data.decode("utf-8", "replace").replace("currentColor", colour)
    renderer = QSvgRenderer(QByteArray(text.encode("utf-8")))
    image = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    if renderer.isValid():
        size = renderer.defaultSize().scaled(side - 6, side - 6, Qt.AspectRatioMode.KeepAspectRatio)
        painter = QPainter(image)
        renderer.render(painter, QRectF((side - size.width()) / 2, (side - size.height()) / 2,
                                        size.width(), size.height()))
        painter.end()
    return QPixmap.fromImage(image)


class IconLibraryDialog(PanelDialog):
    """Search a set, select icons, add them to *repo*'s pictures."""

    def __init__(self, repo: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent, title=_("Icon library"), size=None)
        self._repo = repo
        #: The names added to the project, in order.
        self.added: list[str] = []
        self.resize(640, 480)
        card = self.add_card(_("Icons that come with ChartLibre"), "iconLibraryCard", stretch=1)
        root = card.layout()

        row = QHBoxLayout()
        self.sets = QComboBox(card)
        for key in icon_library.set_keys():
            self.sets.addItem(icon_library.load(key).title, key)
        self.search = QLineEdit(card)
        self.search.setPlaceholderText(_("Search: heart, factory, Italy, Europe…"))
        self.search.setClearButtonEnabled(True)
        row.addWidget(self.sets)
        row.addWidget(self.search, 1)
        root.addLayout(row)

        self.list = QListWidget(card)
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setUniformItemSizes(True)
        self.list.setIconSize(QSize(_THUMB, _THUMB))
        self.list.setGridSize(QSize(92, 92))
        self.list.setWordWrap(True)
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.itemDoubleClicked.connect(lambda _item: self._add())
        root.addWidget(self.list, 1)

        self.credit = QLabel(card)
        self.credit.setProperty("muted", True)
        self.credit.setWordWrap(True)
        root.addWidget(self.credit)

        self.sets.currentIndexChanged.connect(self._fill)
        self.search.textChanged.connect(self._fill)
        self.add_action("add", self._add)
        self.add_action("dismiss", self.reject)
        self._fill()

    def _key(self) -> str:
        return str(self.sets.currentData() or "")

    def _fill(self, *_args: object) -> None:
        key = self._key()
        self.list.clear()
        if not key:
            return
        colour = self.palette().text().color().name()
        found = icon_library.search(key, self.search.text(), _LIMIT)
        for name, title in found:
            try:
                pixmap = _thumbnail(icon_library.svg(key, name), colour)
            except KeyError:
                continue
            item = QListWidgetItem(QIcon(pixmap), title if len(title) <= 22 else title[:21] + "…")
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(f"{title}\n{icon_library.project_name(key, name)}")
            self.list.addItem(item)
        icons = icon_library.load(key)
        shown = _("{count} shown").format(count=len(found)) if len(found) < len(icons.icons) or found else ""
        self.credit.setText(_("{title} {version}, licence {license}. {shown}").format(
            title=icons.title, version=icons.version, license=icons.license, shown=shown))

    def _add(self) -> None:
        """The selected icons into the project's pictures, each with its set's source and licence."""
        key = self._key()
        icons = icon_library.load(key)
        for item in self.list.selectedItems():
            name = str(item.data(Qt.ItemDataRole.UserRole))
            try:
                added = self._repo.add_image(icon_library.project_name(key, name), icon_library.svg(key, name),
                                             source=icons.credit(), license=icons.license)
            except Exception:
                applogger.exception("Icon %s of %s could not be added.", name, key)
                continue
            self.added.append(added)
        if self.added:
            self.accept()
