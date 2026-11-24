"""Spreadsheet formats beyond Excel's own: LibreOffice, Excel binary (todo I-01). Parquet and Feather are in the data_formats pack."""
from __future__ import annotations

import pandas as pd

from app.plugin_api.importers.base import (
    ALL_DATASETS,
    FileImporter,
    ImportedData,
    combine,
)


def _workbook_datasets(path: str, engine: str) -> list[str]:
    names = [str(name) for name in pd.ExcelFile(path, engine=engine).sheet_names]
    return names if len(names) > 1 else []


def _workbook_read(path: str, engine: str, dataset: str | None) -> ImportedData:
    """A workbook read through pandas with *engine*: its sheets are its datasets."""
    book = pd.ExcelFile(path, engine=engine)
    if dataset == ALL_DATASETS:
        return ImportedData(frame=combine({str(name): book.parse(name) for name in book.sheet_names}))
    return ImportedData(frame=book.parse(dataset or 0))


class OdsImporter(FileImporter):
    Name = "LibreOffice / OpenDocument spreadsheet"
    Description = "An .ods workbook: each sheet a dataset."
    Suffixes = [".ods"]
    Category = "Spreadsheets and text"
    Packages = ["odfpy"]
    Order = 5

    def datasets(self, path: str) -> list[str]:
        self.require()
        return _workbook_datasets(path, "odf")

    def read(self, path: str, dataset: str | None = None) -> ImportedData:
        self.require()
        return _workbook_read(path, "odf", dataset)


class XlsbImporter(FileImporter):
    Name = "Excel binary workbook"
    Description = "An .xlsb workbook: each sheet a dataset."
    Suffixes = [".xlsb"]
    Category = "Spreadsheets and text"
    Packages = ["pyxlsb"]
    Order = 6

    def datasets(self, path: str) -> list[str]:
        self.require()
        return _workbook_datasets(path, "pyxlsb")

    def read(self, path: str, dataset: str | None = None) -> ImportedData:
        self.require()
        return _workbook_read(path, "pyxlsb", dataset)
