"""NetCDF files (climate, ocean, atmosphere and many instruments' data), read through netCDF4.

A NetCDF file holds variables over dimensions. The variables that share one set of dimensions make one
table - a dataset named by its dimensions ("time", "time, lat, lon") - in long form: a column per dimension
(its coordinate variable's values, or the index when it has none), then a column per variable. Fill values
are empty cells, scale and offset applied (netCDF4 does it). Global attributes are the metadata, each
variable's "units" its unit. A table past MAX_ROWS rows is refused with a word on how to cut it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.plugin_api.importers.base import ALL_DATASETS, FileImporter, ImportedData, combine

#: Long form multiplies the dimensions: more rows than this are not a table to read whole.
MAX_ROWS = 5_000_000


def _key(dimensions: tuple[str, ...]) -> str:
    return ", ".join(dimensions) if dimensions else "scalars"


class NetcdfImporter(FileImporter):
    Name = "NetCDF"
    Description = "A NetCDF file (.nc): the variables of each set of dimensions as one table."
    Suffixes = [".nc", ".nc4", ".cdf", ".netcdf"]
    Category = "Columnar and scientific"
    Packages = ["netCDF4"]
    Order = 25

    @staticmethod
    def _open(path: str):
        import netCDF4

        return netCDF4.Dataset(path, "r")

    @staticmethod
    def _tables(data) -> dict[str, list[str]]:
        """dataset name -> its variables; a dimension's own coordinate variable is a column, not a table."""
        tables: dict[str, list[str]] = {}
        for name, variable in data.variables.items():
            dimensions = tuple(variable.dimensions)
            if dimensions == (name,) and any(
                    other != name and name in data.variables[other].dimensions for other in data.variables):
                continue  # a coordinate: shown beside the variables over it
            tables.setdefault(_key(dimensions), []).append(name)
        return tables

    def datasets(self, path: str) -> list[str]:
        self.require()
        with self._open(path) as data:
            tables = self._tables(data)
        return list(tables) if len(tables) > 1 else []

    def read(self, path: str, dataset: str | None = None) -> ImportedData:
        self.require()
        with self._open(path) as data:
            tables = self._tables(data)
            if not tables:
                raise ValueError("The file holds no variable.")
            metadata = {str(key): _plain(data.getncattr(key)) for key in data.ncattrs()}
            if dataset == ALL_DATASETS:
                frames, units = {}, {}
                for name, variables in tables.items():
                    frames[name], table_units = self._table(data, variables)
                    units.update(table_units)
                return ImportedData(frame=combine(frames), metadata=metadata, units=units)
            name = dataset if dataset in tables else next(iter(tables))
            frame, units = self._table(data, tables[name])
            notes = [f"Dimensions: {name}."] if len(tables) > 1 else []
            return ImportedData(frame=frame, metadata=metadata, units=units, notes=notes)

    @staticmethod
    def _table(data, variables: list[str]) -> tuple[pd.DataFrame, dict[str, str]]:
        dimensions = tuple(data.variables[variables[0]].dimensions)
        sizes = [len(data.dimensions[dimension]) for dimension in dimensions]
        rows = int(np.prod(sizes)) if sizes else 1
        if rows > MAX_ROWS:
            raise ValueError(f"The variables over {_key(dimensions)} make {rows:,} rows, more than {MAX_ROWS:,}. "
                             "Cut the file first (for example: ncks -d time,0,99 in.nc out.nc).")
        columns: dict[str, np.ndarray] = {}
        units: dict[str, str] = {}
        if dimensions:
            axes = []
            for dimension, size in zip(dimensions, sizes):
                coordinate = data.variables.get(dimension)
                if coordinate is not None and tuple(coordinate.dimensions) == (dimension,):
                    axes.append(_values(coordinate))
                    if getattr(coordinate, "units", ""):
                        units[dimension] = str(coordinate.units)
                else:
                    axes.append(np.arange(size))
            grids = np.meshgrid(*axes, indexing="ij")
            for dimension, grid in zip(dimensions, grids):
                columns[dimension] = grid.reshape(-1)
        for name in variables:
            if name in columns:
                continue
            variable = data.variables[name]
            columns[name] = _values(variable).reshape(-1)
            if getattr(variable, "units", ""):
                units[name] = str(variable.units)
        return pd.DataFrame(columns), units


def _values(variable) -> np.ndarray:
    """A variable's values, fill values as NaN (text and dates as they come)."""
    values = variable[:]
    if np.ma.isMaskedArray(values):
        values = values.astype(float).filled(np.nan) if values.dtype.kind in "biuf" else values.filled(None)
    return np.asarray(values)


def _plain(value):
    if isinstance(value, np.ndarray):
        return value.tolist() if value.size > 1 else value.item()
    return value.item() if isinstance(value, np.generic) else value
