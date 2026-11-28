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
    # One pack, in the temporary folder: nothing reaches dev/packs.
    packs = tmp_path / "packs"
    (packs / "fruit").mkdir(parents=True)
    (packs / "fruit" / "pack.json").write_text('{"name": "Fruit"}', encoding="utf-8")
    monkeypatch.setattr(helper, "PACKS_DIR", packs)
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


def test_a_packs_catalogue_is_edited_and_written_into_the_packs_own_folder(qapp, tmp_path: Path, monkeypatch) -> None:
    import json

    from dev.developer import localization_helper as helper

    app_locales = tmp_path / "locales"
    packs_dir = tmp_path / "packs"
    (packs_dir / "lab").mkdir(parents=True)
    (packs_dir / "lab" / "pack.json").write_text(json.dumps({"id": "lab", "name": "Lab", "description": "Readers."}))
    monkeypatch.setattr(i18n, "LOCALES_DIR", app_locales)
    monkeypatch.setattr(helper, "PACKS_DIR", packs_dir)
    monkeypatch.setattr(i18n, "source_translator_calls", lambda root=None: {"Pack string"} if root else {"App string"})
    app_po = _catalogue(app_locales, "it", {"App string": "Stringa"})
    dialog = helper.EditLocalizationDialog()
    try:
        assert [dialog._catalogue_combo.itemData(i) for i in range(dialog._catalogue_combo.count())] == ["", "lab"]
        dialog._catalogue_combo.setCurrentIndex(dialog._catalogue_combo.findData("lab"))
        shown = {dialog._table.item(row, 0).text() for row in range(dialog._table.rowCount())}
        assert shown == {"Pack string", "Lab", "Readers."}  # the pack's, not the application's
        _type(dialog, "Pack string", "Stringa del pacchetto")
        dialog._catalogue_combo.setCurrentIndex(0)  # no Save pressed
        pack_po = packs_dir / "lab" / "locales" / "it" / "pack.po"
        assert i18n._parse_po(pack_po)["Pack string"] == "Stringa del pacchetto"
        assert not pack_po.with_suffix(".mo").exists()
        assert "Pack string" not in i18n._parse_po(app_po)  # the application's catalogue is untouched
        assert {dialog._table.item(row, 0).text() for row in range(dialog._table.rowCount())} == {"App string"}
    finally:
        dialog._dirty = False
        dialog.close()


def _select(dialog, source: str) -> None:
    dialog._table.clearSelection()
    for row in range(dialog._table.rowCount()):
        if dialog._table.item(row, 0).text() == source:
            dialog._table.selectRow(row)


def test_copy_source_puts_the_english_in_the_selected_rows_only(dialog) -> None:
    _select(dialog, "Pear")
    dialog._on_copy_source()
    texts = {dialog._table.item(row, 0).text(): dialog._table.item(row, 1).text()
             for row in range(dialog._table.rowCount())}
    assert texts == {"Apple": "Apfel", "Pear": "Pear"}
    assert dialog._dirty


def test_translate_all_languages_fills_and_saves_each(dialog, tmp_path: Path, monkeypatch, qapp) -> None:
    import threading

    from app.utils import machine_translation as mt
    from dev.developer import localization_helper as helper

    def fake(missing, *, language, on_result, **_kw):
        for source in missing:
            on_result(source, f"{source}-{language}")
        return mt.TranslationRun()

    monkeypatch.setattr(mt, "translate_all", fake)
    monkeypatch.setattr(helper, "ask_before_auto_translate", lambda parent: True)
    shown: list[str] = []
    monkeypatch.setattr(helper, "show_message", lambda parent, key, **kw: shown.append((key, kw)))
    dialog._on_translate_all_languages()
    for _ in range(300):
        qapp.processEvents()
        if dialog._all_queue is None and dialog._translation_task is None:
            break
        threading.Event().wait(0.01)
    # ChartLibre's Pear in two languages; the pack's Apple, Pear and Fruit in two.
    assert shown == [("dev.localization_auto_translated", {"count": 8})]
    for code in ("de", "it"):
        saved = i18n._parse_po(tmp_path / code / "LC_MESSAGES" / f"{i18n.DOMAIN}.po")
        assert saved["Pear"] == f"Pear-{code}"
        pack = i18n._parse_po(tmp_path / "packs" / "fruit" / "locales" / code / "pack.po")
        assert pack["Fruit"] == f"Fruit-{code}"


def test_translate_all_does_the_packs_first_and_a_failure_does_not_stop_it(dialog, tmp_path: Path, monkeypatch,
                                                                           qapp) -> None:
    import threading

    from app.utils import machine_translation as mt
    from dev.developer import localization_helper as helper

    order: list[tuple[str, str]] = []

    def fake(missing, *, language, on_result, **_kw):
        order.append((dialog._current_pack(), language))
        if dialog._current_pack() == "fruit" and language == "de":
            raise RuntimeError("the service is down")
        for source in missing:
            on_result(source, f"{source}-{language}")
        return mt.TranslationRun()

    monkeypatch.setattr(mt, "translate_all", fake)
    monkeypatch.setattr(helper, "ask_before_auto_translate", lambda parent: True)
    shown: list[str] = []
    monkeypatch.setattr(helper, "show_message", lambda parent, key, **kw: shown.append((key, kw)))
    dialog._on_translate_all_languages()
    for _ in range(300):
        qapp.processEvents()
        if dialog._all_queue is None and dialog._translation_task is None:
            break
        threading.Event().wait(0.01)
    assert order == [("fruit", "de"), ("fruit", "it"), ("", "de"), ("", "it")]
    # The pack's Italian (3) and ChartLibre's Pear in two languages: done in spite of the failure, said shortly.
    assert shown == [("dev.localization_auto_translate_partial", {"count": 5})]
    assert i18n._parse_po(tmp_path / "packs" / "fruit" / "locales" / "it" / "pack.po")["Fruit"] == "Fruit-it"
