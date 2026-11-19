"""Draw the small example of every chart type that New plot shows: app/charts/previews/<chart>.png.

    python dev/tools/make_chart_previews.py [--sources dev/packs] [--packs app/packages]

After the pictures, each pack folder (dev/packs/<id>/) gets one of them as its example, preview.png, and its
.clpack is built again: the first chart type the pack holds that has a picture. Preferences > Packages shows it.

Run again after adding a chart type or changing how one looks. The data are the tests' showcase figures.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ["CHARTLIBRE_ALL_PACKS"] = "1"  # the example of a chart in a pack too (app.utils.packs)

import matplotlib

matplotlib.use("Agg")

from matplotlib.figure import Figure

from app.data.sqlite_repo import SqliteRepo
from app.utils import packs
from dev.tools import make_pack
from app.plugin_api.charts.render_figure import render_figure_from_descriptor
from app.widgets.renderer_picker import preview_path
from dev.tests._figure_factory import create_renderer_showcase_db


_CHART_NAME = re.compile(r"^\s+Name(?::\s*str)?\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE)


def pack_previews(sources: Path, target: Path) -> list[str]:
    """Give each pack folder of *sources* (dev/packs/<id>/) its example picture, preview.png, and build its
    .clpack into *target*. The example is the first chart type the pack holds that has a picture."""
    done = []
    for folder in sorted(sources.glob("*/" + packs.MANIFEST)):
        folder = folder.parent
        found = None
        for path in sorted((folder / "charts").glob("*.py")):
            for name in _CHART_NAME.findall(path.read_text(encoding="utf-8", errors="replace")):
                if found is None and preview_path(name).is_file():
                    found = name
        if found is None:
            continue
        shutil.copyfile(preview_path(found), folder / packs.PREVIEW)
        built = make_pack.build(folder, target)
        done.append(f"{built.name}: {found}")
    return done


def main() -> None:
    arguments = argparse.ArgumentParser()
    arguments.add_argument("--sources", type=Path, default=ROOT / "dev" / "packs", help="the pack folders")
    arguments.add_argument("--packs", type=Path, default=packs.BUILTIN_DIR, help="where the .clpack files go")
    given = arguments.parse_args()
    with tempfile.TemporaryDirectory() as workdir:
        database = Path(workdir) / "previews.dhub"
        figure_ids = create_renderer_showcase_db(database, n_points=400)
        repo = SqliteRepo(db_path=database)
        for chart_type, figure_id in figure_ids.items():
            descriptor = repo.load_figure_descriptor(figure_id=figure_id)
            figure = Figure(figsize=(6.4, 4.0))
            render_figure_from_descriptor(figure=figure, descriptor=descriptor, repo=repo)
            target = preview_path(chart_type)
            target.parent.mkdir(parents=True, exist_ok=True)
            figure.savefig(target, dpi=70)
        repo.close()
    for line in pack_previews(given.sources, given.packs):
        print("example in", line)


if __name__ == "__main__":
    main()
