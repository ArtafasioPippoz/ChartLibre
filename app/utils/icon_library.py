"""The icons the application ships for pictures in charts: Lucide (ISC) and the flags of the world (MIT).

Each set is one zip in app/data/icon_library (built by dev/tools/make_icon_library.py) with its index, its licence
text and its SVG files. An icon added to a project keeps the set's name, source and licence in __images__, so a
chart that uses it can credit it. No Qt: the Pictures dialog draws the previews.
"""
from __future__ import annotations

import json
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "icon_library"


@dataclass(frozen=True, slots=True)
class IconSet:
    key: str
    title: str
    license: str
    source: str
    version: str
    prefix: str
    #: (name, title, tags) of every icon.
    icons: tuple[tuple[str, str, tuple[str, ...]], ...]

    def credit(self) -> str:
        return f"{self.title} {self.version} ({self.source})"


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def set_keys() -> list[str]:
    return sorted(path.stem for path in DIRECTORY.glob("*.zip"))


@lru_cache(maxsize=8)
def load(key: str) -> IconSet:
    with zipfile.ZipFile(DIRECTORY / f"{key}.zip") as archive:
        index = json.loads(archive.read("index.json"))
    return IconSet(key=key, title=index["title"], license=index["license"], source=index["source"],
                   version=str(index["version"]), prefix=index["prefix"],
                   icons=tuple((icon["name"], icon["title"], tuple(t for t in icon.get("tags", ()) if t))
                               for icon in index["icons"]))


def search(key: str, text: str, limit: int = 300) -> list[tuple[str, str]]:
    """The (name, title) of the icons of set *key* matching every word of *text* (name, title or tag), best first:
    a name that starts with the text, then one that contains it, then a tag. Empty text lists them in order."""
    words = _plain(text).split()
    found: list[tuple[int, str, str]] = []
    for name, title, tags in load(key).icons:
        haystack_name, haystack_tags = _plain(f"{name} {title}"), _plain(" ".join(tags))
        if not all(word in haystack_name or word in haystack_tags for word in words):
            continue
        rank = 0 if words and haystack_name.startswith(words[0]) else 1 if all(w in haystack_name for w in words) else 2
        found.append((rank, name, title))
    found.sort(key=lambda row: (row[0], row[1]))
    return [(name, title) for _rank, name, title in found[:limit]]


def svg(key: str, name: str) -> bytes:
    """The SVG file of icon *name* of set *key*; KeyError when there is none."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise KeyError(name)
    with zipfile.ZipFile(DIRECTORY / f"{key}.zip") as archive:
        return archive.read(f"icons/{name}.svg")


def project_name(key: str, name: str) -> str:
    """The name an icon gets in a project: "lucide-heart", "flag-it"."""
    return load(key).prefix + name
