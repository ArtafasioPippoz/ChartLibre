"""Make an extension pack: a folder with a pack.json becomes a .clpack file (app.utils.packs reads it).

    .python/bin/python3 dev/tools/make_pack.py my_pack/                 # writes my_pack/../<id>.clpack
    .python/bin/python3 dev/tools/make_pack.py my_pack/ app/packages/   # into the application's own packs
    .python/bin/python3 dev/tools/make_pack.py --new my_pack/ --id lab --name "My lab"   # an empty one to fill

The folder is checked first, and nothing is written when something is wrong: the manifest, the folders'
names, every plugin file (it must parse and declare a class with a Name, as the application's scan asks),
and that no plugin takes the name of one built into ChartLibre - the built-in one would win and the pack's
never show. See dev/plans/extension_packs_plan.txt.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.utils import packs  # noqa: E402

#: What a pack's folder may hold beside pack.json and the plugin families.
OTHER_FOLDERS = ("lib", "locales", "demo", "docs")
#: Never packed: what Python and the Finder leave behind.
LEFT_OUT = ("__pycache__", ".DS_Store", "Thumbs.db")


def _files(folder: Path) -> list[Path]:
    return sorted(path for path in folder.rglob("*")
                  if path.is_file() and not any(part in LEFT_OUT or part.startswith(".") for part in
                                                path.relative_to(folder).parts))


def _builtin_names(family: str) -> set[str]:
    """The names the application's own plugins of *family* declare."""
    names: set[str] = set()
    for path in (ROOT / "app" / family).rglob("*.py"):
        if packs.pack_of(path):  # an installed pack's copy, this very one perhaps: not the application's own
            continue
        names.update(packs._declared(path.read_text(encoding="utf-8", errors="replace"))[0])
    return names


def check(folder: Path) -> list[str]:
    """What is wrong with the pack in *folder*, in sentences; empty when it can be built."""
    manifest_path = folder / packs.MANIFEST
    if not manifest_path.is_file():
        return [f"There is no {packs.MANIFEST} in {folder}."]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"{packs.MANIFEST} cannot be read: {exc}"]
    if not isinstance(manifest, dict):
        return [f"{packs.MANIFEST} is not a list of names and values."]
    wrong: list[str] = []
    pack_id = str(manifest.get("id", ""))
    if not packs._ID.match(pack_id):
        wrong.append(f'{packs.MANIFEST} needs an "id" of small letters, digits and underscores.')
    for key in ("name", "version", "description"):
        if not str(manifest.get(key, "")).strip():
            wrong.append(f'{packs.MANIFEST} needs a "{key}".')
    if not isinstance(manifest.get("packages", []), list):
        wrong.append(f'"packages" in {packs.MANIFEST} is a list of pip names.')

    for entry in sorted(folder.iterdir()):
        if entry.is_dir() and entry.name not in (*packs.FAMILIES, *OTHER_FOLDERS, *LEFT_OUT) \
                and not entry.name.startswith("."):
            wrong.append(f"The folder {entry.name}/ is not one a pack has "
                         f"({', '.join((*packs.FAMILIES, *OTHER_FOLDERS))}).")
    lib = folder / "lib"
    if lib.is_dir() and pack_id and [item.name for item in lib.iterdir() if item.is_dir()
                                     and item.name not in LEFT_OUT] != [pack_id]:
        wrong.append(f"lib/ holds one folder, named as the pack: lib/{pack_id}/.")

    plugins = 0
    for family in packs.FAMILIES:
        builtin = _builtin_names(family)
        for path in sorted((folder / family).glob("**/*.py")) if (folder / family).is_dir() else []:
            if path.name.startswith("_") or any(part in LEFT_OUT for part in path.parts):
                continue
            where = path.relative_to(folder).as_posix()
            source = path.read_text(encoding="utf-8", errors="replace")
            try:
                ast.parse(source)
            except SyntaxError as exc:
                wrong.append(f"{where} is not valid Python: line {exc.lineno}, {exc.msg}.")
                continue
            names = packs._declared(source)[0]
            if not names:
                wrong.append(f'{where} declares no plugin: a class with Name = "..." (name = for a fit function).')
            plugins += len(names)
            for name in sorted(set(names) & builtin):
                wrong.append(f'{where}: "{name}" is already the name of a plugin built into ChartLibre.')
    if not plugins and not wrong:
        wrong.append(f"The pack adds nothing: no plugin in {', '.join(packs.FAMILIES)}.")
    return wrong


def build(folder: Path, target: Path | None = None) -> Path:
    """Write <id>.clpack from *folder* into *target* (a folder; the pack folder's parent by default).

    Raises packs.PackError, with every finding, when the folder does not pass check().
    """
    folder = folder.resolve()
    wrong = check(folder)
    if wrong:
        raise packs.PackError("\n".join(wrong))
    pack_id = json.loads((folder / packs.MANIFEST).read_text(encoding="utf-8"))["id"]
    target = (target or folder.parent).resolve()
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{pack_id}{packs.SUFFIX}"
    partial = path.with_suffix(".part")
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in _files(folder):
            archive.write(file, file.relative_to(folder).as_posix())
    partial.replace(path)
    made = packs.read(path)
    if made.error:  # what the application itself would say of it
        path.unlink(missing_ok=True)
        raise packs.PackError(made.error)
    return path


def new(folder: Path, pack_id: str, name: str) -> Path:
    """Start a pack in *folder*: its manifest and an empty folder per plugin family."""
    if not packs._ID.match(pack_id):
        raise packs.PackError('The id is small letters, digits and underscores, starting with a letter.')
    if folder.exists() and any(folder.iterdir()):
        raise packs.PackError(f"{folder} is not empty.")
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {"id": pack_id, "name": name or pack_id, "version": "0.1.0", "description": "What this pack adds.",
                "author": "", "needs_app": "", "packages": []}
    (folder / packs.MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for family in packs.FAMILIES[:3]:  # charts, data_operations, importers: what most packs add
        (folder / family).mkdir()
    return folder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path, help="the pack's folder (it holds pack.json)")
    parser.add_argument("target", type=Path, nargs="?", help="where the .clpack is written")
    parser.add_argument("--new", action="store_true", help="start an empty pack in the folder")
    parser.add_argument("--id", default="", help="with --new: the pack's id")
    parser.add_argument("--name", default="", help="with --new: the pack's name")
    parser.add_argument("--check", action="store_true", help="check only, write nothing")
    args = parser.parse_args(argv)
    try:
        if args.new:
            print(f"Started {new(args.folder, args.id or args.folder.name.lower(), args.name)}")
        elif args.check:
            wrong = check(args.folder)
            print("\n".join(wrong) if wrong else "Nothing wrong.")
            return 1 if wrong else 0
        else:
            print(f"Written {build(args.folder, args.target)}")
    except packs.PackError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
