"""The readers the instruments and data_formats packs add: NI TDMS and NetCDF, on files written here,
read the way the Import dialog reads them (the packs are on by default)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.plugin_api.importers.base import ALL_DATASETS
from app.scanners import importer_scanner
from app.utils import data_sources


def _read(path: Path, dataset=None):
    return data_sources.read_imported(str(path), dataset)


def test_the_packs_readers_are_found_and_named_by_their_pack() -> None:
    packs_of = {entry["value"]: entry.get("pack") for entry in importer_scanner.importers}
    assert packs_of["NI TDMS"] == packs_of["Touchstone S-parameters"] == packs_of["JCAMP-DX spectrum"] == "instruments"
    assert packs_of["NetCDF"] == packs_of["Parquet"] == "data_formats"
    assert packs_of["GPS track (GPX)"] == packs_of["MATLAB"] == "data_formats"
    assert packs_of["LibreOffice / OpenDocument spreadsheet"] is None


def test_tdms_groups_are_datasets_with_a_time_column_and_units(tmp_path: Path) -> None:
    pytest.importorskip("nptdms")
    from nptdms import ChannelObject, GroupObject, RootObject, TdmsWriter

    path = tmp_path / "run.tdms"
    with TdmsWriter(str(path)) as writer:
        writer.write_segment([
            RootObject(properties={"operator": "Ada"}),
            GroupObject("Scope", properties={"rate": 1000.0}),
            ChannelObject("Scope", "V1", np.array([0.0, 1.0, 2.0]),
                          properties={"wf_increment": 0.5, "wf_start_offset": 0.0, "unit_string": "V"}),
            ChannelObject("Scope", "V2", np.array([5.0, 6.0])),
            GroupObject("Temperature"),
            ChannelObject("Temperature", "T", np.array([20.0, 21.0]), properties={"unit_string": "degC"}),
        ])
    assert data_sources.is_importable(str(path))
    assert importer_scanner.load_importer(importer_scanner.importer_for(path)).datasets(str(path)) == \
        ["Scope", "Temperature"]
    scope = _read(path)
    assert list(scope.frame.columns) == ["Time", "V1", "V2"]
    assert scope.frame["Time"].tolist() == [0.0, 0.5, 1.0] and scope.frame["V2"].isna().tolist() == [False] * 2 + [True]
    assert scope.units == {"Time": "s", "V1": "V"} and scope.metadata["File operator"] == "Ada"
    assert "shorter ones end in empty cells" in scope.notes[0]
    both = _read(path, ALL_DATASETS).frame
    assert set(both["Dataset"]) == {"Scope", "Temperature"} and len(both) == 5


def test_netcdf_variables_by_their_dimensions_in_long_form(tmp_path: Path) -> None:
    netCDF4 = pytest.importorskip("netCDF4")
    path = tmp_path / "field.nc"
    with netCDF4.Dataset(str(path), "w") as data:
        data.title = "A field"
        data.createDimension("time", 2)
        data.createDimension("lat", 3)
        time = data.createVariable("time", "f8", ("time",))
        time[:] = [0.0, 1.0]
        time.units = "days since 2026-01-01"
        lat = data.createVariable("lat", "f8", ("lat",))
        lat[:] = [10.0, 20.0, 30.0]
        level = data.createVariable("level", "f8", ("time",))
        level[:] = [1.5, 2.5]
        temperature = data.createVariable("temperature", "f4", ("time", "lat"), fill_value=-999.0)
        temperature[:] = np.ma.masked_array([[1, 2, 3], [4, 5, 6]], mask=[[0, 0, 0], [0, 1, 0]])
        temperature.units = "K"
    reader = importer_scanner.load_importer(importer_scanner.importer_for(path))
    assert reader.datasets(str(path)) == ["time", "time, lat"]
    grid = _read(path, "time, lat")
    assert list(grid.frame.columns) == ["time", "lat", "temperature"] and len(grid.frame) == 6
    assert grid.frame["lat"].tolist() == [10.0, 20.0, 30.0] * 2
    assert np.isnan(grid.frame["temperature"].iloc[4]) and grid.frame["temperature"].iloc[5] == 6.0
    assert grid.units == {"time": "days since 2026-01-01", "temperature": "K"}
    assert grid.metadata["title"] == "A field"
    series = _read(path).frame
    assert list(series.columns) == ["time", "level"] and series["level"].tolist() == [1.5, 2.5]


def test_a_netcdf_too_large_for_one_table_says_how_to_cut_it(tmp_path: Path, monkeypatch) -> None:
    netCDF4 = pytest.importorskip("netCDF4")
    path = tmp_path / "big.nc"
    with netCDF4.Dataset(str(path), "w") as data:
        data.createDimension("x", 50)
        data.createDimension("y", 50)
        data.createVariable("v", "f4", ("x", "y"))[:] = np.zeros((50, 50))
    module = __import__(importer_scanner.load_importer(importer_scanner.importer_for(path)).__module__,
                        fromlist=["MAX_ROWS"])
    monkeypatch.setattr(module, "MAX_ROWS", 1000)
    with pytest.raises(ValueError, match="2,500 rows.*ncks"):
        _read(path)
