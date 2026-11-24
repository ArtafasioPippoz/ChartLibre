"""The packs that ship with ChartLibre: each .clpack in app/packages is its source in dev/packs, and what
it adds is there when the application starts."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.utils import packs
from dev.tools import make_pack

ROOT = Path(__file__).resolve().parents[2]
SOURCES = sorted(path.parent for path in (ROOT / "dev" / "packs").glob("*/pack.json"))


@pytest.mark.parametrize("source", SOURCES, ids=lambda path: path.name)
def test_the_pack_file_is_its_source_as_it_is_now(source: Path) -> None:
    assert make_pack.check(source) == []
    built = ROOT / "app" / "packages" / f"{source.name}{packs.SUFFIX}"
    assert built.is_file(), f"build it: dev/tools/make_pack.py dev/packs/{source.name} app/packages"
    with zipfile.ZipFile(built) as archive:
        packed = {name: archive.read(name) for name in archive.namelist()}
    files = {path.relative_to(source).as_posix(): path.read_bytes() for path in make_pack._files(source)}
    stale = sorted(name for name in files.keys() | packed.keys() if files.get(name) != packed.get(name))
    assert not stale, f"dev/packs/{source.name} changed since its .clpack was built: {stale}"


def test_every_pack_file_has_its_source() -> None:
    assert sorted(path.stem for path in (ROOT / "app" / "packages").glob(f"*{packs.SUFFIX}")) == \
        [source.name for source in SOURCES]


def test_the_default_packs_plugins_are_among_the_applications() -> None:
    from app.scanners.axis_renderer_scanner import renderers
    from app.scanners.data_operation_scanner import data_operations

    assert {entry["value"]: entry.get("pack") for entry in renderers}.get("Wafer Map") == "semiconductors"
    assert {entry["value"]: entry.get("pack") for entry in data_operations}.get("Wafer Map") == "semiconductors"
