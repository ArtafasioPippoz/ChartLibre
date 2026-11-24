"""The analyses' modules for the tests that go through all of them: the application's own and the shipped
packs' (their source in dev/packs/<pack>/data_operations), by module name."""
from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
BUILTIN = ROOT / "app" / "data_operations"


def _dotted(path: Path) -> str:
    if path.is_dir():  # an analysis that is a package of its own (fit_dialog)
        return f"app.data_operations.{path.name}"
    if path.parent == BUILTIN:
        return f"app.data_operations.{path.stem}"
    return ".".join(path.relative_to(ROOT).with_suffix("").parts)  # dev.packs.<pack>.data_operations.<stem>


def operation_files(*, packages: bool = False) -> list[Path]:
    """Every analysis' *_dialog.py: the application's, then each shipped pack's source, by name; with
    *packages*, the application's analyses that are packages of their own too (fit_dialog/)."""
    files = list(BUILTIN.glob("*_dialog.py")) + list((ROOT / "dev" / "packs").glob("*/data_operations/*_dialog.py"))
    if packages:
        files += [path for path in BUILTIN.glob("*_dialog") if (path / "__init__.py").is_file()]
    return sorted(files, key=lambda path: path.stem)


def operation_module(name: str) -> ModuleType:
    """The module of the analysis *name* ("cluster_dialog"), wherever it is."""
    for path in operation_files(packages=True):
        if path.stem == name:
            return importlib.import_module(_dotted(path))
    raise ModuleNotFoundError(f"No analysis module {name!r} in app/data_operations or dev/packs.")


def operation_modules(*, packages: bool = False) -> list[ModuleType]:
    return [importlib.import_module(_dotted(path)) for path in operation_files(packages=packages)]


def pack_operation_modules() -> list[ModuleType]:
    """The shipped packs' analyses alone, from their source."""
    return [importlib.import_module(_dotted(path))
            for path in sorted((ROOT / "dev" / "packs").glob("*/data_operations/*.py"))]
