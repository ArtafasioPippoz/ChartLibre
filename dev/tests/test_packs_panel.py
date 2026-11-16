"""Preferences > Packages: the list of packs, the switches written at Save, trust asked once, add and remove."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from app.utils import packs
from app.widgets import packs_panel
from app.widgets.packs_panel import PacksPanel
from test_packs import folders, make_pack  # noqa: F401 - the fixture


def check(panel: PacksPanel, row: int, on: bool) -> None:
    panel.list.item(row).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)


def test_a_switch_is_written_at_save_not_before(qapp, folders):
    make_pack(packs.BUILTIN_DIR, manifest={"default": True, "version": "1.0", "description": "Readers."})
    panel = PacksPanel()
    item = panel.list.item(0)
    assert item.text().splitlines() == ["Lab pack  1.0", "Readers.", "Adds: file readers (1)"]
    assert item.checkState() == Qt.CheckState.Checked and not panel.remove_button.isEnabled()
    check(panel, 0, False)
    assert packs.is_switched_on(packs.find()[0])
    panel.save()
    assert not packs.is_switched_on(packs.find()[0])


def test_a_pack_of_the_user_asks_for_trust_once_and_no_leaves_it_off(qapp, folders, monkeypatch):
    make_pack(packs.USER_DIR, manifest={"author": "A lab"})
    asked = []
    answer = [False]
    monkeypatch.setattr(packs_panel, "ask", lambda _parent, key, **fields: asked.append((key, fields)) or answer[0])
    panel = PacksPanel()
    check(panel, 0, True)
    assert asked[0][0] == "pack.trust" and asked[0][1]["author"] == "A lab"
    assert panel.list.item(0).checkState() == Qt.CheckState.Unchecked
    answer[0] = True
    check(panel, 0, True)
    check(panel, 0, False)
    check(panel, 0, True)
    assert len(asked) == 2  # accepted in this window: not asked again
    assert not packs.is_enabled(packs.find()[0])  # nothing until Save
    panel.save()
    assert packs.is_enabled(packs.find()[0])


def test_a_file_is_added_listed_and_removed_and_a_bad_one_is_said(qapp, folders, monkeypatch, tmp_path):
    said = []
    monkeypatch.setattr(packs_panel, "show_message", lambda _parent, key, **fields: said.append((key, fields)))
    monkeypatch.setattr(packs_panel, "ask", lambda *_args, **_fields: True)
    panel = PacksPanel()
    assert panel.list.count() == 0 and not panel.empty_note.isHidden()
    bad = tmp_path / "bad.clpack"
    bad.write_text("no zip")
    panel.add_file(bad)
    assert said[0][0] == "pack.not_added" and panel.list.count() == 0
    panel.add_file(make_pack(tmp_path / "downloads"))
    assert panel.list.count() == 1 and (packs.USER_DIR / "lab.clpack").is_file()
    panel.list.setCurrentRow(0)
    assert panel.remove_button.isEnabled()
    panel.remove_button.click()
    assert panel.list.count() == 0 and not (packs.USER_DIR / "lab.clpack").exists()


def test_a_pack_that_cannot_be_used_has_no_check_box_and_says_why(qapp, folders):
    make_pack(packs.BUILTIN_DIR, manifest={"needs_app": "99.0"})
    panel = PacksPanel()
    item = panel.list.item(0)
    assert "needs ChartLibre 99.0" in item.text()
    assert not item.flags() & Qt.ItemFlag.ItemIsUserCheckable


def test_the_settings_window_has_the_page_and_fits_a_laptop(qapp, folders):
    from app.dialogs.settings_dialog import SettingsDialog

    for index in range(6):
        make_pack(packs.BUILTIN_DIR, f"pack{index}", manifest={"default": True, "description": "Words. " * 12})
    dialog = SettingsDialog()
    try:
        names = [dialog._sidebar.item(row).text() for row in range(dialog._sidebar.count())]
        assert "Packages" in names
        dialog._sidebar.setCurrentRow(names.index("Packages"))
        dialog.show()
        qapp.processEvents()
        assert dialog.width() <= 1280 and dialog.height() <= 720
        assert dialog._packs_panel.list.count() == 6
    finally:
        dialog.close()
