"""Preferences > Packages: the extension packs, each switched on or off (app.utils.packs)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.utils import packs
from app.utils.i18n import tr
from app.utils.messages import ask, show_message

#: What a pack adds, family by family, in the words of the interface.
FAMILY_WORDS = {
    "charts": "chart types",
    "data_operations": "analyses",
    "importers": "file readers",
    "functions": "fit functions",
    "ai_providers": "assistant providers",
}


def describe(pack: packs.Pack) -> str:
    """The lines of a pack's row: its name and version, what it adds or what is wrong (what it is: the detail below)."""
    lines = [f"{tr(pack.name)}  {pack.version}".rstrip()]
    if pack.error:
        lines.append(tr("Not usable: {why}").format(why=tr(pack.error)))
        return "\n".join(lines)
    adds = ", ".join(f"{tr(FAMILY_WORDS[family])} ({count})" for family, count in packs.contents(pack).items())
    if adds:
        lines.append(tr("Adds: {what}").format(what=adds))
    missing = packs.missing_packages(pack)
    if missing:
        lines.append(tr("Needs the libraries: {names}").format(names=", ".join(missing)))
    return "\n".join(lines)


class PacksPanel(QWidget):
    """The list of packs with a check box each. Nothing is written until save(), like the rest of Preferences;
    adding and removing a file happen at once, because they are files."""

    PREVIEW_WIDTH = 180

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        #: pack id -> the switch as the user left it, where it differs from what is stored.
        self._changed: dict[str, bool] = {}
        #: The user's packs accepted in this window, trusted for good at save().
        self._accepted: dict[str, packs.Pack] = {}
        #: A pack was added here: what it brings is there at the next start only.
        self._added = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget(self)
        self.list.setWordWrap(True)
        self.list.setAlternatingRowColors(True)
        self.list.setMinimumHeight(170)
        self.list.setSpacing(3)
        self.list.itemChanged.connect(self._switched)
        self.list.currentItemChanged.connect(lambda *_: self._show_detail())
        layout.addWidget(self.list, 1)

        # The chosen pack as the chart picker shows a chart: its example picture beside what it is.
        self.detail = QWidget(self)
        detail_row = QHBoxLayout(self.detail)
        detail_row.setContentsMargins(0, 0, 0, 0)
        self.preview = QLabel(self.detail)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.description = QLabel(self.detail)
        self.description.setWordWrap(True)
        self.description.setAlignment(Qt.AlignmentFlag.AlignTop)
        detail_row.addWidget(self.preview)
        detail_row.addWidget(self.description, 1)
        self.detail.setVisible(False)

        self.empty_note = QLabel(tr("No packs yet. A pack is a .clpack file that adds analyses, chart types or "
                                    "file readers."), self)
        self.empty_note.setProperty("muted", True)
        self.empty_note.setWordWrap(True)
        layout.addWidget(self.empty_note)

        buttons = QHBoxLayout()
        self.add_button = QPushButton(tr("Add from a file…"), self)
        self.add_button.clicked.connect(self._add)
        buttons.addWidget(self.add_button)
        buttons.addStretch(1)
        layout.addWidget(self.detail)
        layout.addLayout(buttons)  # under the description of the chosen pack
        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """List the pack files as they are now, keeping the switches not saved yet."""
        self.list.blockSignals(True)
        self.list.clear()
        for pack in packs.find():
            item = QListWidgetItem(describe(pack))
            item.setData(Qt.ItemDataRole.UserRole, pack)
            flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
            if not pack.error:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
                on = self._changed.get(pack.id, packs.is_switched_on(pack) and self._may_run(pack))
                item.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            item.setFlags(flags)
            item.setToolTip(str(pack.path))
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.empty_note.setVisible(self.list.count() == 0)
        self.list.setVisible(self.list.count() > 0)
        self._show_detail()

    def _show_detail(self) -> None:
        """The description and the example picture of the chosen pack; nothing when it has neither."""
        pack = self._current()
        text = tr(pack.description) if pack is not None and pack.description else ""
        picture = QPixmap()
        data = packs.preview_bytes(pack) if pack is not None else None
        if data:
            picture.loadFromData(data)
        if not picture.isNull():
            picture = picture.scaledToWidth(self.PREVIEW_WIDTH * 2, Qt.TransformationMode.SmoothTransformation)
            picture.setDevicePixelRatio(2.0)  # sharp on a Retina screen, as the chart picker's
        self.preview.setPixmap(picture)
        self.preview.setVisible(not picture.isNull())
        self.description.setText(text)
        self.description.setVisible(bool(text))
        self.detail.setVisible(bool(text) or not picture.isNull())

    def _may_run(self, pack: packs.Pack) -> bool:
        return packs.is_trusted(pack) or self._accepted.get(pack.id) is not None

    def _current(self) -> packs.Pack | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _switched(self, item: QListWidgetItem) -> None:
        pack: packs.Pack = item.data(Qt.ItemDataRole.UserRole)
        on = item.checkState() == Qt.CheckState.Checked
        if on and not self._may_run(pack):
            # Python from outside the application: asked once per file, like a pickled model.
            if not ask(self, "pack.trust", name=pack.name, author=pack.author or tr("unknown")):
                self.list.blockSignals(True)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.list.blockSignals(False)
                return
            self._accepted[pack.id] = pack
        self._changed[pack.id] = on

    def _add(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, tr("Add a pack"), "", tr("ChartLibre packs (*{suffix})").format(suffix=packs.SUFFIX))
        if path:
            self.add_file(Path(path))

    def add_file(self, path: Path) -> None:
        try:
            packs.add(path)
        except (packs.PackError, OSError) as exc:
            show_message(self, "pack.not_added", name=path.name, why=tr(str(exc)))
            return
        self._added = True
        self.refresh()

    # ------------------------------------------------------------------
    def restart_needed(self) -> bool:
        """A pack was added, or a switch differs from what is stored: the app has to start again to show it."""
        stored = {pack.id: packs.is_switched_on(pack) for pack in packs.find()}
        return self._added or any(on != stored.get(pack_id, False) for pack_id, on in self._changed.items())

    def save(self) -> None:
        """Write the switches that changed, and trust the packs accepted here."""
        for pack in self._accepted.values():
            if self._changed.get(pack.id):
                packs.trust(pack)
        for pack_id, on in self._changed.items():
            packs.set_switched_on(pack_id, on)
        self._changed.clear()
        self._accepted.clear()
        self._added = False
