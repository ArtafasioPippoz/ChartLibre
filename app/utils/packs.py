"""Extension packs: a .clpack file adds a set of plugins, switched on or off in Preferences.

A pack is a zip renamed .clpack. Inside, a manifest (pack.json) and one folder per plugin family, named as
under app/ - charts, data_operations, importers, functions, ai_providers - plus lib/<pack id>/ for the pack's
own helper modules. The packs that come with the application are in app/packages/, those the user adds in
user/packages/. An enabled pack is unpacked once, into user/packages/unpacked/<id>-<fingerprint>/, and its
folders are handed to the plugin families as more roots to scan (app.scanners.plugin_family).

A pack is Python run with the user's rights. One that came with the application is trusted; one the user
added runs only once its fingerprint was accepted on this computer (trust), like a pickled model.
A pack that cannot be read is listed with its error and left off: it never stops the application.

See dev/plans/extension_packs_plan.txt.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from app import APP_VERSION
from app.logs.logger import applogger
from app.utils.config import USER_CONTENT_DIR, get_value, set_value

SUFFIX = ".clpack"
MANIFEST = "pack.json"
#: The folders of a pack that hold plugins, each named as its family's folder under app/.
FAMILIES = ("charts", "data_operations", "importers", "functions", "ai_providers")
BUILTIN_DIR: Path = Path(__file__).resolve().parent.parent / "packages"
USER_DIR: Path = USER_CONTENT_DIR / "packages"
#: user.json keys: {pack id: on or off}, and the fingerprints of the user's packs this computer runs.
STATE_KEY = "packs"
TRUST_KEY = "trusted_packs"
#: A pack is source code and a few sample files: more than this unpacked is refused.
MAX_UNPACKED_BYTES = 50 * 1024 * 1024
_ID = re.compile(r"[a-z][a-z0-9_]*\Z")


class PackError(ValueError):
    """A pack that cannot be read or unpacked, in words for the user."""


@dataclass(slots=True)
class Pack:
    """One .clpack file and what its manifest says."""

    path: Path
    #: It came with the application (app/packages), not from the user.
    builtin: bool
    id: str = ""
    name: str = ""
    version: str = ""
    description: str = ""
    author: str = ""
    #: The oldest ChartLibre it runs on; empty for any.
    needs_app: str = ""
    #: pip names it needs beyond the application's own.
    packages: list[str] = field(default_factory=list)
    #: On until switched off (the application's own packs only).
    default: bool = False
    #: SHA-256 of the file.
    fingerprint: str = ""
    #: Why it cannot be used; empty when it can.
    error: str = ""


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text))


def read(path: Path, *, builtin: bool = False) -> Pack:
    """The pack in *path*; what is wrong with it, if anything, is in its ``error``."""
    pack = Pack(path=path, builtin=builtin, id=path.stem, name=path.stem)
    try:
        pack.fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read(MANIFEST).decode("utf-8"))
        if not isinstance(manifest, dict):
            raise PackError(f"{MANIFEST} is not a list of names and values.")
        pack_id = str(manifest.get("id", ""))
        if not _ID.match(pack_id):
            raise PackError(f'{MANIFEST} needs an "id" of small letters, digits and underscores.')
        pack.id = pack_id
        pack.name = str(manifest.get("name") or pack_id)
        for key in ("version", "description", "author", "needs_app"):
            setattr(pack, key, str(manifest.get(key, "")))
        packages = manifest.get("packages", [])
        pack.packages = [str(item) for item in packages] if isinstance(packages, list) else []
        pack.default = builtin and bool(manifest.get("default", False))
        if pack.needs_app and _version(pack.needs_app) > _version(APP_VERSION):
            raise PackError(f"It needs ChartLibre {pack.needs_app} or later.")
    except KeyError:
        pack.error = f"It has no {MANIFEST}."
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as exc:
        pack.error = f"It cannot be read: {exc}"
    except PackError as exc:
        pack.error = str(exc)
    return pack


def find() -> list[Pack]:
    """Every pack file, the application's first; of two with one id the first is used, the other listed as such."""
    found: list[Pack] = []
    seen: set[str] = set()
    for folder, builtin in ((BUILTIN_DIR, True), (USER_DIR, False)):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob(f"*{SUFFIX}")):
            pack = read(path, builtin=builtin)
            if not pack.error and pack.id in seen:
                pack.error = f'Another pack is already called "{pack.id}".'
            elif not pack.error:
                seen.add(pack.id)
            found.append(pack)
    return found


# ----------------------------------------------------------------------
# On, off and trusted
# ----------------------------------------------------------------------
def _state() -> dict:
    value = get_value(STATE_KEY, {})
    return value if isinstance(value, dict) else {}


def _trusted() -> set[str]:
    value = get_value(TRUST_KEY, [])
    return {str(item) for item in value} if isinstance(value, list) else set()


def is_trusted(pack: Pack) -> bool:
    return pack.builtin or pack.fingerprint in _trusted()


def trust(pack: Pack) -> None:
    """Remember on this computer that this pack, as it is now, may run."""
    known = _trusted()
    if pack.fingerprint and pack.fingerprint not in known:
        set_value(TRUST_KEY, sorted(known | {pack.fingerprint}))


def is_switched_on(pack: Pack) -> bool:
    """What Preferences shows: the user's choice, or the pack's own default."""
    return bool(_state().get(pack.id, pack.default))


def set_switched_on(pack_id: str, on: bool) -> None:
    """Applies at the next start: the plugin families are scanned once."""
    set_value(STATE_KEY, {**_state(), pack_id: bool(on)})


def is_enabled(pack: Pack) -> bool:
    """Its plugins are loaded: readable, switched on and allowed to run."""
    return not pack.error and is_switched_on(pack) and is_trusted(pack)


# ----------------------------------------------------------------------
# Unpacking
# ----------------------------------------------------------------------
def _checked_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """The archive's members, none of which may land outside the pack's folder."""
    members = archive.infolist()
    if sum(member.file_size for member in members) > MAX_UNPACKED_BYTES:
        raise PackError(f"It is larger than {MAX_UNPACKED_BYTES // (1024 * 1024)} MB unpacked.")
    for member in members:
        name = PurePosixPath(member.filename.replace("\\", "/"))
        is_link = (member.external_attr >> 16) & 0o170000 == 0o120000
        if name.is_absolute() or ".." in name.parts or ":" in member.filename or is_link:
            raise PackError(f"It holds a file that would be written outside its folder: {member.filename}")
    return members


def unpack(pack: Pack) -> Path:
    """The folder *pack* is unpacked in, written now unless this very file was unpacked before."""
    target = USER_DIR / "unpacked" / f"{pack.id}-{pack.fingerprint[:16]}"
    if target.is_dir():
        return target
    try:
        with zipfile.ZipFile(pack.path) as archive:
            members = _checked_members(archive)
            partial = target.with_name(target.name + ".part")
            shutil.rmtree(partial, ignore_errors=True)
            archive.extractall(partial, members=members)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PackError(f"It cannot be unpacked: {exc}") from exc
    # Earlier versions of the same pack: a changed file has another fingerprint and its own folder.
    for old in target.parent.glob(f"{pack.id}-*"):
        if old != partial and re.fullmatch(rf"{pack.id}-[0-9a-f]{{16}}", old.name):
            shutil.rmtree(old, ignore_errors=True)
    partial.rename(target)
    return target


def roots(family: str) -> list[tuple[Path, str]]:
    """(folder, pack id) of every enabled pack that has plugins of *family*, the pack unpacked if need be."""
    found: list[tuple[Path, str]] = []
    for pack in find():
        if not is_enabled(pack):
            continue
        try:
            folder = unpack(pack)
        except PackError as exc:
            applogger.error("The pack %s is left out. %s", pack.path.name, exc)
            continue
        lib = folder / "lib"
        if lib.is_dir() and str(lib) not in sys.path:
            sys.path.append(str(lib))  # the pack's own modules: "from <pack id> import ..."
        if (folder / family).is_dir():
            found.append((folder / family, pack.id))
    return found


# ----------------------------------------------------------------------
# What Preferences does with the files
# ----------------------------------------------------------------------
def contents(pack: Pack) -> dict[str, int]:
    """family -> how many plugin files *pack* holds for it, read from the archive without unpacking."""
    counts: dict[str, int] = {}
    try:
        with zipfile.ZipFile(pack.path) as archive:
            names = archive.namelist()
    except (OSError, zipfile.BadZipFile):
        return counts
    for name in names:
        parts = PurePosixPath(name).parts
        if len(parts) >= 2 and parts[0] in FAMILIES and name.endswith(".py") and not parts[-1].startswith("_"):
            counts[parts[0]] = counts.get(parts[0], 0) + 1
    return counts


def missing_packages(pack: Pack) -> list[str]:
    """The pip names *pack* needs that this Python does not have."""
    from importlib import metadata

    missing = []
    for name in pack.packages:
        try:
            metadata.distribution(name)
        except metadata.PackageNotFoundError:
            missing.append(name)
    return missing


def add(source: Path) -> Pack:
    """Copy the pack file *source* into the user's folder; raises PackError when it is not a usable pack."""
    pack = read(source)
    if pack.error:
        raise PackError(pack.error)
    if any(other.id == pack.id and other.builtin for other in find()):
        raise PackError(f'A pack that came with ChartLibre is already called "{pack.id}".')
    USER_DIR.mkdir(parents=True, exist_ok=True)
    for other in find():  # a newer file of a pack the user already has replaces it
        if other.id == pack.id and not other.builtin and other.path != source:
            other.path.unlink(missing_ok=True)
    target = USER_DIR / f"{pack.id}{SUFFIX}"
    if source.resolve() != target.resolve():
        shutil.copyfile(source, target)
    return read(target)


def remove(pack: Pack) -> None:
    """Delete a pack the user added: its file, what was unpacked from it and its switch."""
    if pack.builtin:
        raise PackError("A pack that came with ChartLibre can be switched off, not removed.")
    pack.path.unlink(missing_ok=True)
    for folder in (USER_DIR / "unpacked").glob(f"{pack.id}-*"):
        shutil.rmtree(folder, ignore_errors=True)
    state = _state()
    if pack.id in state:
        set_value(STATE_KEY, {key: value for key, value in state.items() if key != pack.id})


# ----------------------------------------------------------------------
# What a pack that is off would have given
# ----------------------------------------------------------------------
def _declared(source: str) -> tuple[list[str], list[str]]:
    """(names, suffixes) the classes of a plugin file declare as literals - read, like the scan, without importing."""
    import ast

    names: list[str] = []
    suffixes: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names, suffixes
    for node in (item for item in tree.body if isinstance(item, ast.ClassDef)):
        for statement in node.body:
            if not (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)):
                continue
            try:
                value = ast.literal_eval(statement.value)
            except (ValueError, SyntaxError):
                continue
            target = statement.targets[0].id
            if target in ("Name", "name") and isinstance(value, str):
                names.append(value)
            elif target == "Suffixes" and isinstance(value, (list, tuple)):
                suffixes.extend(str(item).lower() for item in value)
    return names, suffixes


def pack_that_has(family: str, name: str) -> Pack | None:
    """The usable pack, not enabled now, that holds the plugin *name* of *family* - or, for the family
    "suffix", a reader of files ending in *name*."""
    wanted = name.lower() if family == "suffix" else name
    folder = "importers" if family == "suffix" else family
    for pack in find():
        if pack.error or is_enabled(pack):
            continue
        try:
            with zipfile.ZipFile(pack.path) as archive:
                sources = [archive.read(member).decode("utf-8", "replace") for member in archive.namelist()
                           if member.startswith(f"{folder}/") and member.endswith(".py")]
        except (OSError, zipfile.BadZipFile):
            continue
        for source in sources:
            names, suffixes = _declared(source)
            if wanted in (suffixes if family == "suffix" else names):
                return pack
    return None


def needed_note(family: str, name: str) -> str:
    """One sentence for the user when what they ask for is in a pack that is off; "" when no pack has it."""
    from app.utils.i18n import tr

    pack = pack_that_has(family, name)
    if pack is None:
        return ""
    return tr("This needs the pack “{pack}”. Switch it on in Settings > Packages, then start ChartLibre "
              "again.").format(pack=pack.name)
