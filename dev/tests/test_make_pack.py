"""dev/tools/make_pack.py: a pack's folder is checked and written as a .clpack the application reads;
a pack's own translations answer after the application's."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from app.scanners.plugin_family import PluginFamily
from app.utils import i18n, packs
from dev.tools import make_pack
from test_packs import IMPORTER, folders  # noqa: F401 - the fixture


def pack_folder(tmp_path: Path, **manifest) -> Path:
    folder = make_pack.new(tmp_path / "source", "lab", "Lab pack")
    (folder / "importers" / "reader.py").write_text(IMPORTER)
    if manifest:
        path = folder / packs.MANIFEST
        path.write_text(json.dumps({**json.loads(path.read_text()), **manifest}))
    return folder


def test_a_new_pack_is_built_and_the_application_scans_it(folders, tmp_path):
    folder = pack_folder(tmp_path)
    (folder / "importers" / "__pycache__").mkdir()
    (folder / "importers" / "__pycache__" / "reader.pyc").write_bytes(b"x")
    (folder / ".DS_Store").write_bytes(b"x")
    assert make_pack.check(folder) == []
    written = make_pack.build(folder, packs.BUILTIN_DIR)
    assert written == packs.BUILTIN_DIR / "lab.clpack"
    with zipfile.ZipFile(written) as archive:
        assert sorted(archive.namelist()) == ["importers/reader.py", "pack.json"]
    packs.set_switched_on("lab", True)
    builtin = packs.APP_DIR / "importers"
    builtin.mkdir(parents=True)
    family = PluginFamily(label="", base_class="FileImporter", builtin_root=builtin, user_root=None,
                          module_prefix="_test_made_pack", pack_folder="importers")
    assert [entry["value"] for entry in family.discover()] == ["Pack reader"]


def test_what_is_wrong_is_all_said_and_nothing_is_written(tmp_path):
    folder = pack_folder(tmp_path, id="Bad Id", version="")
    (folder / "importers" / "broken.py").write_text("class X(:\n")
    (folder / "importers" / "nothing.py").write_text("x = 1\n")
    (folder / "charts" / "scatter.py").write_text('class S(BaseAxisRenderer):\n    Name = "Scatter Plot"\n')
    (folder / "extras").mkdir()
    (folder / "lib" / "other").mkdir(parents=True)
    with pytest.raises(packs.PackError) as error:
        make_pack.build(folder)
    said = str(error.value)
    for part in ('needs an "id"', 'needs a "version"', "importers/broken.py is not valid Python: line 1",
                 "importers/nothing.py declares no plugin", '"Scatter Plot" is already the name',
                 "The folder extras/ is not one a pack has"):
        assert part in said, part
    assert not list(tmp_path.glob("*.clpack"))


def test_a_folder_without_a_manifest_and_a_pack_that_adds_nothing(tmp_path):
    assert "no pack.json" in make_pack.check(tmp_path)[0]
    empty = make_pack.new(tmp_path / "empty", "empty", "")
    assert make_pack.check(empty) == ["The pack adds nothing: no plugin in charts, data_operations, importers, "
                                      "functions, ai_providers."]
    with pytest.raises(packs.PackError, match="not empty"):
        make_pack.new(empty, "again", "")


def test_the_command_line_checks_and_builds(tmp_path, capsys):
    folder = pack_folder(tmp_path)
    assert make_pack.main([str(folder), "--check"]) == 0
    assert make_pack.main([str(folder), str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "lab.clpack").is_file() and "Written" in capsys.readouterr().out
    (folder / packs.MANIFEST).unlink()
    assert make_pack.main([str(folder)]) == 1


def test_a_packs_own_translations_answer_after_the_applications(folders, tmp_path, monkeypatch):
    folder = pack_folder(tmp_path, default=True)
    catalogue = folder / "locales" / "it" / "pack.po"
    catalogue.parent.mkdir(parents=True)
    catalogue.write_text('msgid ""\nmsgstr ""\n\nmsgid "Pack reader"\nmsgstr "Lettore del pacchetto"\n\n'
                         'msgid "Save"\nmsgstr "NOT THIS"\n', encoding="utf-8")
    make_pack.build(folder, packs.BUILTIN_DIR)
    packs.sync()
    i18n._translation.cache_clear()
    monkeypatch.setattr(i18n, "_language", "it")
    try:
        assert i18n.tr("Pack reader") == "Lettore del pacchetto"
        assert i18n.tr("Save") == "Salva"  # the application's own word stays
        assert i18n.tr("Never translated anywhere") == "Never translated anywhere"
    finally:
        i18n._translation.cache_clear()
