"""What is in a pack that is switched off is asked for by name: a chart says so, a file is not read as text,
and the libraries a pack lacks are installed at start."""
from __future__ import annotations

import sys

import pandas as pd
import pytest
from matplotlib.figure import Figure

from app.utils import data_sources, packs
from test_packs import folders, make_pack  # noqa: F401 - the fixture

CHART = 'class Wafer(BaseAxisRenderer):\n    Name: str = "Wafer Chart"\n'
READER = 'class Nc(FileImporter):\n    Name = "NetCDF"\n    Suffixes = [".ncx", ".NCY"]\n'


def test_the_pack_that_is_off_is_found_by_chart_name_and_by_suffix_and_not_once_it_is_on(folders):
    make_pack(packs.BUILTIN_DIR, "semi", manifest={"name": "Semiconductors"},
              files={"charts/wafer.py": CHART, "importers/nc.py": READER})
    assert packs.pack_that_has("charts", "Wafer Chart").id == "semi"
    assert packs.pack_that_has("suffix", ".NCX").id == "semi" and packs.pack_that_has("suffix", ".ncy").id == "semi"
    assert packs.pack_that_has("charts", "Scatter Plot") is None
    assert "“Semiconductors”" in packs.needed_note("charts", "Wafer Chart")
    packs.set_switched_on("semi", True)
    assert packs.pack_that_has("charts", "Wafer Chart") is None and packs.needed_note("suffix", ".ncx") == ""


def test_a_chart_of_a_pack_that_is_off_says_which_pack_and_the_other_axes_are_drawn(folders, repo):
    make_pack(packs.BUILTIN_DIR, "semi", manifest={"name": "Semiconductors"}, files={"charts/wafer.py": CHART})
    repo.import_dataframe(pd.DataFrame({"x": [1.0, 2.0], "y": [1.0, 3.0]}), table_name="src", normalize_columns=False)
    figure_id = int(repo.create_figure_descriptor(name="f"))
    for index, chart_type in enumerate(["Wafer Chart", "Scatter Plot", "No Such Chart"]):
        axis_id = int(repo.create_axis_descriptor(figure_id=figure_id, axis_index=index, chart_type=chart_type,
                                                  title="t", x_label="x", y_label="y", options={}))
        repo.create_series_descriptor(axis_id=axis_id, series_index=0, name="s", sql_query="SELECT x, y FROM src",
                                      roles={"x": "x", "y": "y"}, style={})
    from app.plugin_api.charts.render_figure import render_figure_from_descriptor

    figure = Figure()
    render_figure_from_descriptor(figure=figure, descriptor=repo.load_figure_descriptor(figure_id), repo=repo)
    said = [" ".join(text.get_text() for text in axes.texts) for axes in figure.axes]
    assert "needs the pack “Semiconductors”" in said[0] and "Wafer Chart" in said[0]
    assert figure.axes[1].lines or figure.axes[1].collections  # the scatter plot beside it is drawn
    assert "“No Such Chart” is not installed" in said[2]


def test_a_file_whose_reader_is_in_a_pack_that_is_off_is_not_read_as_text(folders, tmp_path):
    make_pack(packs.BUILTIN_DIR, "formats", manifest={"name": "Data formats"}, files={"importers/nc.py": READER})
    path = tmp_path / "run.ncx"
    path.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError, match="needs the pack “Data formats”"):
        data_sources.read_any_file(str(path))
    other = tmp_path / "run.unknown"
    other.write_text("a,b\n1,2\n")
    assert list(data_sources.read_any_file(str(other)).columns) == ["a", "b"]  # as before: tried as text


@pytest.mark.parametrize(("code", "why"), [(0, ""), (3, "it failed")])
def test_the_libraries_the_enabled_packs_lack_are_installed_by_pip_and_a_failure_is_said(folders, monkeypatch, code, why):
    make_pack(packs.BUILTIN_DIR, manifest={"default": True, "packages": ["pytest", "no-such-library-xyz"]})
    asked: list[list[str]] = []

    def fake_pip(names):
        asked.append(list(names))
        return [sys.executable, "-c", f"import sys; print('it failed'); sys.exit({code})"]

    monkeypatch.setattr(packs, "pip_command", fake_pip)
    assert packs.install_missing() == (["no-such-library-xyz"], why)
    assert asked == [["no-such-library-xyz"]]


def test_nothing_is_installed_for_a_pack_that_is_off(folders, monkeypatch):
    make_pack(packs.BUILTIN_DIR, manifest={"default": False, "packages": ["no-such-library-xyz"]})
    monkeypatch.setattr(packs, "pip_command", lambda names: pytest.fail("pip must not run"))
    assert packs.install_missing() == ([], "")


def test_the_developer_tools_load_every_readable_pack_whatever_the_switches(folders, monkeypatch):
    make_pack(packs.BUILTIN_DIR, "off", manifest={"default": False})
    make_pack(packs.BUILTIN_DIR, "broken", manifest={"needs_app": "99.0"})
    by_id = {pack.id: pack for pack in packs.find()}
    assert not packs.is_enabled(by_id["off"])
    monkeypatch.setenv(packs.ALL_PACKS_ENV, "1")
    assert packs.is_enabled(by_id["off"]) and not packs.is_enabled(by_id["broken"])
