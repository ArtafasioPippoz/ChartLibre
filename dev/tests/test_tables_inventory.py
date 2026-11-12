"""Project tables (the developer tool): the tables of a project and a preview of the selected one."""
from __future__ import annotations

import pandas as pd

from app.data.sqlite_repo import SqliteRepo
from dev.developer.tables_inventory import TablesInventoryDialog


def test_lists_the_tables_and_previews_the_selected_one(qapp, tmp_path) -> None:
    path = tmp_path / "t.dhub"
    repo = SqliteRepo(db_path=path)
    repo.import_dataframe(pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]}), table_name="data",
                          normalize_columns=False)
    repo.close()
    dialog = TablesInventoryDialog(None, path)
    names = [dialog.tables.item(row, 0).text() for row in range(dialog.tables.rowCount())]
    assert "data" in names
    dialog.tables.selectRow(names.index("data"))
    assert dialog.preview.rowCount() == 3 and dialog.preview.columnCount() == 2
    assert "3 of 3" in dialog.caption.text()
    dialog.done(0)
