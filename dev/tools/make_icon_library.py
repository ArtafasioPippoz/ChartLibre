"""Build the icon library the application ships (app/data/icon_library/*.zip) from the sets' npm packages.

    .python/bin/python3 dev/tools/make_icon_library.py <lucide-static package dir> <flag-icons package dir>

The packages are downloaded by hand (registry.npmjs.org: lucide-static 1.77.0, ISC; flag-icons 7.6.0, MIT) and
unpacked in a folder of their own, never in the repository. Each zip holds index.json (the set's name, licence,
source, version and its icons: name, title, tags), LICENSE and icons/<name>.svg. Flags are the 4x3 ones.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "app" / "data" / "icon_library"


def _write(key: str, meta: dict, icons: list[dict], files: dict[str, bytes], license_text: bytes) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT / f"{key}.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("index.json", json.dumps({**meta, "icons": icons}, ensure_ascii=False, separators=(",", ":")))
        archive.writestr("LICENSE", license_text)
        for name, data in sorted(files.items()):
            archive.writestr(f"icons/{name}.svg", data)
    print(f"{key}: {len(icons)} icons, {(OUT / f'{key}.zip').stat().st_size // 1024} KB")


def lucide(package: Path) -> None:
    tags = json.loads((package / "tags.json").read_text(encoding="utf-8"))
    version = json.loads((package / "package.json").read_text(encoding="utf-8"))["version"]
    files, icons = {}, []
    for path in sorted((package / "icons").glob("*.svg")):
        files[path.stem] = path.read_bytes()
        icons.append({"name": path.stem, "title": path.stem.replace("-", " "), "tags": tags.get(path.stem, [])})
    _write("lucide", {"title": "Lucide", "license": "ISC", "source": "https://lucide.dev", "version": version,
                      "prefix": "lucide-", "kind": "icons"}, icons, files, (package / "LICENSE").read_bytes())


def flags(package: Path) -> None:
    countries = json.loads((package / "country.json").read_text(encoding="utf-8"))
    version = json.loads((package / "package.json").read_text(encoding="utf-8"))["version"]
    files, icons = {}, []
    for country in countries:
        path = package / country["flag_4x3"]
        if not path.is_file():
            continue
        files[country["code"]] = path.read_bytes()
        icons.append({"name": country["code"], "title": country["name"],
                      "tags": [country.get("capital", ""), country.get("continent", ""), country["code"]]})
    _write("flags", {"title": "Flags of the world", "license": "MIT",
                     "source": "https://github.com/lipis/flag-icons", "version": version, "prefix": "flag-",
                     "kind": "flags"}, icons, files, (package / "LICENSE").read_bytes())


if __name__ == "__main__":
    lucide(Path(sys.argv[1]))
    flags(Path(sys.argv[2]))
