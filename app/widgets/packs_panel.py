"""Preferences > Packages: the extension packs, each switched on or off (app.utils.packs)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
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

from app.styles.style import mark_destructive_button
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
    """The lines of a pack's row: its name and version, what it is, what it adds or what is wrong."""
    lines = [f"{pack.name}  {pack.version}".rstrip()]
    if pack.description:
        lines.append(pack.description)
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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        #: pack id -> the switch as the user left it, where it differs from what is stored.
        self._changed: dict[str, bool] = {}
        #: The user's packs accepted in this window, trusted for good at save().
        self._accepted: dict[str, packs.Pack] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget(self)
        self.list.setWordWrap(True)
        self.list.setAlternatingRowColors(True)
        self.list.setMinimumHeight(170)
        self.list.setSpacing(3)
        self.list.itemChanged.connect(self._switched)
        self.list.currentItemChanged.connect(lambda *_: self._update_buttons())
        layout.addWidget(self.list, 1)

        self.empty_note = QLabel(tr("No packs yet. A pack is a .clpack file that adds analyses, chart types or "
                                    "file readers."), self)
        self.empty_note.setProperty("muted", True)
        self.empty_note.setWordWrap(True)
        layout.addWidget(self.empty_note)

        buttons = QHBoxLayout()
        self.add_button = QPushButton(tr("Add from a file…"), self)
        self.add_button.clicked.connect(self._add)
        self.remove_button = mark_destructive_button(QPushButton(tr("Remove"), self))
        self.remove_button.setToolTip(tr("Delete a pack you added. A pack that came with ChartLibre can only "
                                         "be switched off."))
        self.remove_button.clicked.connect(self._remove)
        self.folder_button = QPushButton(tr("Open folder"), self)
        self.folder_button.clicked.connect(self._open_folder)
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        buttons.addWidget(self.folder_button)
        layout.addLayout(buttons)

        note = QLabel(tr("A pack switched on or off is applied the next time the app starts."), self)
        note.setProperty("muted", True)
        note.setWordWrap(True)
        layout.addWidget(note)
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
        self._update_buttons()

    def _may_run(self, pack: packs.Pack) -> bool:
        return packs.is_trusted(pack) or self._accepted.get(pack.id) is not None

    def _current(self) -> packs.Pack | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _update_buttons(self) -> None:
        pack = self._current()
        self.remove_button.setEnabled(pack is not None and not pack.builtin)

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
        self.refresh()

    def _remove(self) -> None:
        pack = self._current()
        if pack is None or pack.builtin or not ask(self, "pack.confirm_remove", name=pack.name):
            return
        packs.remove(pack)
        self._changed.pop(pack.id, None)
        self._accepted.pop(pack.id, None)
        self.refresh()

    def _open_folder(self) -> None:
        packs.USER_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(packs.USER_DIR)))

    # ------------------------------------------------------------------
    def save(self) -> None:
        """Write the switches that changed, and trust the packs accepted here."""
        for pack in self._accepted.values():
            if self._changed.get(pack.id):
                packs.trust(pack)
        for pack_id, on in self._changed.items():
            packs.set_switched_on(pack_id, on)
        self._changed.clear()
        self._accepted.clear()
