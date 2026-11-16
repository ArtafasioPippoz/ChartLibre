"""Extension packs (app.utils.packs): found, switched, unpacked safely, scanned by a plugin family."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from app.scanners.plugin_family import PluginFamily
from app.utils import config, packs

IMPORTER = '''
from app.plugin_api.importers.base import FileImporter

class TdmsLike(FileImporter):
    Name = "Pack reader"
    Suffixes = [".pk"]
'''


def make_pack(folder: Path, pack_id: str = "lab", *, manifest: dict | None = None, files: dict | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{pack_id}{packs.SUFFIX}"
    with zipfile.ZipFile(path, "w") as archive:
        if manifest is not False:
            archive.writestr(packs.MANIFEST, json.dumps({"id": pack_id, "name": "Lab pack", **(manifest or {})}))
        for name, text in (files or {"importers/reader.py": IMPORTER}).items():
            archive.writestr(name, text)
    return path


@pytest.fixture
def folders(tmp_path, monkeypatch):
    """The application's and the user's pack folders, and a user.json, of this test alone."""
    monkeypatch.setattr(packs, "BUILTIN_DIR", tmp_path / "app_packages")
    monkeypatch.setattr(packs, "USER_DIR", tmp_path / "user_packages")
    user_json = tmp_path / "user.json"
    user_json.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "USER_CONFIG_PATH", user_json)
    return tmp_path


def family(tmp_path: Path) -> PluginFamily:
    builtin = tmp_path / "builtin"
    builtin.mkdir(exist_ok=True)
    return PluginFamily(label="", base_class="FileImporter", builtin_root=builtin, user_root=None,
                        module_prefix="_test_pack_importer", string_list_attrs=("Suffixes",),
                        pack_folder="importers")


def test_a_default_pack_of_the_application_is_scanned_and_names_itself(folders):
    make_pack(packs.BUILTIN_DIR, manifest={"default": True, "version": "1.2"})
    (pack,) = packs.find()
    assert (pack.id, pack.name, pack.version, pack.error) == ("lab", "Lab pack", "1.2", "")
    assert packs.is_enabled(pack)
    (entry,) = family(folders).discover()
    assert entry["value"] == "Pack reader" and entry["pack"] == "lab"
    assert family(folders).load(entry).__name__ == "TdmsLike"


def test_switched_off_it_adds_nothing_and_on_again_it_is_not_unpacked_twice(folders):
    make_pack(packs.BUILTIN_DIR, manifest={"default": True})
    (pack,) = packs.find()
    packs.set_switched_on("lab", False)
    assert family(folders).discover() == []
    packs.set_switched_on("lab", True)
    folder = packs.unpack(pack)
    stamp = folder.stat().st_mtime_ns
    assert len(family(folders).discover()) == 1
    assert folder.stat().st_mtime_ns == stamp
    assert [item.name for item in (packs.USER_DIR / "unpacked").iterdir()] == [folder.name]


def test_a_pack_the_user_added_runs_only_once_trusted_and_a_changed_file_asks_again(folders):
    path = make_pack(packs.USER_DIR)
    packs.set_switched_on("lab", True)
    (pack,) = packs.find()
    assert not pack.builtin and not packs.is_enabled(pack)
    assert family(folders).discover() == []
    packs.trust(pack)
    assert len(family(folders).discover()) == 1
    make_pack(packs.USER_DIR, files={"importers/reader.py": IMPORTER + "# changed\n"})
    assert path.exists() and not packs.is_enabled(packs.find()[0])


def test_a_changed_pack_replaces_its_old_folder(folders):
    make_pack(packs.BUILTIN_DIR, manifest={"default": True})
    old = packs.unpack(packs.find()[0])
    make_pack(packs.BUILTIN_DIR, manifest={"default": True, "version": "2"})
    new = packs.unpack(packs.find()[0])
    assert new != old and new.is_dir() and not old.exists()


@pytest.mark.parametrize(
    ("manifest", "said"),
    [
        (False, "no pack.json"),
        ({"id": "Bad Id"}, '"id"'),
        ({"needs_app": "99.0"}, "needs ChartLibre 99.0"),
    ],
)
def test_a_pack_that_cannot_be_used_is_listed_with_why_and_left_off(folders, manifest, said):
    make_pack(packs.BUILTIN_DIR, manifest=manifest if manifest is False else {"default": True, **manifest})
    (pack,) = packs.find()
    assert said in pack.error and not packs.is_enabled(pack)
    assert family(folders).discover() == []


def test_a_file_that_is_no_zip_and_a_second_pack_of_the_same_id_are_listed_not_used(folders):
    make_pack(packs.BUILTIN_DIR, manifest={"default": True})
    packs.BUILTIN_DIR.joinpath(f"broken{packs.SUFFIX}").write_text("not a zip")
    make_pack(packs.USER_DIR)
    by_place = {(pack.path.parent.name, pack.path.stem): pack.error for pack in packs.find()}
    assert by_place[("app_packages", "lab")] == ""
    assert "cannot be read" in by_place[("app_packages", "broken")]
    assert "already called" in by_place[("user_packages", "lab")]


@pytest.mark.parametrize("member", ["../outside.py", "/absolute.py", "importers/../../outside.py"])
def test_a_member_that_would_land_outside_the_folder_stops_the_unpacking(folders, member):
    make_pack(packs.BUILTIN_DIR, manifest={"default": True}, files={member: "x = 1\n"})
    (pack,) = packs.find()
    with pytest.raises(packs.PackError, match="outside its folder"):
        packs.unpack(pack)
    assert family(folders).discover() == []  # logged and left out, the application goes on
    assert not (folders / "outside.py").exists()


def test_a_packs_own_modules_are_importable_by_its_id(folders):
    make_pack(packs.BUILTIN_DIR, "labtools", manifest={"default": True},
              files={"lib/labtools/__init__.py": "ANSWER = 42\n", "importers/reader.py": IMPORTER})
    family(folders).discover()
    import labtools

    assert labtools.ANSWER == 42
