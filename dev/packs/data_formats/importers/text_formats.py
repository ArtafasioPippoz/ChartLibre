"""Program text formats read without any package: GPX tracks and GraphPad .pzfx (todo I-01).

Moved from app/importers into the data_formats pack; JCAMP-DX and LabVIEW .lvm are in the instruments pack.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

from app.plugin_api.importers.base import (
    ALL_DATASETS,
    FileImporter,
    ImportedData,
    combine,
)
from app.utils.coercion import to_numbers

# ----------------------------------------------------------------------
# GPX
# ----------------------------------------------------------------------
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class GpxImporter(FileImporter):
    Name = "GPS track (GPX)"
    Description = "A GPX file's track, route and waypoints: latitude, longitude, elevation, time."
    Suffixes = [".gpx"]
    Category = "Other"
    Order = 90

    def read(self, path: str, dataset: str | None = None) -> ImportedData:
        root = ET.parse(path).getroot()
        rows = []
        for element in root.iter():
            kind = _local(element.tag)
            if kind not in ("trkpt", "rtept", "wpt"):
                continue
            row = {"Kind": {"trkpt": "track", "rtept": "route", "wpt": "waypoint"}[kind],
                   "Latitude": float(element.get("lat", "nan")), "Longitude": float(element.get("lon", "nan"))}
            for child in element:
                name = _local(child.tag)
                if name == "ele":
                    row["Elevation (m)"] = float(child.text or "nan")
                elif name == "time":
                    row["Time"] = child.text
                elif name == "name":
                    row["Name"] = child.text
            rows.append(row)
        if not rows:
            raise ValueError("No track, route or waypoint: is this a GPX file?")
        return ImportedData(frame=pd.DataFrame(rows), units={"Elevation (m)": "m"})


# ----------------------------------------------------------------------
# GraphPad Prism .pzfx
# ----------------------------------------------------------------------
def _pzfx_tables(path: str) -> dict[str, pd.DataFrame]:
    root = ET.parse(path).getroot()
    tables: dict[str, pd.DataFrame] = {}
    for table in root.iter():
        if _local(table.tag) not in ("Table", "HugeTable"):
            continue
        title = next((child.text for child in table if _local(child.tag) == "Title"), None) or f"Table {len(tables) + 1}"
        columns: dict[str, list[str]] = {}
        for column in table:
            kind = _local(column.tag)
            if kind not in ("XColumn", "YColumn", "RowTitlesColumn"):
                continue
            name = next((child.text for child in column if _local(child.tag) == "Title"), None) \
                or {"XColumn": "X", "RowTitlesColumn": "Row"}.get(kind, f"Y{len(columns)}")
            subcolumns = [sub for sub in column if _local(sub.tag) == "Subcolumn"]
            for k, sub in enumerate(subcolumns):
                label = name if len(subcolumns) == 1 else f"{name} {k + 1}"
                columns[label] = [(d.text or "") for d in sub if _local(d.tag) == "d"]
        if columns:
            length = max(len(values) for values in columns.values())
            frame = pd.DataFrame({name: values + [""] * (length - len(values)) for name, values in columns.items()})
            tables[title] = frame.apply(_numbers_or_text)
    return tables


def _numbers_or_text(column: pd.Series) -> pd.Series:
    """A column as numbers when every filled cell is one; else as text, its empty cells missing."""
    filled = column.replace("", np.nan)
    if to_numbers(filled).notna().sum() == filled.notna().sum():
        return to_numbers(column)
    return filled


class PrismImporter(FileImporter):
    Name = "GraphPad Prism (.pzfx)"
    Description = "A Prism XML project: each data table a dataset, replicates as numbered columns."
    Suffixes = [".pzfx"]
    Category = "Statistics software"
    Order = 15

    def datasets(self, path: str) -> list[str]:
        tables = _pzfx_tables(path)
        return list(tables) if len(tables) > 1 else []

    def read(self, path: str, dataset: str | None = None) -> ImportedData:
        tables = _pzfx_tables(path)
        if not tables:
            raise ValueError("No data table: is this a Prism .pzfx file?")
        if dataset == ALL_DATASETS:
            return ImportedData(frame=combine(tables))
        return ImportedData(frame=tables.get(dataset or "", next(iter(tables.values()))))
