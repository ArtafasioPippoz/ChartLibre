"""Extension packs: a .clpack file adds a set of plugins, switched on or off in Preferences.

A pack is a zip renamed .clpack. Inside, a manifest (pack.json) and one folder per plugin family, named as
under app/ - charts, data_operations, importers, functions, ai_providers - plus lib/<pack id>/ for the pack's
own helper modules and locales/ for its translations. The packs that come with the application are in
app/packages/ (their source in dev/packs/, built by dev/tools/make_pack.py), those the user adds in
user/packages/.

An enabled pack is installed: its plugin files are copied beside the application's own, each family's in
its folder - app/charts/<pack id>/, app/data_operations/<pack id>/ and so on - where the families' scan
finds them like any other plugin; the rest of it (lib, locales) goes to app/packages/installed/<pack id>/.
A pack switched off is taken out again. sync() does both, before the families are scanned, so a switch in
Preferences applies at the next start. Every folder a pack is installed in carries a marker file: nothing
without it is ever replaced or removed.

A pack is Python run with the user's rights. One that came with the application is trusted; one the user
added runs only once its fingerprint was accepted on this computer (trust), like a pickled model.
A pack that cannot be read or installed is listed or logged with its error and left out: it never stops
the application.

See dev/plans/extension_packs_plan.txt.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from app import APP_VERSION
from app.utils.logger import applogger
from app.utils.config import USER_CONTENT_DIR, get_value, set_value

SUFFIX = ".clpack"
MANIFEST = "pack.json"
#: The folders of a pack that hold plugins, each named as its family's folder under app/.
FAMILIES = ("charts", "data_operations", "importers", "functions", "ai_providers")
#: The application's folder: an installed pack's plugins go in APP_DIR/<family>/<pack id>/.
APP_DIR: Path = Path(__file__).resolve().parent.parent
BUILTIN_DIR: Path = APP_DIR / "packages"
#: In every folder a pack was installed in: which pack, and of which file (its fingerprint).
MARKER = "installed_pack.json"
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


#: Set to 1 by the developer's tools (ChartLibre Developer, the tests, the preview maker): every readable pack is
#: loaded whatever the user's switches say, so a test or a picture never depends on one person's Preferences.
ALL_PACKS_ENV = "CHARTLIBRE_ALL_PACKS"


def is_enabled(pack: Pack) -> bool:
    """Its plugins are loaded: readable, switched on and allowed to run."""
    if os.environ.get(ALL_PACKS_ENV) == "1":
        return not pack.error
    return not pack.error and is_switched_on(pack) and is_trusted(pack)


# ----------------------------------------------------------------------
# Installing: the plugin files beside the application's own
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


def _installed_dir() -> Path:
    """Where what is not a plugin file of the installed packs is kept: their lib/ and locales/."""
    return BUILTIN_DIR / "installed"


def _marker(folder: Path) -> dict:
    try:
        value = json.loads((folder / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def installed() -> dict[str, str]:
    """pack id -> fingerprint of the file it was installed from, of the packs installed now."""
    found: dict[str, str] = {}
    folders = [item for item in _installed_dir().iterdir()] if _installed_dir().is_dir() else []
    for family in FAMILIES:
        if (APP_DIR / family).is_dir():
            folders.extend(APP_DIR.joinpath(family).iterdir())
    for folder in folders:
        marker = _marker(folder) if folder.is_dir() else {}
        if marker.get("id") == folder.name:
            found.setdefault(folder.name, str(marker.get("fingerprint", "")))
    return found


def family_folder(family: str, pack_id: str) -> Path:
    """Where the plugins of *family* of the pack *pack_id* are installed: beside the application's own."""
    return APP_DIR / family / pack_id


def uninstall(pack_id: str) -> None:
    """Take an installed pack out: its folder in each family's and its own. Only folders with the marker."""
    for folder in (*(family_folder(family, pack_id) for family in FAMILIES), _installed_dir() / pack_id):
        if _marker(folder).get("id") == pack_id:
            shutil.rmtree(folder, ignore_errors=True)


def install(pack: Pack) -> None:
    """Copy *pack*'s files where the application reads them; raises PackError and leaves nothing half made."""
    import os

    stage = _installed_dir() / f"{pack.id}.stage{os.getpid()}"
    marker = json.dumps({"id": pack.id, "fingerprint": pack.fingerprint, "version": pack.version})
    try:
        with zipfile.ZipFile(pack.path) as archive:
            members = _checked_members(archive)
            shutil.rmtree(stage, ignore_errors=True)
            archive.extractall(stage, members=members)
        moves: list[tuple[Path, Path]] = []
        for family in FAMILIES:
            if (stage / family).is_dir():
                moves.append((stage / family, family_folder(family, pack.id)))
        rest = stage / ".rest"
        rest.mkdir()
        for item in list(stage.iterdir()):
            if item.name not in (*FAMILIES, ".rest"):
                item.rename(rest / item.name)
        moves.append((rest, _installed_dir() / pack.id))
        for _source, target in moves:
            if target.exists() and _marker(target).get("id") != pack.id:
                # A folder of the application's own with the pack's name (app/data_operations/fit_dialog).
                raise PackError(f"The folder {target} is already there and is not this pack's.")
        for source, target in moves:
            if _marker(target).get("fingerprint") == pack.fingerprint:
                continue  # another process of the application installed it meanwhile
            (source / MARKER).write_text(marker, encoding="utf-8")
            (source / ".gitignore").write_text("*\n", encoding="utf-8")  # installed copies are not source
            shutil.rmtree(target, ignore_errors=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
    except (OSError, zipfile.BadZipFile) as exc:
        uninstall(pack.id)
        failure = PackError(f"It cannot be installed: {exc}")
        applogger.warning("%s", failure, exc_info=exc)
        raise failure from exc
    except PackError:
        uninstall(pack.id)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


class _Lock:
    """One process at a time changes the installed packs: two copies of the application starting together
    (or the test workers) would otherwise take out what the other is installing."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._file = None

    def __enter__(self) -> "_Lock":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self._path, "a+b")  # noqa: SIM115 - held until __exit__
        try:
            import fcntl

            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX)
        except ImportError:  # Windows
            import msvcrt

            self._file.seek(0)
            while True:
                try:
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:  # LK_LOCK gives up after ten seconds: wait again
                    continue
        return self

    def __exit__(self, *_exc) -> None:
        try:
            try:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            except ImportError:
                import msvcrt

                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self._file.close()


def sync() -> None:
    """Make what is installed what is enabled: install, replace (a changed file) and take out as needed.

    Called before the plugin families are scanned (PluginFamily.discover), so it costs a start nothing
    when nothing changed: the manifests are read and the fingerprints compared. One process at a time.
    """
    with _Lock(_installed_dir() / ".lock"):
        _sync()


def _sync() -> None:
    wanted = {pack.id: pack for pack in find() if is_enabled(pack)}
    have = installed()
    for pack_id, fingerprint_ in have.items():
        if pack_id not in wanted or wanted[pack_id].fingerprint != fingerprint_:
            uninstall(pack_id)
    for pack_id, pack in wanted.items():
        if have.get(pack_id) != pack.fingerprint:
            try:
                install(pack)
            except PackError as exc:
                applogger.error("The pack %s is left out. %s", pack.path.name, exc)
                continue
        for family in FAMILIES:
            _remove_sync_copies(family_folder(family, pack_id), pack_id)
        lib = _installed_dir() / pack_id / "lib"
        if lib.is_dir() and str(lib) not in sys.path:
            sys.path.append(str(lib))  # the pack's own modules: "from <pack id> import ..."


#: A copy a file-syncing service (iCloud Drive, OneDrive, Dropbox) makes when a file is replaced under it:
#: "peaks_dialog 2.py" beside "peaks_dialog.py".
_SYNC_COPY = re.compile(r"^(?P<stem>.+) \d+(?P<suffix>\.py)$")


def _remove_sync_copies(folder: Path, pack_id: str) -> None:
    """Take out of an installed pack's folder the copies a syncing service left beside its files.

    The project folder may be in iCloud Drive (the Desktop often is): installing a pack again replaces its
    files, and the service may keep the old one as "<name> 2.py" - a second plugin of the same name, run
    with the imports of the old version. Only a folder the pack owns (its marker) and only a copy whose
    original is there.
    """
    if not folder.is_dir() or _marker(folder).get("id") != pack_id:
        return
    for path in folder.rglob("* *.py"):
        match = _SYNC_COPY.match(path.name)
        if match and (path.parent / f"{match['stem']}{match['suffix']}").is_file():
            try:
                path.unlink()
            except OSError as exc:
                applogger.warning("A synced copy in the pack %s is left: %s (%s)", pack_id, path, exc)


def pack_of(path: Path) -> str:
    """The id of the installed pack the plugin file *path* belongs to; "" for the application's own."""
    for family in FAMILIES:
        try:
            first = path.relative_to(APP_DIR / family).parts[0]
        except (ValueError, IndexError):
            continue
        return first if _marker(APP_DIR / family / first).get("id") == first else ""
    return ""


def catalogues(language: str) -> list[Path]:
    """The installed packs' own translations into *language*: locales/<language>/pack.po of each."""
    return [path for pack_id in installed()
            if (path := _installed_dir() / pack_id / "locales" / language / "pack.po").is_file()]


# ----------------------------------------------------------------------
# What Preferences does with the files
# ----------------------------------------------------------------------
def _plugin_files(pack: Pack) -> dict[str, str]:
    """posix path inside the pack -> source, of every plugin file of *pack*, read without unpacking it."""
    def is_plugin(name: str) -> bool:
        parts = PurePosixPath(name).parts
        return (len(parts) >= 2 and parts[0] in FAMILIES and name.endswith(".py")
                and not parts[-1].startswith("_") and "__pycache__" not in parts)

    try:
        with zipfile.ZipFile(pack.path) as archive:
            return {name: archive.read(name).decode("utf-8", "replace")
                    for name in archive.namelist() if is_plugin(name)}
    except (OSError, zipfile.BadZipFile):
        return {}


def contents(pack: Pack) -> dict[str, int]:
    """family -> how many plugin files *pack* holds for it, read from the archive without unpacking."""
    counts: dict[str, int] = {}
    for name in _plugin_files(pack):
        family = PurePosixPath(name).parts[0]
        counts[family] = counts.get(family, 0) + 1
    return counts


#: The pack's example picture, at the root of the file like pack.json (the way a chart type has its preview).
PREVIEW = "preview.png"
MAX_PREVIEW_BYTES = 2 * 1024 * 1024


def preview_bytes(pack: Pack) -> bytes | None:
    """The bytes of the pack's example picture, read without unpacking; None when it has none."""
    try:
        with zipfile.ZipFile(pack.path) as archive:
            info = archive.getinfo(PREVIEW)
            if info.file_size > MAX_PREVIEW_BYTES:
                return None
            return archive.read(info)
    except (KeyError, OSError, zipfile.BadZipFile):
        return None


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


def pip_command(names: list[str]) -> list[str]:
    """The command that installs *names* into this very Python (the application's own)."""
    return [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *names]


def install_missing(on_step=None) -> tuple[list[str], str]:
    """Install the libraries the enabled packs lack, in one pip run. Returns (names tried, pip's last line when it failed).

    Run at start, before the plugin families are scanned: this is the only place the libraries come from.
    *on_step* is called now and then while pip runs, so a window can stay alive.
    """
    import importlib
    import subprocess

    names: list[str] = []
    for pack in find():
        if is_enabled(pack):
            names += [name for name in missing_packages(pack) if name not in names]
    if not names:
        return [], ""
    try:
        process = subprocess.Popen(pip_command(names), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        while True:
            try:
                output, _ = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if on_step is not None:
                    on_step()
    except OSError as exc:
        return names, str(exc)
    importlib.invalidate_caches()
    if process.returncode == 0:
        return names, ""
    lines = (output or "").strip().splitlines()
    applogger.error("Libraries for packs not installed: %s", output)
    return names, lines[-1] if lines else "pip failed"


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
    if not any(other.id == pack.id for other in find()):
        uninstall(pack.id)
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
            # Name = "..." and Name: str = "...", as the families' scan reads them.
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                name_node = statement.targets[0]
            elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
                name_node = statement.target
            else:
                continue
            if not isinstance(name_node, ast.Name):
                continue
            try:
                value = ast.literal_eval(statement.value)
            except (ValueError, SyntaxError):
                continue
            target = name_node.id
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
        for name, source in _plugin_files(pack).items():
            if not name.startswith(f"{folder}/"):
                continue
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
