"""Edit Localization (ID100): what is typed is kept when the language changes and when the dialog closes; a
language can be removed."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.utils import i18n


def _catalogue(root: Path, code: str, entries: dict[str, str]) -> Path:
    path = root / code / "LC_MESSAGES" / f"{i18n.DOMAIN}.po"
    i18n._write_po({"": f"Language: {code}\nContent-Type: text/plain; charset=UTF-8\n", **entries}, path)
    return path


@pytest.fixture
def dialog(qapp, tmp_path: Path, monkeypatch):
    from dev.developer import localization_helper as helper

    monkeypatch.setattr(i18n, "LOCALES_DIR", tmp_path)
    monkeypatch.setattr(i18n, "source_translator_calls", lambda root=None: {"Apple", "Pear"})
    _catalogue(tmp_path, "de", {"Apple": "Apfel", "Pear": ""})
    _catalogue(tmp_path, "it", {"Apple": "Mela", "Pear": ""})
    built = helper.EditLocalizationDialog()
    yield built
    built._dirty = False
    built.close()


def _type(dialog, source: str, text: str) -> None:
    for row in range(dialog._table.rowCount()):
        if dialog._table.item(row, 0).text() == source:
            dialog._table.item(row, 1).setText(text)
            return
    raise AssertionError(source)


def test_changing_the_language_keeps_what_was_typed(dialog, tmp_path: Path) -> None:
    combo = dialog._language_combo
    combo.setCurrentIndex(combo.findData("de"))
    _type(dialog, "Pear", "Birne")
    combo.setCurrentIndex(combo.findData("it"))  # no Save pressed
    assert i18n._parse_po(tmp_path / "de" / "LC_MESSAGES" / "ChartLibre.po")["Pear"] == "Birne"
    assert i18n._parse_po(tmp_path / "it" / "LC_MESSAGES" / "ChartLibre.po")["Pear"] == ""  # not the other's


def test_close_keeps_what_was_typed_and_there_is_no_cancel(dialog, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QPushButton

    combo = dialog._language_combo
    combo.setCurrentIndex(combo.findData("it"))
    _type(dialog, "Pear", "Pera")
    assert [b.text() for b in dialog.findChildren(QPushButton) if b.text() in ("OK", "Cancel", "Close")] == ["Close"]
    dialog.reject()  # Esc, or the window's own close button
    assert i18n._parse_po(tmp_path / "it" / "LC_MESSAGES" / "ChartLibre.po")["Pear"] == "Pera"


def test_a_language_is_removed_to_the_trash_after_a_question(dialog, tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtCore import QFile

    from app.utils import messages

    trashed: list[str] = []
    monkeypatch.setattr(QFile, "moveToTrash", staticmethod(lambda path: trashed.append(path) or True))
    combo = dialog._language_combo
    combo.setCurrentIndex(combo.findData("de"))
    monkeypatch.setattr(messages, "ask", lambda *a, **k: False)
    dialog._on_remove_language()
    assert trashed == [] and combo.findData("de") >= 0  # No: nothing happens
    monkeypatch.setattr(messages, "ask", lambda *a, **k: True)
    _type(dialog, "Pear", "Birne")
    dialog._on_remove_language()
    assert trashed == [str(tmp_path / "de")] and combo.findData("de") < 0
    assert dialog._current_language() == "it" and not dialog._dirty
