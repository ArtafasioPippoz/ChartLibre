"""NI TDMS files (LabVIEW, NI DAQ, VeriStand), read through npTDMS.

A TDMS file holds groups of channels. Each group is a dataset: its channels side by side, a Time column
first when the channels carry a waveform's timing (wf_start_offset, wf_increment). Channels of one group
that differ in length are padded with empty cells and said so. The file's, the group's and each channel's
properties are the metadata; a channel's unit_string its unit.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.plugin_api.importers.base import ALL_DATASETS, FileImporter, ImportedData, combine


def _plain(value: Any) -> Any:
    """A property as the metadata keeps it: numbers and text as they are, the rest (dates) as text."""
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, np.generic):
        return value.item()
    return str(value)


class TdmsImporter(FileImporter):
    Name = "NI TDMS"
    Description = "A National Instruments .tdms file (LabVIEW, DAQ): each group a dataset, its channels as columns."
    Suffixes = [".tdms"]
    Category = "Lab instruments"
    Packages = ["npTDMS"]
    Order = 40

    @staticmethod
    def _file(path: str):
        from nptdms import TdmsFile

        return TdmsFile.read(path)

    def datasets(self, path: str) -> list[str]:
        self.require()
        groups = [group.name for group in self._file(path).groups() if group.channels()]
        return groups if len(groups) > 1 else []

    def read(self, path: str, dataset: str | None = None) -> ImportedData:
        self.require()
        tdms = self._file(path)
        groups = [group for group in tdms.groups() if group.channels()]
        if not groups:
            raise ValueError("The file holds no channel with data.")
        metadata = {f"File {key}": _plain(value) for key, value in tdms.properties.items()}
        if dataset == ALL_DATASETS:
            frames, units, notes = {}, {}, []
            for group in groups:
                frame, group_units, group_notes = self._group(group)
                frames[group.name] = frame
                units.update(group_units)
                notes.extend(group_notes)
            return ImportedData(frame=combine(frames), metadata=metadata, units=units, notes=notes)
        group = next((group for group in groups if group.name == dataset), groups[0])
        frame, units, notes = self._group(group)
        metadata.update({f"Group {key}": _plain(value) for key, value in group.properties.items()})
        for channel in group.channels():
            metadata.update({f"{channel.name} {key}": _plain(value) for key, value in channel.properties.items()
                             if key != "unit_string"})
        return ImportedData(frame=frame, metadata=metadata, units=units, notes=notes)

    @staticmethod
    def _group(group) -> tuple[pd.DataFrame, dict[str, str], list[str]]:
        """A group's channels as columns, its waveform time first; units by column; what was done."""
        columns: dict[str, pd.Series] = {}
        units: dict[str, str] = {}
        notes: list[str] = []
        channels = group.channels()
        timed = next((channel for channel in channels if "wf_increment" in channel.properties), None)
        if timed is not None:
            columns["Time"] = pd.Series(timed.time_track())
            units["Time"] = str(timed.properties.get("wf_xunit_string", "s"))
        for channel in channels:
            columns[channel.name] = pd.Series(channel[:])
            if channel.properties.get("unit_string"):
                units[channel.name] = str(channel.properties["unit_string"])
        lengths = {len(values) for values in columns.values()}
        if len(lengths) > 1:
            notes.append(f"{group.name}: its channels have {min(lengths)} to {max(lengths)} values; "
                         "the shorter ones end in empty cells.")
        return pd.DataFrame(columns), units, notes
