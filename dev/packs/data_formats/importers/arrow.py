"""Apache Arrow's files: Parquet and Feather, read through pyarrow (moved from app/importers/columnar.py)."""
from __future__ import annotations

import pandas as pd

from app.plugin_api.importers.base import FileImporter, ImportedData


class ParquetImporter(FileImporter):
    Name = "Parquet"
    Description = "An Apache Parquet file."
    Suffixes = [".parquet", ".pq"]
    Category = "Columnar and scientific"
    Packages = ["pyarrow"]
    Order = 20

    def read(self, path: str, dataset: str | None = None) -> ImportedData:
        self.require()
        return ImportedData(frame=pd.read_parquet(path))


class FeatherImporter(FileImporter):
    Name = "Feather / Arrow"
    Description = "An Apache Arrow IPC file (Feather)."
    Suffixes = [".feather", ".arrow", ".ipc"]
    Category = "Columnar and scientific"
    Packages = ["pyarrow"]
    Order = 21

    def read(self, path: str, dataset: str | None = None) -> ImportedData:
        self.require()
        return ImportedData(frame=pd.read_feather(path))
