"""The Column Info button beside the Data title opens even before a cell has been chosen."""
from __future__ import annotations

import time

import pandas as pd

from app.data.sqlite_repo import SqliteRepo
from app.dialogs import column_info_dialog
from app.main_window.main_window import MainWindow


def test_the_button_opens_the_first_column_when_no_cell_is_current(qapp, tmp_path, monkeypatch) -> None:
    repo = SqliteRepo(db_path=tmp_path / "c.dhub")
    repo.import_dataframe(pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]}), table_name="t", normalize_columns=False)
    window = MainWindow(repo, tmp_path / "c.dhub")
    try:
        window.resize(1200, 800)
        window.show()
        window._select_navigation("tables")
        end = time.monotonic() + 0.8
        while time.monotonic() < end:
            qapp.processEvents()
            time.sleep(0.005)
        opened: list[tuple] = []
        monkeypatch.setattr(column_info_dialog.ColumnInfoDialog, "exec", lambda self: opened.append(self) or 0)
        window._preview.column_info()
        assert len(opened) == 1
    finally:
        window.close()
